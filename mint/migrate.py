"""Move a pre-A2 art cache into the variant layout.

    mint migrate [--set sets/x.json ...] [--dry-run]

Before, a restyle was art/<id>.<style>.png and an upscale art/<id>.x4.png,
and nothing recorded the recipe that made them. Now every derived image is a
*variant* in art/<id>/ with a sidecar (see art.py). This walks every set file
in sets/ (plus any given with --set, e.g. experiments kept elsewhere), works
out the recipe each card's old file must have been made with, and moves the
file into place under that recipe's hash. Sets that predate the stable seed
rule get `"seed_rule": "position"` written into their style block so their
existing images stay current instead of being regenerated.

Files no set accounts for are listed at the end and left where they are.
"""
import argparse
import json
import os
import sys

from . import sets, workspace
from .art import Art
from .cards import Cards
from .errors import MintError
from .upscale import DEFAULT_MODEL, enhance_recipe


def claims_for_set(cards, art, st, dry_run=False):
    """(old file -> Variant) for every card of this set whose pre-A2 restyle exists."""
    claims = []
    if st.style is None:
        return claims
    if "seed_rule" not in _raw_style_keys(st.path):
        st.style.seed_rule = "position"
        if not dry_run:
            sets.save(st.path, st)
    for name in st.names():
        entry = st.card({"name": name})
        try:
            card = cards.find(name, entry.printing)
        except MintError as e:
            print(f"  skip {name}: {e}")
            continue
        old = art.dir / f"{card['illustration_id']}.{st.style.name}.png"
        if old.exists():
            recipe = st.recipe(card)
            claims.append((old, art.new_variant(card, st.style.name, "restyle", recipe, "crop", sets.recipe_hash(recipe))))
    return claims


def _raw_style_keys(path):
    return json.loads(path.read_text()).get("style", {}).keys()


def claims_for_upscales(cards, art):
    claims = []
    for old in sorted(art.dir.glob("*.x4.png")):
        iid = old.name[: -len(".x4.png")]
        card = cards.by_illustration(iid) or {"illustration_id": iid, "name": "?"}
        recipe = enhance_recipe(DEFAULT_MODEL, "crop")
        claims.append((old, art.new_variant(card, "enhance", "enhance", recipe, "crop", sets.recipe_hash(recipe))))
    return claims


def rehash(art, dry_run=False):
    """Rename any variant whose file name does not match its recipe's hash (the hash
    function changed, or an earlier migration computed it differently)."""
    n = 0
    for sc in sorted(art.dir.glob("*/*.json")):
        try:
            v = art._read(sc)
        except (json.JSONDecodeError, KeyError, TypeError):
            continue
        h = sets.recipe_hash(v.recipe)
        if h == v.hash:
            continue
        new = v.path.with_name(f"{v.label}-{h}.png")
        print(f"  {v.path.relative_to(art.dir)} -> {new.name}  (rehash)")
        n += 1
        if dry_run:
            continue
        os.replace(v.path, new)
        sc.unlink()
        v.hash, v.path = h, new
        art.record(v)
    return n


def apply(claims, art, dry_run=False):
    """Move each old file to its first claimant and hard-link it for the others: two sets
    that share a style name and a card both keep a current variant, at no disk cost."""
    by_old = {}
    for old, v in claims:
        by_old.setdefault(old, []).append(v)
    for old, vs in by_old.items():
        for k, v in enumerate(vs):
            print(f"  {old.name} -> {v.path.relative_to(art.dir)}" + ("  (link)" if k else "") + f"  {v.card}")
            if dry_run:
                continue
            v.path.parent.mkdir(parents=True, exist_ok=True)
            if k == 0:
                os.replace(old, v.path)
            else:
                os.link(vs[0].path, v.path)
            art.record(v)
    return set(by_old)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="mint migrate", description=__doc__.split("\n\n")[0])
    ap.add_argument("--set", action="append", default=[], help="extra set files beyond sets/*.json")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    ws = workspace.default()
    cards, art = Cards(ws.cards_file), Art(ws.art)
    paths = sorted(ws.sets.glob("*.json")) + [os.path.abspath(p) for p in a.set]
    claims = []
    for p in paths:
        try:
            st = sets.load(p)
        except MintError as e:
            print(f"skip {p}: {e}")
            continue
        print(f"{p}: style {st.style.name if st.style else '-'}")
        claims += claims_for_set(cards, art, st, a.dry_run)
    claims += claims_for_upscales(cards, art)
    moved = apply(claims, art, a.dry_run)
    rehashed = rehash(art, a.dry_run)
    if rehashed:
        print(f"{'would rename' if a.dry_run else 'renamed'} {rehashed} variant(s) to their recipe hash")
    left = sorted(f.name for f in art.dir.glob("*.png") if not f.name.startswith("scan_") and f not in moved)
    print(f"\n{'would move' if a.dry_run else 'moved'} {len(moved)} file(s) into {len(claims)} variant(s)")
    if left:
        print(f"{len(left)} file(s) no set accounts for (give their set with --set, or delete them):")
        for f in left:
            print("  " + f)
    return 0 if not left else 1


if __name__ == "__main__":
    sys.exit(main())

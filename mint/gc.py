"""Say what in the art cache and the renders is no longer needed, and delete it on request.

    mint gc [--delete] [--keep-days 3] [--set CODE]

The art cache keeps every take ever made, by design: a changed knob is a new
file beside the old one. That is right while a look is being chosen and
wrong forever after. This walks every set and keeps, per card:

    the picked variant and the recipe's current one, whatever a styled render
    used, the image each of those was made from (the base chain), the
    enhances and the clips (motion variants) of any of those, and anything
    made in the last --keep-days.

Every other variant of that card is a candidate, and so is every variant
directory no set's card refers to. Renders are judged against the manifest:
an entry whose file is gone is dropped, a PNG the manifest does not know is
an orphan, and an entry is *stale* when the frame (template, frame.py, knobs, set css)
or the art it should render with has changed since, or the card left the
set -- unless the card is pinned to it, which says it prints as it is.
Nothing is removed without --delete; the report says what would be.
"""
import argparse
import datetime as dt
import sys

from pathlib import Path

from . import frame, renders, sets, workspace
from .art import Art
from .cards import Cards
from .errors import MintError
from .manifest import Manifest, frame_hash


def mb(paths):
    return sum(p.stat().st_size for p in paths if p.exists()) / 1e6


def files_of(v):
    """A variant's image and, for a clip, the videos beside it."""
    return [v.path, *v.videos]


def keep_hashes(st, card, entry, art, render_sources):
    """The variant hashes of this card that must stay, and why (hash -> reason)."""
    keep = {}
    if entry.pick:
        keep[entry.pick] = "picked"
    if st.style:
        try:
            keep.setdefault(sets.recipe_hash(st.recipe(card, art=art)), "the recipe's")
        except MintError:
            pass
    for h in render_sources:
        keep.setdefault(h, "a render uses it")
    # the base chain: what a kept variant was made from, and the enhances made from any kept one
    by_hash = {v.hash: v for v in art.variants(card)}
    frontier = list(keep)
    while frontier:
        v = by_hash.get(frontier.pop())
        if v and sets.HASH_RE.match(v.base or "") and v.base not in keep:
            keep[v.base] = "a kept variant starts from it"
            frontier.append(v.base)
    for v in by_hash.values():
        if v.kind == "enhance" and v.base in keep and v.hash not in keep:
            keep[v.hash] = "an enhance of a kept one"
        elif v.kind == "motion" and v.base in keep and v.hash not in keep:
            keep[v.hash] = "a clip of a kept one"
    return keep


def render_state(ws, st, cards, art, owned=None):
    """(stale entries [(manifest, filename, reason)], orphan files, dropped entries) for a set's out/ dir.

    `owned` is every card name the out/ directory belongs to. It is wider than this set when two set
    files share a code, because they then share the directory (sets/mer.json and sets/mer-missing.json
    are both MER): a render is only orphaned when *no* set writing there still lists its card, so
    judging by this set alone would call the other's renders abandoned and offer them for deletion."""
    out = ws.home / "out" / st.code.lower()
    m = Manifest(out)
    fh = frame_hash(st.css, frame.frame_css(st.frame))
    stale, dropped, sources = [], [], {}
    if owned is None:
        owned = set(st.cards) | {f.get("name") for f in _faces(cards, st)}
    for fn, e in list(m.entries.items()):
        p = out / fn
        if not p.exists():
            dropped.append(fn)
            continue
        name = e.get("card")
        if name not in owned:
            stale.append((m, fn, "the card left the set"))
            continue
        if name not in st.cards and not any(name == f.get("name") for f in _faces(cards, st)):
            continue  # a set sharing this directory owns it; its own pass judges its frame and art
        try:
            card = cards.find(name, *st.lookup(name))
        except MintError:
            stale.append((m, fn, "the card is not in the card file"))
            continue
        entry = st.card(card)
        if entry.render == fn:  # the render the card is pinned to prints as it is; it is never stale
            sources.setdefault(card["illustration_id"], set()).add((e.get("source") or {}).get("hash"))
            continue
        design = st.design_of(card)
        src = (art.resolve(card, override=entry.art, style_hash=st.styled_hash(card, art=art), design=design,
                           fetch=False) if e.get("styled")
               else art.resolve(card, override=entry.art, design=design, fetch=False))
        was = e.get("source") or {}
        # the recipe hash alone does not identify a picture (renders.art_key says why): compare the
        # illustration too, or a render whose printing changed reads as current
        current = was.get("hash") == src.hash and (not was.get("path")
                                                   or renders.art_key(was["path"]) == renders.art_key(src.path))
        if e.get("frame") != fh:
            stale.append((m, fn, "the frame changed"))
        elif not current:
            stale.append((m, fn, "the art changed"))
        else:
            sources.setdefault(card["illustration_id"], set()).add((e.get("source") or {}).get("hash"))
    orphans = [p for p in out.glob("*.png") if p.name not in m.entries] if out.is_dir() else []
    return stale, orphans, dropped, m, sources


def _faces(cards, st):
    """The back faces of the set's cards, for renders named after them."""
    out = []
    for n in st.names():
        try:
            out += cards.find(n, *st.lookup(n)).get("card_faces") or []
        except MintError:
            pass
    return out


def collect(ws, only=None, keep_days=3):
    """The report: per set, the variants and renders that can go. `only` names one set, either as the
    path of its file -- every other command's --set is a path, so gc takes one rather than quietly
    matching nothing -- or as its code. A path names exactly one file; a code names every file
    carrying it, and two files may (sets/mer.json and sets/mer-missing.json are both MER)."""
    stem = None
    if only and only.lower().endswith(".json"):
        stem, only = Path(only).stem.lower(), None
    cards, art = Cards(ws.cards_file), Art(ws.art)
    cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=keep_days)).isoformat()
    report = {"variants": [], "stale": [], "orphans": [], "dropped": [], "unreferenced": [], "errors": []}
    referenced = set()
    loaded = []
    for p in ws.set_files():
        try:
            loaded.append((p, sets.load(p)))
        except MintError as e:
            report["errors"].append(f"{p.name}: {e}")

    def picked(p, st):
        if stem is not None:
            return p.stem.lower() == stem
        return not only or st.code.lower() == only.lower()

    # The art cache is keyed by illustration, so one picture is shared by every set that prints the
    # card. What must stay is therefore the union over *all* sets -- their picks, recipes and the
    # variants their renders use -- even when the report is narrowed to one set. Asking only the
    # named set would offer another set's restyles for deletion.
    # Keyed by file, not by code: two set files can share a code and share an out/ directory.
    owned = {}
    for _, st in loaded:
        owned.setdefault(st.code.lower(), set()).update(
            set(st.cards) | {f.get("name") for f in _faces(cards, st)})

    state, sources_all = {}, {}
    for p, st in loaded:
        stale, orphans, dropped, m, sources = render_state(ws, st, cards, art, owned[st.code.lower()])
        state[p] = (stale, orphans, dropped, m)
        for illus, hs in sources.items():
            sources_all.setdefault(illus, set()).update(hs)

    keep_all = {}
    for _, st in loaded:
        for name in st.names():
            try:
                card = cards.find(name, *st.lookup(name))
            except MintError:
                continue
            referenced.add(card["illustration_id"])
            keep_all.setdefault(card["illustration_id"], set()).update(
                keep_hashes(st, card, st.card(card), art, sources_all.get(card["illustration_id"], ())))

    seen = set()
    for p, st in loaded:
        if not picked(p, st):
            continue
        stale, orphans, dropped, m = state[p]
        report["stale"] += [(st.code, m, fn, why) for m, fn, why in stale]
        report["orphans"] += orphans
        report["dropped"] += [(st.code, m, fn) for fn in dropped]
        for name in st.names():
            try:
                card = cards.find(name, *st.lookup(name))
            except MintError:
                continue
            keep = keep_all.get(card["illustration_id"], ())
            for v in art.variants(card):
                if v.hash in keep or (v.created or "") >= cutoff:
                    continue
                if (card["illustration_id"], v.hash) in seen:  # a card two selected sets share
                    continue
                seen.add((card["illustration_id"], v.hash))
                report["variants"].append((st.code, name, v))
    if not only and stem is None:  # only a whole-workspace run can tell what nothing refers to
        for d in sorted(x for x in ws.art.iterdir() if x.is_dir()):
            if d.name not in referenced:
                report["unreferenced"].append(d)
    return report


def main(argv=None):
    ap = argparse.ArgumentParser(prog="mint gc", description=__doc__.split("\n\n")[0])
    ap.add_argument("--delete", action="store_true", help="remove what the report lists")
    ap.add_argument("--keep-days", type=int, default=3, help="variants younger than this stay (default 3)")
    ap.add_argument("--set", help="one set only (its cards' variants and its renders)")
    a = ap.parse_args(argv)
    ws = workspace.default()
    try:
        r = collect(ws, a.set, a.keep_days)
    except MintError as e:
        sys.exit(str(e))
    for e in r["errors"]:
        print(f"  skipped  {e}")
    vs = r["variants"]
    print(f"variants not picked, current, rendered, a base of one of those, or under {a.keep_days} days old: "
          f"{len(vs)}, {mb([p for _, _, v in vs for p in files_of(v)]):.0f} MB")
    for code, name, v in vs:
        print(f"  {code} {name}: {v.label}-{v.hash} ({v.kind}, {v.created[:10]})")
    un = r["unreferenced"]
    if un:
        files = [p for d in un for p in d.iterdir()]
        print(f"variant directories no set's card refers to: {len(un)}, {mb(files):.0f} MB")
        for d in un:
            print(f"  {d.name}")
    st = r["stale"]
    print(f"stale renders (the frame or the art changed since, or the card left): {len(st)}, "
          f"{mb([m.path.parent / fn for _, m, fn, _ in st]):.0f} MB")
    for code, _, fn, why in st:
        print(f"  {code} {fn}: {why}")
    if r["orphans"]:
        print(f"renders the manifest does not know: {len(r['orphans'])}, {mb(r['orphans']):.0f} MB")
        for p in r["orphans"]:
            print(f"  {p}")
    if r["dropped"]:
        print(f"manifest entries whose file is gone: {len(r['dropped'])}")
    if not a.delete:
        if vs or un or st or r["orphans"] or r["dropped"]:
            print("\nnothing removed; --delete does")
        else:
            print("\nnothing to remove")
        return 0
    art = Art(ws.art)
    for _, _, v in vs:
        art.delete(v)
    for d in un:
        for p in d.iterdir():
            p.unlink()
        d.rmdir()
    touched = set()
    for _, m, fn, _ in st:
        m.remove(fn)
        touched.add(m)
    for _, m, fn in r["dropped"]:
        m.entries.pop(fn, None)
        touched.add(m)
    for m in touched:
        m.save()
    for p in r["orphans"]:
        p.unlink()
    print(f"\nremoved {len(vs)} variant(s), {len(un)} directorie(s), {len(st)} stale render(s), {len(r['orphans'])} orphan(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Enhance card art through a local ComfyUI server: a 4x ESRGAN pass.

    mint upscale [--model 4x-UltraSharp.pth] [--set sets/x.json] [--base crop|HASH] ["Card Name" ...]

Scryfall's art crops are ~300 DPI on the card; a 4x ESRGAN pass brings them
to ~1200, matching the vector frame. The result is an `enhance` variant in
art/<illustration_id>/ (see art.py) and `mint render` prefers it over the raw
crop automatically. --base enhances a restyled variant instead of the crop;
renders of that style then pick the enhanced one up. Cards already enhanced
with this model from this base are skipped unless --force.

With a --set, the default base follows each card's frame design: a design that
cuts its picture out of the printing's own scan (art.cut) is enhanced from that
cut, since that is the picture the card renders with.

Needs ComfyUI running (python main.py --listen 127.0.0.1 --port 8188) with an
upscale model in its models/upscale_models/. Tested with RealESRGAN_x4plus.pth
and 4x-UltraSharp.pth.
"""
import argparse
import os
import sys

from . import art as artlib
from . import comfy, sets, workspace
from .art import Art
from .cards import Cards
from .errors import MintError

DEFAULT_MODEL = "4x-UltraSharp.pth"


def enhance_recipe(model=DEFAULT_MODEL, base="crop"):
    return {"model": model, "base": base}


def enhance(server, art, card, model=DEFAULT_MODEL, base="crop", force=False, design=None):
    """Make (or find) the enhance variant of `base` for this card. Returns (Variant, made).
    A base given by label ("spore") means this card's newest such variant. "crop" means the card's
    base picture, which for a card whose frame `design` cuts its art out of the printing's own scan
    is that cut and not Scryfall's crop -- so an enhance always lands on the picture the card renders
    with. "cut" (or "cut:<design>") asks for the cut by name, and says so when the printing has none."""
    if base == "crop" or artlib.is_cut(base):
        named = artlib.CUT_BASE.match(base).group(1) if artlib.is_cut(base) else design
        cut = art.cut_for(card, named or design)
        if cut:
            base = artlib.cut_base(cut)
        elif artlib.is_cut(base):
            raise MintError(f"{card['name']}: no scan cut for this card -- "
                            + (f"its printing is not {named}" if named else "name the design, as 'cut:textless'"))
    if sets.is_label(base):
        v = art.latest(card, base)
        if not v:
            raise MintError(f"{card['name']}: no {base!r} variant yet to enhance")
        base = v.hash
    recipe = enhance_recipe(model, base)
    h = sets.recipe_hash(recipe)
    if not force:
        v = art.variant(card, h)
        if v:
            return v, False
    src = art.base_path(card, base)
    v = art.new_variant(card, "enhance", "enhance", recipe, base, h)
    v.path.parent.mkdir(parents=True, exist_ok=True)
    name = server.upload(str(src))
    server.run_to_file(comfy.upscale_workflow(name, model, "tcg-mint/" + card["illustration_id"]), str(v.path))
    return art.record(v), True


def main(argv=None):
    ap = argparse.ArgumentParser(prog="mint upscale", description=__doc__.split("\n\n")[0])
    ap.add_argument("names", nargs="*")
    ap.add_argument("--set", help="set JSON; enhances every card in it when no names are given")
    ap.add_argument("--model", default=DEFAULT_MODEL,
                    help=f"file in ComfyUI's models/upscale_models (default {DEFAULT_MODEL})")
    ap.add_argument("--base", default="crop",
                    help="what to enhance: crop (default; the scan cut for a design that has one), "
                         "cut[:design], or a variant hash")
    ap.add_argument("--force", action="store_true", help="redo cards that already have this enhance")
    a = ap.parse_args(argv)
    ws = workspace.default()
    try:
        st = sets.load(a.set) if a.set else None
        names = a.names or (st.names() if st else [])
        if not names:
            ap.error("give card names or a --set")
        server = comfy.Comfy(ws.comfy_url)
        server.require()
        cards, art = Cards(ws.cards_file), Art(ws.art)
        for name in names:
            card = cards.find(name, *(st.lookup(name) if st else (None, None)))
            v, made = enhance(server, art, card, a.model, a.base, a.force, design=st.design_of(card) if st else None)
            print(f"{'enhanced' if made else 'cached  '} {card['name']} -> {os.path.relpath(v.path)}")
    except MintError as e:
        sys.exit(str(e))


if __name__ == "__main__":
    main()

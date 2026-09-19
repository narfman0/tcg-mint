"""Upscale card art through a local ComfyUI server.

    mint upscale [--model 4x-UltraSharp.pth] [--set sets/x.json] ["Card Name" ...]

Scryfall's art crops are ~300 DPI on the card; a 4x ESRGAN pass brings them
to ~1200, matching the vector frame. Results land in art/<illustration_id>.x4.png
and `mint render` prefers them over the raw crop automatically. Cards already
upscaled are skipped unless --force.

Needs ComfyUI running (python main.py --listen 127.0.0.1 --port 8188) with an
upscale model in its models/upscale_models/. Tested with RealESRGAN_x4plus.pth
and 4x-UltraSharp.pth.
"""
import argparse
import os
import sys

from . import comfy, sets, workspace
from .art import Art
from .cards import Cards
from .errors import MintError

DEFAULT_MODEL = "4x-UltraSharp.pth"


def upscale_file(server, src, dest, model=DEFAULT_MODEL, prefix="tcg-mint/enhance"):
    """ESRGAN any image file through ComfyUI into dest."""
    name = server.upload(str(src))
    return server.run_to_file(comfy.upscale_workflow(name, model, prefix), str(dest))


def upscale(server, art, card, model=DEFAULT_MODEL, force=False):
    dest = art.upscaled(card)
    if dest.exists() and not force:
        return dest, False
    upscale_file(server, art.crop(card), dest, model, "tcg-mint/" + card["illustration_id"])
    return dest, True


def main(argv=None):
    ap = argparse.ArgumentParser(prog="mint upscale", description=__doc__.split("\n\n")[0])
    ap.add_argument("names", nargs="*")
    ap.add_argument("--set", help="set JSON; upscales every card in it when no names are given")
    ap.add_argument("--model", default=DEFAULT_MODEL,
                    help=f"file in ComfyUI's models/upscale_models (default {DEFAULT_MODEL})")
    ap.add_argument("--force", action="store_true", help="redo cards that already have an upscale")
    a = ap.parse_args(argv)
    ws = workspace.default()
    try:
        st = sets.load(a.set)[0] if a.set else {}
        names = a.names or list(st.get("cards", {}))
        if not names:
            ap.error("give card names or a --set")
        server = comfy.Comfy(ws.comfy_url)
        server.require()
        cards, art = Cards(ws.cards_file), Art(ws.art)
        for name in names:
            card = cards.find(name, sets.overrides(st, {"name": name}).get("printing"))
            dest, did = upscale(server, art, card, a.model, a.force)
            print(f"{'upscaled' if did else 'cached  '} {card['name']} -> {os.path.relpath(dest)}")
    except MintError as e:
        sys.exit(str(e))


if __name__ == "__main__":
    main()

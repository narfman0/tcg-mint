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

from . import ART, comfy, render

DEFAULT_MODEL = "4x-UltraSharp.pth"


def upscaled_path(card):
    return ART / (card["illustration_id"] + ".x4.png")


def upscale(card, model, force=False):
    dest = upscaled_path(card)
    if dest.exists() and not force:
        return dest, False
    src = render.art_path(card, upscaled=False)[len("file://"):]  # the raw crop, fetched if needed
    name = comfy.upload(src)
    prefix = "tcg-mint/" + card["illustration_id"]
    outputs = comfy.run(comfy.upscale_workflow(name, model, prefix))
    images = [im for node in outputs.values() for im in node.get("images", [])]
    if not images:
        raise comfy.ComfyError("workflow produced no image")
    comfy.fetch(images[0], dest)
    return dest, True


def main(argv=None):
    ap = argparse.ArgumentParser(prog="mint upscale", description=__doc__.split("\n\n")[0])
    ap.add_argument("names", nargs="*")
    ap.add_argument("--set", help="set JSON; upscales every card in it when no names are given")
    ap.add_argument("--model", default=DEFAULT_MODEL, help=f"file in ComfyUI's models/upscale_models (default {DEFAULT_MODEL})")
    ap.add_argument("--force", action="store_true", help="redo cards that already have an upscale")
    a = ap.parse_args(argv)
    st, _ = render.load_set(a.set)
    names = a.names or list(st.get("cards", {}))
    if not names:
        ap.error("give card names or a --set")
    if not comfy.alive():
        sys.exit(f"no ComfyUI at {comfy.URL}; start it with: python main.py --listen 127.0.0.1 --port 8188")
    for name in names:
        card = render.load_card(name)
        try:
            dest, did = upscale(card, a.model, a.force)
        except comfy.ComfyError as e:
            sys.exit(f"{card['name']}: {e}")
        print(f"{'upscaled' if did else 'cached  '} {card['name']} -> {os.path.relpath(dest)}")


if __name__ == "__main__":
    main()

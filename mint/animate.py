"""A short seamless clip of a card's art through ComfyUI (Wan 2.2).

    mint animate --set sets/x.json [--force] [--remix new] [--from <hash|crop>] ["Card Name" ...]

The card's styled art -- the file `render --styled` uses, enhance included --
is the start frame of an image-to-video run; the set's SDXL look reaches the
clip that way, since Wan cannot run an SDXL LoRA but can animate the picture
one made. The frames are looped (loop.py) and encoded beside a poster:

    art/<illustration_id>/<label>-<hash>.png     the poster, frame 0 of the loop: a variant of kind `motion`
    art/<illustration_id>/<label>-<hash>.webm    the loop, in each format asked for

The recipe is the set file's `motion` block (sets.Motion; every knob has a
default, so a set without one still animates), the card's own `motion` line
in place of the prompt, and the image it starts from:

    "motion": {
      "prompt": "hair drifts as if underwater, fabric sways; the camera is still",
      "remix": "animate",           animate: from the card's styled art (I2V) | new: from words alone (T2V)
      "width": 832, "height": 576,  multiples of 32; the art window is 1.42:1
      "length": 49, "fps": 24,      frames, 4n+1: 49 is two seconds, 81 is ~3.4 s
      "steps": 20, "cfg": 5, "shift": 8, "sampler": "uni_pc", "scheduler": "simple",
      "loop": "pingpong",           pingpong | crossfade | none
      "formats": ["webm"],          webm | gif | apng | mp4
      "model": "wan2.2_ti2v_5B_fp16.safetensors", ...
    }

Say what moves and what stays still; "cinematic" and "camera pans" get a
music video. The effective recipe (sets.SetFile.motion_recipe) is hashed
into the file name, so a re-restyle of the base, or any knob, is a new
variant beside the old one. The raw frames are not kept: re-looping means
regenerating, and the 5B model takes about a minute a clip on a 16 GB card.
ffmpeg does the encoding.
"""
import argparse
import os
import sys
import tempfile

from PIL import Image

from . import comfy, loop, sets, wan, workspace
from .art import Art
from .cards import Cards
from .errors import MintError, SetError


def animate_file(server, src, stem, recipe, prefix="tcg-mint/animate"):
    """Run the motion workflow on any image file (None in `new` mode): the poster to <stem>.png and
    the loop to <stem>.<fmt> for each format. Returns the files written."""
    if not loop.have_ffmpeg():
        raise MintError("ffmpeg is not on PATH; animate needs it to encode the clip (dnf/apt install ffmpeg)")
    name = server.upload(str(src)) if src is not None else None
    with tempfile.TemporaryDirectory() as t:
        paths = server.run_to_frames(wan.workflow(name, recipe, recipe["seed"], prefix), t)
        frames = [Image.open(p).convert("RGB") for p in paths]
    seq = loop.looped(frames, recipe["loop"], recipe.get("crossfade", 0))
    os.makedirs(os.path.dirname(stem) or ".", exist_ok=True)
    made = [f"{stem}.png"]
    seq[0].save(made[0])
    for fmt in recipe["formats"]:
        made.append(loop.encode(seq, f"{stem}.{fmt}", recipe["fps"], fmt, recipe.get("gif_width", 0)))
    return made


def animate(server, art, card, st, motion=None, force=False, seed=None, remix=None, base=None):
    """Make (or find) the motion variant of `card` for the set's motion block (or `motion`, a
    sets.Motion, for a one-off recipe). `seed` forces a one-off seed, `remix` a one-off mode and
    `base` the image to start from (a variant hash or "crop"; else the card's styled art).
    Returns (Variant, made)."""
    motion = motion or st.motion or sets.Motion()
    recipe = st.motion_recipe(card, motion, art, seed=seed, remix=remix, base=base)
    h = sets.recipe_hash(recipe)
    if not force:
        v = art.variant(card, h)
        if v:
            return v, False
    v = art.new_variant(card, motion.name, "motion", recipe, recipe["base"], h)
    src = None if recipe["base"] == "none" else art.base_path(card, recipe["base"])
    animate_file(server, src, str(v.path.with_suffix("")), recipe,
                 "tcg-mint/" + card["illustration_id"] + "." + motion.name)
    return art.record(v), True


def main(argv=None):
    ap = argparse.ArgumentParser(prog="mint animate", description=__doc__.split("\n\n")[0])
    ap.add_argument("names", nargs="*")
    ap.add_argument("--set", required=True)
    ap.add_argument("--force", action="store_true", help="regenerate cards that already have this clip")
    ap.add_argument("--remix", choices=sets.MOTION_REMIX, help="the mode for this run, whatever the block says")
    ap.add_argument("--from", dest="base", metavar="HASH", help="the image to animate: a variant hash or crop; "
                    "default the card's styled art")
    a = ap.parse_args(argv)
    ws = workspace.default()
    try:
        st = sets.load(a.set)
        names = a.names or st.names()
        if not names:
            ap.error("the set has no cards")
        server = comfy.client(ws)
        server.require()
        cards, art = Cards(ws.cards_file), Art(ws.art)
        for name in names:
            card = cards.find(name, *st.lookup(name))
            v, made = animate(server, art, card, st, force=a.force, remix=a.remix, base=a.base)
            clips = ", ".join(os.path.relpath(p) for p in v.videos) or os.path.relpath(v.path)
            print(f"{'animated' if made else 'cached  '} {card['name']} -> {clips}")
    except (MintError, SetError) as e:
        sys.exit(str(e))


if __name__ == "__main__":
    main()

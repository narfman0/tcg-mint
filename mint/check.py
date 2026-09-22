"""Check set files and report what each card has.

    mint check [sets/x.json ...]

Validates every set file (sets/ by default) against the
schema, looks
each card up, and says which image a plain and a styled render would use:
whether the current recipe has a restyle variant, whether the crop has been
enhanced, whether the card has a clip for the current motion recipe (and
which image it would animate), any warnings about the printing, and the
frame design a card renders in when it is not the M15 frame -- with a warning
when the picture is the wrong shape for it, or has too few pixels to fill it
at the 800 DPI `mint export` writes for MPC Autofill.
"""
import argparse
import sys

from PIL import Image

from . import frame, sets, workspace
from .art import Art
from .cards import Cards, warnings
from .errors import MintError
from .export import MAX_DPI as ORDER_DPI  # what `mint export` writes for MPC Autofill


def art_fit(path, design):
    """Why the picture at `path` does not fit the design's art rectangle: an aspect more than 15% off
    it is cut hard by `cover` (the M15 window into a full-art card loses its sides), else None."""
    try:
        with Image.open(path) as im:
            aspect = im.width / im.height
    except (OSError, ValueError):
        return None
    want = frame.art_aspect(design)
    if abs(aspect / want - 1) <= 0.15:
        return None
    shape = "wider" if aspect > want else "taller"
    return f"the picture is {aspect:.2f}:1, {shape} than the {design} design's {want:.2f}:1 -- cover crops it"


def art_thin(path, design, dpi=ORDER_DPI):
    """Why the picture at `path` has too few pixels for the design's art window at `dpi`, or None.
    `cover` never stretches a picture -- it keeps the aspect and crops -- so this is about
    resolution: below the window's pixel count the browser interpolates the difference."""
    try:
        with Image.open(path) as im:
            have = im.size
    except (OSError, ValueError):
        return None
    w, h, _ = frame.DESIGNS[design]
    want = (round(w / 100 * dpi), round(h / 100 * dpi))
    f = max(want[0] / have[0], want[1] / have[1])
    if f <= 1.05:
        return None
    return (f"the picture is {have[0]}x{have[1]} and the {design} window wants {want[0]}x{want[1]} at {dpi} DPI "
            f"-- {f:.1f}x up; `mint upscale` gives it the pixels")


def check_set(ws, cards, art, st):
    problems = 0
    print(f"{st.path}: {st.code} '{st.name}', {len(st.cards)} cards, style {st.style.name if st.style else '-'}")
    for name in st.names():
        entry = st.card({"name": name})
        try:
            card = cards.find(name, *st.lookup(name))
        except MintError as e:
            print(f"  !! {name}: {e}")
            problems += 1
            continue
        notes = [f"warn: {w}" for w in warnings(card)]
        design = st.design_of(card)
        if design != "m15":
            notes.append(f"design: {design}")
        plain = art.resolve(card, override=entry.art, enhance=True) if art.crop(card, fetch=False).exists() or entry.art \
            else None
        notes.append(f"plain: {plain.describe() if plain else 'crop not fetched'}")
        if plain and (fit := art_fit(plain.path, design)):
            notes.append(f"warn: {fit}")
        if plain and (thin := art_thin(plain.path, design)):
            notes.append(f"warn: {thin}")
        h = st.styled_hash(card, art=art)
        if h:
            v = art.variant(card, h)
            picked = " (picked)" if entry.pick else ""
            notes.append(f"styled: {v.label}-{v.hash}{picked}" if v else f"styled: missing ({h}{picked})")
        if st.style:
            recipe = st.recipe(card, art=art)
            if sets.is_label(recipe["base"]):
                notes.append(f"base {recipe['base']}: none yet")
        if st.motion:
            mr = st.motion_recipe(card, art=art)
            mv = art.variant(card, sets.recipe_hash(mr))
            notes.append(f"motion: {mv.label}-{mv.hash}" if mv else f"motion: missing ({sets.recipe_hash(mr)} from {mr['base']})")
        others = [v for v in art.variants(card)]
        if others:
            notes.append(f"{len(others)} variant(s)")
        print(f"  {entry.number or '-':>3} {card['name']:36} {' | '.join(notes)}")
    return problems


def main(argv=None):
    ap = argparse.ArgumentParser(prog="mint check", description=__doc__.split("\n\n")[0])
    ap.add_argument("paths", nargs="*")
    a = ap.parse_args(argv)
    ws = workspace.default()
    paths = a.paths or ws.set_files()
    cards, art = Cards(ws.cards_file), Art(ws.art)
    problems = 0
    for p in paths:
        try:
            st = sets.load(p)
        except MintError as e:
            print(f"!! {e}")
            problems += 1
            continue
        problems += check_set(ws, cards, art, st)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())

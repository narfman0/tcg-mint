"""Check set files and report what each card has.

    mint check [sets/x.json ...]

Validates every set file (sets/ and sets/private/ by default) against the
schema, looks
each card up, and says which image a plain and a styled render would use:
whether the current recipe has a restyle variant, whether the crop has been
enhanced, and any warnings about the printing.
"""
import argparse
import sys

from . import sets, workspace
from .art import Art
from .cards import Cards, warnings
from .errors import MintError


def check_set(ws, cards, art, st):
    problems = 0
    print(f"{st.path}: {st.code} '{st.name}', {len(st.cards)} cards, style {st.style.name if st.style else '-'}")
    for name in st.names():
        entry = st.card({"name": name})
        try:
            card = cards.find(name, entry.printing)
        except MintError as e:
            print(f"  !! {name}: {e}")
            problems += 1
            continue
        notes = [f"warn: {w}" for w in warnings(card)]
        plain = art.resolve(card, override=entry.art, enhance=True) if art.crop(card, fetch=False).exists() or entry.art \
            else None
        notes.append(f"plain: {plain.describe() if plain else 'crop not fetched'}")
        h = st.styled_hash(card, art=art)
        if h:
            v = art.variant(card, h)
            picked = " (picked)" if entry.pick else ""
            notes.append(f"styled: {v.label}-{v.hash}{picked}" if v else f"styled: missing ({h}{picked})")
        if st.style:
            recipe = st.recipe(card, art=art)
            if sets.is_label(recipe["base"]):
                notes.append(f"base {recipe['base']}: none yet")
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

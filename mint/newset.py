"""Start a set file from a plain decklist.

    mint newset --code SAT --name "Satoru, ..." [--style neon] [--private] [--out sets/satoru.json] decklist.txt

The decklist is `<count> <Card Name>` per line, mainboard first, then a blank
line and the commander(s); anything from the first `#` header on is ignored
(that is where Moxfield exports put sideboard/maybeboard sections). The
commander becomes card 1 and the rest follow in list order. An existing set
file is updated in place: new cards are appended, numbers and per-card edits
(flavor, subject, art) are kept.

--style seeds the set's `style` block from a template in styles/ (see
style.py) or one of the built-in recipes (`neon`, `ink`, `glass`); edit it
afterwards, it is just JSON. A template's .css becomes the set's .css.
--private puts the set in sets/private/, which git ignores.
"""
import argparse
import os
import re
import sys
from pathlib import Path

from . import sets, style, workspace
from .errors import MintError

STYLES = {
    "neon": {
        "name": "neon",
        "prompt": "cyberpunk fantasy illustration, neon-lit rain-slick night city, holographic signage and glowing kanji, "
                  "chrome and black lacquer, magenta and cyan rim light, volumetric haze, detailed digital painting, "
                  "dramatic cinematic composition",
        "negative": "blurry, low quality, text, watermark, signature, frame, border, deformed, daylight, pastel, nude, nsfw",
        "control": "canny", "control_strength": 0.75, "denoise": 0.85, "steps": 28, "cfg": 6, "seed": 7,
    },
    # pen-and-ink: the prompt has to say "drawing" loudly or a photoreal checkpoint
    # just paints in grey; the source is desaturated so no colour survives the latent
    "ink": {
        "name": "ink",
        "prompt": "manga page, pen and ink drawing, pure black ink on white paper, bold confident brush-pen linework, "
                  "dense cross-hatching for shadow, screentone, high contrast, no gray wash, dark fantasy, "
                  "grotesque detail",
        "negative": "grayscale painting, soft gradients, photograph, photorealistic, blurry, low quality, text, "
                    "watermark, signature, frame, border, colour, color, nude, nsfw",
        "control": "lineart", "control_strength": 0.8, "control_end": 0.8,
        "denoise": 0.95, "steps": 30, "cfg": 7.5, "seed": 11, "grayscale_source": True,
    },
    "glass": {
        "name": "glass",
        "prompt": "stained glass window illustration, art nouveau, thick black leading between panes of jewel-toned "
                  "glass, backlit, ornamental borders and flowing curves, gold and ruby and sapphire, "
                  "art-nouveau decorative composition, cathedral window",
        "negative": "blurry, low quality, text, watermark, signature, frame, photographic, realistic, 3d render, "
                    "nude, nsfw, portrait of a woman",
        "control": "canny", "control_strength": 0.7, "denoise": 0.88, "steps": 28, "cfg": 6, "seed": 23,
    },
}


def read_decklist(path):
    main, commanders = [], []
    section = main
    for line in open(path):
        line = line.rstrip("\n")
        if line.startswith("#"):
            break
        if not line.strip():
            section = commanders
            continue
        m = re.match(r"(\d+)x?\s+(.+)", line.strip())
        if m:
            section.append(m.group(2).strip())
    if not commanders:  # no blank line: whole list is the deck
        return main
    return commanders + main


def main(argv=None):
    ap = argparse.ArgumentParser(prog="mint newset", description=__doc__.split("\n\n")[0])
    ap.add_argument("decklist")
    ap.add_argument("--code", required=True, help="set code, e.g. SAT (the company code is added by the renderer)")
    ap.add_argument("--name", required=True)
    ap.add_argument("--style", help="seed the style block from a template in styles/ or a built-in recipe")
    ap.add_argument("--private", action="store_true", help="put the set in sets/private/, which git ignores")
    ap.add_argument("--out", help="set file (default sets/<code lowercased>.json)")
    a = ap.parse_args(argv)
    ws = workspace.default()
    out = a.out or str((ws.sets / ws.PRIVATE if a.private else ws.sets) / (a.code.lower() + ".json"))

    st = sets.load(out) if os.path.exists(out) else sets.SetFile(code=a.code, name=a.name)
    st.code, st.name = a.code, a.name
    css = None
    if a.style and st.style is None:
        try:
            st.style, css = style.load(ws, a.style)
        except MintError as e:
            raise SystemExit(str(e)) from None

    names = read_decklist(a.decklist)
    seen = set()
    names = [n for n in names if not (n in seen or seen.add(n))]  # basic lands repeat
    cards = st.cards
    nxt = max((c.number or 0 for c in cards.values()), default=0) + 1
    added = 0
    for n in names:
        if n not in cards:
            cards[n] = sets.CardEntry(number=nxt)
            nxt += 1
            added += 1
    st.size = len(cards)
    sets.save(out, st)
    css_fn = Path(out).with_suffix(".css")
    if css and not css_fn.exists():
        css_fn.write_text(css)
    print(f"{out}: {len(cards)} cards ({added} new)" + (f", style {st.style.name}" if st.style else ""))


if __name__ == "__main__":
    sys.exit(main())

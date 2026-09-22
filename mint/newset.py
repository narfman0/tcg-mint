"""Start a set file from a plain decklist.

    mint newset --code SAT --name "Satoru, ..." [--style neon] [--out sets/satoru.json] decklist.txt

The decklist is `<count> <Card Name>` per line, mainboard first, then a blank
line and the commander(s); anything from the first `#` header on is ignored
(that is where Moxfield exports put sideboard/maybeboard sections). The
commander becomes card 1 and the rest follow in list order. An existing set
file is updated in place: new cards are appended, numbers and per-card edits
(flavor, subject, art) are kept.

--style seeds the set's `style` block from a template in styles/ (see
style.py) or one of the built-in recipes (`neon`, `ink`, `glass`); edit it
afterwards, it is just JSON. A template's .css becomes the set's .css.
"""
import argparse
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
    return parse_decklist(open(path).read())


def parse_decklist(text, plain=False):
    """The card names in a decklist's text, commanders first (the module docstring says the
    shape). Lines without a count are skipped; with `plain` they count as one copy each,
    so the workbench takes a bare list of names too."""
    main, commanders = [], []
    section = main
    for line in text.splitlines():
        if line.startswith("#"):
            break
        if not line.strip():
            section = commanders
            continue
        m = re.match(r"(\d+)x?\s+(.+)", line.strip())
        if m:
            section.append(m.group(2).strip())
        elif plain:
            section.append(line.strip())
    if not commanders:  # no blank line: whole list is the deck
        return main
    return commanders + main


def dedupe(names):
    """The names in order, each once (basic lands repeat in a decklist)."""
    seen = set()
    return [n for n in names if not (n in seen or seen.add(n))]


def create(ws, code, name, names, style_name=None, out=None):
    """Make or update a set file: new cards are appended after the existing ones with the
    next numbers; per-card edits and an existing style block are kept. A style template
    seeds the style block (and its .css) only when the set has none. Returns (path, set, added)."""
    out = Path(out or ws.sets / (code.lower() + ".json"))
    st = sets.load(out) if out.exists() else sets.SetFile(code=code, name=name)
    st.code, st.name = code, name
    css = None
    if style_name and st.style is None:
        t = style.read(ws, style_name)
        st.style, css, st.frame = t["style"], t["css"], t["frame"]
    added = add_cards(st, names)
    sets.save(out, st)
    css_fn = out.with_suffix(".css")
    if css and not css_fn.exists():
        css_fn.write_text(css)
    st.css = css_fn.read_text() if css_fn.exists() else ""
    return out, st, added


def add_cards(st, names):
    """Append the names a set does not have yet, numbered after its highest; returns how many."""
    nxt = max((c.number or 0 for c in st.cards.values()), default=0) + 1
    added = 0
    for n in dedupe(names):
        if n not in st.cards:
            st.cards[n] = sets.CardEntry(number=nxt)
            nxt += 1
            added += 1
    st.size = len(st.cards)
    return added


def main(argv=None):
    ap = argparse.ArgumentParser(prog="mint newset", description=__doc__.split("\n\n")[0])
    ap.add_argument("decklist")
    ap.add_argument("--code", required=True, help="set code, e.g. SAT (the company code is added by the renderer)")
    ap.add_argument("--name", required=True)
    ap.add_argument("--style", help="seed the style block from a template in styles/ or a built-in recipe")
    ap.add_argument("--out", help="set file (default sets/<code lowercased>.json)")
    a = ap.parse_args(argv)
    try:
        out, st, added = create(workspace.default(), a.code, a.name, read_decklist(a.decklist),
                                style_name=a.style, out=a.out)
    except MintError as e:
        raise SystemExit(str(e)) from None
    print(f"{out}: {len(st.cards)} cards ({added} new)" + (f", style {st.style.name}" if st.style else ""))


if __name__ == "__main__":
    sys.exit(main())

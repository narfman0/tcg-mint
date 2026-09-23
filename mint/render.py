"""Render cards from Scryfall data into the M15-style frame, at print resolution.

    mint render [--set sets/bls1.json] [--styled] [--theme NAME | --compare]
                [--dpi 1200] [--out DIR] ["Card Name" ...]

A set file (JSON, see sets.py) carries the set code, size, an optional
art_filter (the set's "flair", a CSS filter applied when --styled is given)
and per-card overrides. With --set and no card names, the whole set is
rendered. Output is 2.72x3.72in with bleed, which is both MPC's template and
what an imposer wants.

The work is done by `render_cards()`, which any caller can use; `main` is
the command-line face of it.
"""
import argparse
import datetime as dt
import hashlib
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from . import frame, sets, workspace
from .art import Art, ArtSource
from .browser import Browser
from .cards import Cards, faces
from .cards import warnings as card_warnings
from .errors import MintError
from .manifest import Manifest, frame_hash


@dataclass
class Rendered:
    """What `render_cards` produced for one card in one theme."""
    name: str
    number: int
    theme: str
    out: str
    source: ArtSource
    sizes: dict | None = None
    art_filter: str | None = None
    warnings: list = field(default_factory=list)
    design: str | None = None   # the frame design it was rendered in, for the card page to tell two apart
    back: bool = False          # a double-faced card's back face, filed under the front's number

    @property
    def shrunk(self):
        return bool(self.sizes) and self.sizes["text"] < frame.TEXT_FLOOR


def slug(name):
    return re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_")


def stamp(base, out_dir, html, browser):
    """Render `html` into out_dir under `base`, named by what came out: the PNG's own eight-hex
    digest ends the file name. Two renders of the same card that differ -- another design, other
    knobs, newer art -- are two files side by side, the way two takes of the art are; rendering the
    same thing twice writes the same name again and stays one. Returns (path, sizes)."""
    part = os.path.join(out_dir, f".{base}.part.png")
    try:
        sizes = browser.render(html, part)
        rid = hashlib.sha1(Path(part).read_bytes()).hexdigest()[:8]
        out = os.path.join(out_dir, f"{base}-{rid}.png")
        os.replace(part, out)
    finally:  # a render that died half way leaves nothing behind for gc to call an orphan
        if os.path.exists(part):
            os.unlink(part)
    return out, sizes


def render_cards(ws, names, *, set_path=None, styled=False, themes=("wizards",), dpi=1200, out_dir=".",
                 compare=False, year=None, on_rendered=None, back_faces=False, design=None):
    """Render `names` (or the whole set when empty) into out_dir. Returns a list of
    Rendered; `on_rendered` is called with each one as it finishes. With back_faces,
    a double-faced card's back is rendered too, as its own card numbered "<n>b".
    `design` overrides the set's, for rendering the same card in one frame after another
    (`mint calibrate --design`)."""
    st = sets.load(set_path) if set_path else sets.SetFile(code=ws.maker_code + "1")
    if design:
        st.design = design
    names = list(names) or st.names()
    if not names:
        raise MintError("give card names or a --set with cards")
    year = year or dt.date.today().strftime("%Y")
    fhash = frame_hash(st.css, frame.frame_css(st.frame))

    cards = Cards(ws.cards_file)
    art = Art(ws.art)
    symbols, expansions = frame.Symbols(ws.symbols), frame.Sets(ws.symbols)
    fonts_css = frame.local_fonts(ws.fonts)
    os.makedirs(out_dir, exist_ok=True)
    manifest = Manifest(out_dir)
    results = []
    with Browser(dpi) as browser:
        for i, name in enumerate(names, 1):
            found = cards.find(name, *st.lookup(name))
            fs = faces(found)
            for card in (fs if back_faces else fs[:1]):
                other = fs[1 - card["face_index"]] if len(fs) == 2 else None  # a double-faced card's other side
                for r in render_one(ws, browser, st, card, i, styled, themes, out_dir, compare, year, fhash,
                                    symbols, expansions, art, fonts_css, manifest, dpi, set_path, other):
                    results.append(r)
                    if on_rendered:
                        on_rendered(r)
    return results


def render_one(ws, browser, st, card, i, styled, themes, out_dir, compare, year, fhash, symbols, expansions, art, fonts_css,
       manifest, dpi, set_path, other_face=None):
    """Render one face of one card in each theme, yielding a Rendered per file."""
    set_code = st.code
    back = card.get("face_index", 0) > 0  # a back face gets the front's number plus "b" and never its art override
    entry = st.card(card)
    number = entry.number or i
    style_hash = st.styled_hash(card, art=art) if styled else None
    design = st.design_of(card)  # the frame it renders in, and so which picture its art comes from
    source = art.resolve(card, override=entry.art if not back else None, style_hash=style_hash, design=design)
    # a restyled image wins; the CSS filter is the fallback for --styled
    art_filter = None
    if styled and source.kind != "styled":
        art_filter = entry.art_filter or st.art_filter
    for th in themes:
        tag = f".{th}" if compare else ""
        prefix = f"{set_code}-" if set_path else ""
        num = f"{number:03d}" + ("b" if back else "")
        base = f"{prefix}{num}_{slug(card['name'])}{'.styled' if styled else ''}{tag}"
        html = frame.build_html(
            card, symbols=symbols, art_url=source.url, theme=th, fonts_css=fonts_css,
            set_size=expansions.size(card["set"]), set_icon=expansions.icon(card["set"]), flavor=entry.flavor,
            art_filter=art_filter, set_css=st.css, frame_vars=frame.frame_css(st.frame),
            maker=ws.maker, year=year, other_face=other_face, design=design)
        out, sizes = stamp(base, out_dir, html, browser)
        r = Rendered(card["name"], number, th, out, source, sizes, art_filter, card_warnings(card), design, back)
        manifest.add(r, set_code=set_code if set_path else None, styled=styled, fhash=fhash, dpi=dpi)
        manifest.save()
        yield r



def contact_sheet(results, themes, out_dir):
    from PIL import Image
    ims = [Image.open(r.out) for r in results]
    w, h = ims[0].size
    s = 4  # downscale for the sheet
    cols, rows = len(themes), len(results) // len(themes)
    sheet = Image.new("RGB", (cols * w // s, rows * h // s), "white")
    for k, im in enumerate(ims):
        sheet.paste(im.resize((w // s, h // s), Image.LANCZOS), ((k % cols) * w // s, (k // cols) * h // s))
    fn = os.path.join(out_dir, "compare.png")
    sheet.save(fn)
    return fn


def main(argv=None):
    ap = argparse.ArgumentParser(prog="mint render", description=__doc__.split("\n\n")[0])
    ap.add_argument("names", nargs="*")
    ap.add_argument("--set", help="set JSON: code, size, art_filter, cards{name: {number, flavor, art, art_filter}}")
    ap.add_argument("--styled", action="store_true", help="use the set's restyled art, or its art_filter as a fallback")
    ap.add_argument("--theme", default="wizards", choices=frame.THEMES)
    ap.add_argument("--compare", action="store_true", help="render every theme into a contact sheet")
    ap.add_argument("--dpi", type=int, default=1200)
    ap.add_argument("--out", default=".", help="directory for the PNGs (default: current directory)")
    ap.add_argument("--faces", action="store_true", help="also render the back face of double-faced cards")
    ap.add_argument("--design", choices=list(frame.DESIGN_CHOICES),
                    help="render every card in this frame design, whatever the set says")
    a = ap.parse_args(argv)
    themes = list(frame.THEMES) if a.compare else [a.theme]

    def report(r):
        for w in r.warnings:
            print(f"warning: {r.name}: {w}", file=sys.stderr)
        note = f"  (rules text shrunk to {r.sizes['text']}px)" if r.shrunk else ""
        print(r.out + note)

    try:
        results = render_cards(workspace.default(), a.names, set_path=a.set, styled=a.styled, themes=themes,
                               dpi=a.dpi, out_dir=a.out, compare=a.compare, on_rendered=report, back_faces=a.faces,
                               design=a.design)
    except MintError as e:
        sys.exit(str(e))
    if a.compare:
        print(contact_sheet(results, themes, a.out))


if __name__ == "__main__":
    main()

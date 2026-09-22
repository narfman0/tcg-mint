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
import os
import re
import sys
from dataclasses import dataclass, field

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

    @property
    def shrunk(self):
        return bool(self.sizes) and self.sizes["text"] < frame.TEXT_FLOOR


def slug(name):
    return re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_")


def render_cards(ws, names, *, set_path=None, styled=False, themes=("wizards",), dpi=1200, out_dir=".",
                 compare=False, year=None, on_rendered=None, back_faces=False):
    """Render `names` (or the whole set when empty) into out_dir. Returns a list of
    Rendered; `on_rendered` is called with each one as it finishes. With back_faces,
    a double-faced card's back is rendered too, as its own card numbered "<n>b"."""
    st = sets.load(set_path) if set_path else sets.SetFile(code=ws.maker_code + "1")
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
    source = art.resolve(card, override=entry.art if not back else None, style_hash=style_hash)
    # a restyled image wins; the CSS filter is the fallback for --styled
    art_filter = None
    if styled and source.kind != "styled":
        art_filter = entry.art_filter or st.art_filter
    for th in themes:
        tag = f".{th}" if compare else ""
        prefix = f"{set_code}-" if set_path else ""
        num = f"{number:03d}" + ("b" if back else "")
        out = os.path.join(out_dir, f"{prefix}{num}_{slug(card['name'])}{'.styled' if styled else ''}{tag}.png")
        html = frame.build_html(
            card, symbols=symbols, art_url=source.url, theme=th, fonts_css=fonts_css,
            set_size=expansions.size(card["set"]), set_icon=expansions.icon(card["set"]), flavor=entry.flavor,
            art_filter=art_filter, set_css=st.css, frame_vars=frame.frame_css(st.frame),
            maker=ws.maker, year=year, other_face=other_face, design=st.design_of(card))
        sizes = browser.render(html, out)
        r = Rendered(card["name"], number, th, out, source, sizes, art_filter, card_warnings(card))
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
    a = ap.parse_args(argv)
    themes = list(frame.THEMES) if a.compare else [a.theme]

    def report(r):
        for w in r.warnings:
            print(f"warning: {r.name}: {w}", file=sys.stderr)
        note = f"  (rules text shrunk to {r.sizes['text']}px)" if r.shrunk else ""
        print(r.out + note)

    try:
        results = render_cards(workspace.default(), a.names, set_path=a.set, styled=a.styled, themes=themes,
                               dpi=a.dpi, out_dir=a.out, compare=a.compare, on_rendered=report, back_faces=a.faces)
    except MintError as e:
        sys.exit(str(e))
    if a.compare:
        print(contact_sheet(results, themes, a.out))


if __name__ == "__main__":
    main()

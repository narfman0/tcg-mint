"""Render a card back.

    mint back [--set sets/slv.json] [--dpi 1200] [--out back.png]

Same page geometry as the fronts (2.72x3.72in with bleed), from back.html.

Without a set that is the common BLS back, which is what every card prints behind it unless its
set says otherwise. A set with a `back` block (sets.Back) gets its own: its wordmark, its two
palettes, and an emblem in the oval -- its expansion symbol, or an SVG of your own.

That is what makes a union order sortable. `mint export` can put several sets in one batch, and
MPC Autofill prints a back per slot, so the sliver deck comes back with slivers on its backs and
the dinosaur deck with dinosaurs -- no marking on the fronts, and no guessing which pile a card
came out of.

Only the two palettes are named. The rings around the oval, the field's inner highlights, the
pinstripe and the glow behind the emblem are derived from them, so a back in cold blue does not
keep the warm brown trim of the one it was copied from.
"""
import argparse
import os
import re
import string
from pathlib import Path

from . import PKG, frame, sets, workspace
from .browser import Browser
from .errors import MintError

# the oval's own box, its middle, and the square a symbol is fitted into there. The square is
# most of the oval's width: a set symbol is drawn to be read at 2mm in a card's footer, so at this
# size it wants to fill its frame the way the mountain does, not float in the middle of it.
OVAL_BOX = (172, 214)
EMBLEM = (18, 39, 136, 136)


# the symbol's lit edge, as a multiple of the thin black edge frame.py draws in the footer: the
# emblem is ~20x that size here, and an edge scaled with it would read as an outline
EDGE = 3


def _rgba(color, alpha):
    """A #rrggbb as an rgba() at this alpha, for a highlight mixed off one of the palettes."""
    r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
    return f"rgba({r},{g},{b},{alpha})"


def symbol_svg(ws, symbol):
    """The emblem's SVG text: a path to one of your own, else a set code whose expansion symbol is
    cached under symbols/sets (fetched if it is not). Raises when neither finds anything, because a
    back that silently fell back to the mountain is a back you would only notice after ordering."""
    p = Path(symbol)
    if p.suffix.lower() == ".svg" or p.is_file():
        if not p.is_file():
            raise MintError(f"no symbol file {symbol}")
        return p.read_text()
    svg = frame.Sets(ws.symbols).icon(symbol.lower())
    if not svg:
        raise MintError(f"no expansion symbol for {symbol!r}: name a set code Scryfall lists, or an .svg of your own")
    return svg


def emblem(ws, back):
    """What goes inside the oval: the set's symbol drawn in the ink, over a glow taken off the
    oval's palette -- or, for a set that names no symbol, the BLS mountain from back.svg, in its
    own colours."""
    if not back.symbol:
        return f'    <svg viewBox="0 0 172 214">\n{(PKG / "back.svg").read_text()}    </svg>'
    x, y, w, h = EMBLEM
    cx, cy = x + w / 2, y + h / 2  # the glow sits behind the symbol, not where the mountain wanted it
    glow = (f'<defs><radialGradient id="glow" cx="50%" cy="50%" r="50%">'
            f'<stop offset="0" stop-color="{back.oval[0]}" stop-opacity=".95"/>'
            f'<stop offset=".45" stop-color="{back.oval[1]}" stop-opacity=".6"/>'
            f'<stop offset="1" stop-color="{back.oval[2]}" stop-opacity="0"/></radialGradient></defs>'
            f'<ellipse cx="{cx:g}" cy="{cy:g}" rx="{w * 0.62:g}" ry="{h * 0.62:g}" fill="url(#glow)"/>')
    box, inner = frame._icon_parts(symbol_svg(ws, back.symbol))
    inner = re.sub(r'\s(?:fill|stroke|stroke-width|paint-order)="[^"]*"', "", inner)  # the icon's own black goes
    inner = re.sub(r"<(path|polygon|rect|circle|ellipse)\b",
                   rf'<\1 fill="{back.ink}" stroke="{back.oval[0]}" '
                   rf'stroke-width="{frame._edge_width(box) * EDGE:g}" paint-order="stroke"', inner)
    return (f'    <svg viewBox="0 0 {OVAL_BOX[0]} {OVAL_BOX[1]}">{glow}'
            f'<svg x="{x}" y="{y}" width="{w}" height="{h}" viewBox="{box}" '
            f'preserveAspectRatio="xMidYMid meet">{inner}</svg></svg>')


def build_html(ws, back=None):
    """The back's page. `back` is a sets.Back (a set's block), or None for the common BLS back."""
    back = back or sets.Back()
    title, _ = frame.THEMES["wizards"]
    return string.Template((PKG / "back.html").read_text()).substitute(
        local_fonts=frame.local_fonts(ws.fonts) + f"\n:root {{ --title-font: {frame.stack(title)}; }}",
        noise=frame.NOISE_URI, word=back.word, sub=back.sub, tag=back.tag, ink=back.ink,
        highlight22=_rgba(back.oval[0], ".22"), highlight35=_rgba(back.oval[0], ".35"),
        shade60=_rgba(back.paper[3], ".6"), emblem=emblem(ws, back),
        dots="\n".join(f'    <i style="background:{c}"></i>' for c in back.dots),
        **{f"paper{i}": c for i, c in enumerate(back.paper)},
        **{f"oval{i}": c for i, c in enumerate(back.oval)})


def render(ws, out, dpi=1200, back=None):
    """Draw one back to `out`. Returns the path."""
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with Browser(dpi) as b:
        b.render(build_html(ws, back), out, fit=False)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(prog="mint back", description=__doc__.split("\n\n")[0])
    ap.add_argument("--set", help="draw this set's own back instead of the common one")
    ap.add_argument("--dpi", type=int, default=1200)
    ap.add_argument("--out", default="back.png")
    a = ap.parse_args(argv)
    try:
        st = sets.load(a.set) if a.set else None
        if a.set and not st.back:
            print(f"{st.code} has no back block: drawing the common back")
        print(render(workspace.default(), a.out, a.dpi, st.back if st else None))
    except MintError as e:
        raise SystemExit(str(e)) from None


if __name__ == "__main__":
    main()

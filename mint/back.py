"""Render the BLS card back.

    mint back [--dpi 1200] [--out back.png]

Same page geometry as the fronts (2.72x3.72in with bleed), from back.html.
"""
import argparse
import os
import string

from . import PKG, frame, workspace
from .browser import Browser


def build_html(ws):
    title, _ = frame.THEMES["wizards"]
    return string.Template((PKG / "back.html").read_text()).substitute(
        local_fonts=frame.local_fonts(ws.fonts) + f"\n:root {{ --title-font: {frame.stack(title)}; }}",
        noise=frame.NOISE_URI)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="mint back", description=__doc__.split("\n\n")[0])
    ap.add_argument("--dpi", type=int, default=1200)
    ap.add_argument("--out", default="back.png")
    a = ap.parse_args(argv)
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    with Browser(a.dpi) as b:
        b.render(build_html(workspace.default()), a.out, fit=False)
    print(a.out)


if __name__ == "__main__":
    main()

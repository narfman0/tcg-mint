"""Render the BLS card back.

    mint back [--dpi 1200] [--out back.png]

Same page geometry as the fronts (2.72x3.72in with bleed), from back.html.
"""
import argparse
import os
import string

from . import PKG, render


def main(argv=None):
    ap = argparse.ArgumentParser(prog="mint back", description=__doc__.split("\n\n")[0])
    ap.add_argument("--dpi", type=int, default=1200)
    ap.add_argument("--out", default="back.png")
    a = ap.parse_args(argv)
    title, _ = render.THEMES["wizards"]
    html = string.Template((PKG / "back.html").read_text()).substitute(
        local_fonts=render.local_fonts() + f"\n:root {{ --title-font: {render.stack(title)}; }}",
        noise="data:image/svg+xml;base64," + render.NOISE)
    from playwright.sync_api import sync_playwright
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    with sync_playwright() as p:
        b, page = render.browser(p, a.dpi)
        render.render(page, html, a.out, fit=False)
        b.close()
    print(a.out)


if __name__ == "__main__":
    main()

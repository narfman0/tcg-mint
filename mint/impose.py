"""Lay rendered cards out on printable pages.

    mint impose [--paper letter|a4] [--bleed 0.04] [--dpi 600] [--out sheet.pdf] card.png ...

Nine cards per page (3x3) at exactly 2.5x3.5in plus `bleed` on every side, so
you cut on the 2.5x3.5 grid and never see a white edge. Cut marks sit in the
page margins, aligned to that grid. The PDF page is the paper size, at 100%,
which is what `mint print` insists on.

Renders are 2.72x3.72in with 0.11in of bleed; the default keeps 0.04in of it
because three rows of full-bleed cards do not fit on Letter. Images are
resampled to --dpi first (600 is past what an inkjet resolves and keeps the
PDF a sensible size); the PDF is produced by Chromium, which embeds PNGs
losslessly at their exact physical size.
"""
import argparse
import os
import shutil
import subprocess
import tempfile

from PIL import Image

from .browser import Browser

PAPER = {"letter": (8.5, 11.0), "a4": (8.27, 11.69)}
CARD = (2.5, 3.5)
RENDER_BLEED = 0.11  # what render.py puts around the card
COLS, ROWS = 3, 3
PAGES_PER_RUN = 3    # pages per Chromium document; parts are joined with pdfunite (poppler)


def prepare(path, bleed, dpi, tmpdir, i):
    """Crop a render down to the requested bleed and resample to dpi."""
    im = Image.open(path)
    ppi = im.width / (CARD[0] + 2 * RENDER_BLEED)  # the render's own pixels per inch
    trim = round((RENDER_BLEED - bleed) * ppi)
    im = im.crop((trim, trim, im.width - trim, im.height - trim))
    w = round((CARD[0] + 2 * bleed) * dpi)
    h = round((CARD[1] + 2 * bleed) * dpi)
    im = im.resize((w, h), Image.LANCZOS)
    out = os.path.join(tmpdir, f"{i:03d}.png")
    im.save(out, compress_level=6)
    return out


def page_html(paths, paper, bleed):
    pw, ph = PAPER[paper]
    cw, ch = CARD[0] + 2 * bleed, CARD[1] + 2 * bleed
    x0 = (pw - COLS * cw) / 2
    y0 = (ph - ROWS * ch) / 2
    if x0 < 0.1 or y0 < 0.1:
        raise SystemExit(f"{COLS}x{ROWS} cards with {bleed}in bleed do not fit on {paper}; lower --bleed")
    parts = [f'<div class="page" style="width:{pw}in;height:{ph}in">']
    for k, p in enumerate(paths):
        c, r = k % COLS, k // COLS
        parts.append(f'<img src="file://{p}" style="left:{x0 + c * cw}in;top:{y0 + r * ch}in;width:{cw}in;height:{ch}in">')
    # cut marks: in the margins, on the 2.5x3.5 grid lines (i.e. inset by the bleed)
    mark = 0.18
    for c in range(COLS + 1):
        for edge in (0, 1):
            x = x0 + c * cw + (bleed if edge == 0 else -bleed)
            if c == 0 and edge == 1 or c == COLS and edge == 0:
                continue
            parts.append(f'<i class="v" style="left:{x}in;top:{y0 - mark - 0.02}in;height:{mark}in"></i>')
            parts.append(f'<i class="v" style="left:{x}in;top:{y0 + ROWS * ch + 0.02}in;height:{mark}in"></i>')
    for r in range(ROWS + 1):
        for edge in (0, 1):
            y = y0 + r * ch + (bleed if edge == 0 else -bleed)
            if r == 0 and edge == 1 or r == ROWS and edge == 0:
                continue
            parts.append(f'<i class="h" style="top:{y}in;left:{x0 - mark - 0.02}in;width:{mark}in"></i>')
            parts.append(f'<i class="h" style="top:{y}in;left:{x0 + COLS * cw + 0.02}in;width:{mark}in"></i>')
    parts.append("</div>")
    return "\n".join(parts)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="mint impose", description=__doc__.split("\n\n")[0])
    ap.add_argument("cards", nargs="+", help="rendered card PNGs, in order")
    ap.add_argument("--paper", default="letter", choices=PAPER)
    ap.add_argument("--bleed", type=float, default=0.04, help="inches of bleed kept around each card (default 0.04)")
    ap.add_argument("--dpi", type=int, default=600, help="resample cards to this before embedding (default 600)")
    ap.add_argument("--out", default="sheet.pdf")
    a = ap.parse_args(argv)
    if a.bleed > RENDER_BLEED:
        ap.error(f"renders only carry {RENDER_BLEED}in of bleed")

    pw, ph = PAPER[a.paper]
    css = ("<!doctype html><meta charset=utf-8><style>"
           f"@page {{ size: {pw}in {ph}in; margin: 0; }}"
           "* { margin: 0; padding: 0; } body { background: #fff; }"
           ".page { position: relative; page-break-after: always; overflow: hidden; }"
           ".page img { position: absolute; display: block; }"
           ".page i { position: absolute; background: #000; }"
           ".page i.v { width: 0.6pt; margin-left: -0.3pt; } .page i.h { height: 0.6pt; margin-top: -0.3pt; }"
           "</style>")
    per_page = COLS * ROWS
    chunk = per_page * PAGES_PER_RUN
    with tempfile.TemporaryDirectory() as tmp, Browser() as b:
        parts = []
        # a few pages per Chromium run: decoded 600 DPI PNGs are ~10 MB each and a
        # whole 90-card set in one document was enough to get the process killed
        for c0 in range(0, len(a.cards), chunk):
            prepared = [prepare(path, a.bleed, a.dpi, tmp, c0 + i) for i, path in enumerate(a.cards[c0:c0 + chunk])]
            pages = [prepared[i:i + per_page] for i in range(0, len(prepared), per_page)]
            fn = os.path.join(tmp, f"sheet{len(parts)}.html")
            open(fn, "w").write(css + "\n".join(page_html(pg, a.paper, a.bleed) for pg in pages))
            part = os.path.join(tmp, f"part{len(parts)}.pdf")
            b.pdf(fn, part, f"{pw}in", f"{ph}in")
            parts.append(part)
            for fp in prepared:
                os.unlink(fp)
        if len(parts) == 1:
            shutil.move(parts[0], a.out)
        else:
            subprocess.run(["pdfunite", *parts, a.out], check=True)
    npages = -(-len(a.cards) // per_page)
    print(f"{a.out}: {npages} page(s), {len(a.cards)} cards, {a.paper} at 100%, {a.bleed}in bleed, {a.dpi} DPI")


if __name__ == "__main__":
    main()

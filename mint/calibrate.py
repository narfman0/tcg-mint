"""Measure where text actually sits on real M15 cards vs. our render.

    mint calibrate [--out DIR] ["Card Name" ...]

For each reference card we take Scryfall's 745x1040 scan (2.98 px per 1/100in)
and our own 1200 DPI render, run the same ink-row estimator on both, and print
cap-top / baseline / box bounds for the title bar, type bar and P/T box in card
units (1/100 in, origin at the card's top-left corner, bleed excluded). The
final table is the mean offset: positive = ours is lower than real.

The estimator finds text rows by their signature -- some ink, but never the
full width; frame fills and box outlines are dark across the whole row -- and
grows outward from the text block to the bar's outline. Same estimator on both
sides, so any bias cancels.
"""
import argparse
import os
import statistics

from PIL import Image

from . import render, workspace
from .art import Art
from .cards import Cards
from .errors import MintError

# non-legendary M15-frame cards with clean bars; a couple with P/T
DEFAULT = ["Cyclonic Rift", "Rhystic Study", "Demonic Tutor", "Consecrated Sphinx", "Blightsteel Colossus"]

# search windows as fractions of card width/height (bleed excluded)
ZONES = {
    "title": ((0.07, 0.55), (0.03, 0.12)),
    "type":  ((0.07, 0.55), (0.545, 0.635)),
    "pt":    ((0.80, 0.95), (0.885, 0.965)),
    "pips":  ((0.60, 0.94), (0.03, 0.12)),
}


def scan(art, card):
    return Image.open(art.scan(card)).convert("L")


def measure(im, ox, oy, ppu, zone, dark=95):
    """ox/oy: pixel origin of the card; ppu: pixels per card unit."""
    (fx0, fx1), (fy0, fy1) = ZONES[zone]
    x0, x1 = int(ox + fx0 * 250 * ppu), int(ox + fx1 * 250 * ppu)
    y0, y1 = int(oy + fy0 * 350 * ppu), int(oy + fy1 * 350 * ppu)
    px = im.load()
    counts, medians = [], []
    for y in range(y0, y1):
        row = [px[x, y] for x in range(x0, x1)]
        counts.append(sum(1 for v in row if v < dark))
        medians.append(statistics.median(row))
    w = x1 - x0
    text = [i for i, c in enumerate(counts) if 0.02 * w < c < 0.6 * w]
    # keep the longest run of text rows (tolerating 1-row gaps between letters' features)
    runs, start, prev = [], None, None
    for i in text + [None]:
        if start is None:
            start = prev = i
        elif i is not None and i - prev <= 2:
            prev = i
        else:
            runs.append((start, prev))
            start = prev = i
    t0, t1 = max(runs, key=lambda r: r[1] - r[0])
    peak = max(counts[t0:t1 + 1])
    body = [i for i in range(t0, t1 + 1) if counts[i] >= 0.30 * peak]
    ref = statistics.median(medians[t0:t1 + 1])
    edge = lambda i: counts[i] > 0.8 * w or medians[i] < ref - 40
    top = t0
    while top - 1 >= 0 and not edge(top - 1):
        top -= 1
    bot = t1
    while bot + 1 < len(counts) and not edge(bot + 1):
        bot += 1
    u = lambda i: (y0 + i - oy) / ppu
    return {"cap_top": u(t0), "baseline": u(body[-1] + 1), "desc": u(t1 + 1), "box_top": u(top), "box_bottom": u(bot + 1)}


def main(argv=None):
    ap = argparse.ArgumentParser(prog="mint calibrate", description=__doc__.split("\n\n")[0])
    ap.add_argument("names", nargs="*", default=DEFAULT)
    ap.add_argument("--out", default=os.path.join("out", "calib"))
    a = ap.parse_args(argv)
    ws = workspace.default()
    try:
        results = render.render_cards(ws, a.names, out_dir=a.out)
    except MintError as e:
        raise SystemExit(str(e)) from None
    cards, art = Cards(ws.cards_file), Art(ws.art)
    deltas = {z: [] for z in ZONES}
    for r in results:
        card = cards.find(r.name)
        real = scan(art, card)
        ours = Image.open(r.out).convert("L")
        ppu_real = real.width / 250            # scan is the bare card
        ppu_ours = ours.width / 272            # ours has 11 units of bleed each side
        print(f"\n{card['name']}  (real scan {real.width}x{real.height}, ours {ours.width}x{ours.height})")
        for z in ZONES:
            if z == "pt" and card.get("power") is None:
                continue
            try:
                r = measure(real, 0, 0, ppu_real, z)
                o = measure(ours, 11 * ppu_ours, 11 * ppu_ours, ppu_ours, z)
            except (ValueError, IndexError) as e:
                print(f"  {z:6} could not measure ({e})")
                continue
            print(f"  {z:6} real cap {r['cap_top']:6.2f} base {r['baseline']:6.2f} box {r['box_top']:6.2f}-{r['box_bottom']:6.2f}"
                  f" | ours cap {o['cap_top']:6.2f} base {o['baseline']:6.2f} box {o['box_top']:6.2f}-{o['box_bottom']:6.2f}")
            rc = (r["cap_top"] + r["baseline"]) / 2 - (r["box_top"] + r["box_bottom"]) / 2
            oc = (o["cap_top"] + o["baseline"]) / 2 - (o["box_top"] + o["box_bottom"]) / 2
            deltas[z].append({"text_in_box": oc - rc, "cap_top": o["cap_top"] - r["cap_top"],
                              "baseline": o["baseline"] - r["baseline"],
                              "cap_height": (o["baseline"] - o["cap_top"]) - (r["baseline"] - r["cap_top"])})
    print("\nmean offsets, ours minus real, in 1/100 in (positive = ours is lower / larger):")
    for z, ds in deltas.items():
        if ds:
            print(f"  {z:6} " + "  ".join(f"{k} {statistics.mean(d[k] for d in ds):+.2f}" for k in ds[0]))


if __name__ == "__main__":
    main()

"""Measure where a frame's pieces actually sit on real cards vs. our render.

    mint calibrate [--out DIR] ["Card Name" ...]           # M15 text placement
    mint calibrate --design retro ["Card Name" ...]        # any design's bands

For each reference card we take Scryfall's 745x1040 scan (2.98 px per 1/100in)
and our own 1200 DPI render, run the same ink-row estimator on both, and print
cap-top / baseline / box bounds for the title bar, type bar and P/T box in card
units (1/100 in, origin at the card's top-left corner, bleed excluded). The
final table is the mean offset: positive = ours is lower than real.

The estimator finds text rows by their signature -- some ink, but never the
full width; frame fills and box outlines are dark across the whole row -- and
grows outward from the text block to the bar's outline. Same estimator on both
sides, so any bias cancels.

`--design NAME` measures a *frame* rather than its text, and works for any
design in frame.DESIGNS. It renders each card in that design, takes the
brightness profile down the middle of both images and across them, and calls
an edge the half-way point between the plateaus either side of a jump -- the
rule the designs' rectangles were measured with in the first place, by one-off
scripts. Every band boundary is printed in card units, ours beside real, with
the offset, and the design's declared art rectangle with them. Reference cards
are looked up as printings whose own frame is that design, so a retro
measurement is taken against a retro printing.
"""
import argparse
import os
import statistics

from PIL import Image

from . import frame, render, workspace
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


# --- measuring a frame, not its text ------------------------------------------------------
def profile(im, box, axis="y"):
    """The mean brightness along one axis inside `box` (x0, y0, x1, y1): each row's average, down
    the card, or each column's, across it. Bands of frame come out as plateaus and their
    boundaries as jumps."""
    x0, y0, x1, y1 = (int(v) for v in box)
    px = im.load()
    if axis == "y":
        return [sum(px[x, y] for x in range(x0, x1)) / (x1 - x0) for y in range(y0, y1)]
    return [sum(px[x, y] for y in range(y0, y1)) / (y1 - y0) for x in range(x0, x1)]


def edges(prof, window=4, min_jump=0.12, min_gap=6):
    """Where the profile steps from one plateau to another, as fractional indices. A jump is scored
    by the difference between the medians `window` samples either side -- steadier than one
    sample's gradient on a scan -- and each is then refined to where the profile crosses half way
    between those two medians."""
    n = len(prof)
    if n < 2 * window + 3:
        return []
    span = max(prof) - min(prof)
    if span <= 0:
        return []

    def lo(i):
        return statistics.median(prof[max(0, i - window):i]) if i else prof[0]

    def hi(i):
        return statistics.median(prof[i:min(n, i + window)])

    out, taken = [], []
    for size, i in sorted(((abs(hi(i) - lo(i)), i) for i in range(window, n - window)), reverse=True):
        if size < min_jump * span:
            break
        if any(abs(i - j) < min_gap for j in taken):
            continue
        taken.append(i)
        mid = (lo(i) + hi(i)) / 2
        at = i
        for k in range(max(1, i - window), min(n, i + window)):  # the crossing, to a fraction of a sample
            if (prof[k - 1] - mid) * (prof[k] - mid) <= 0 and prof[k] != prof[k - 1]:
                at = k - 1 + (mid - prof[k - 1]) / (prof[k] - prof[k - 1])
                break
        out.append(at)
    return sorted(out)


def bands(im, ox, oy, ppu, *, axis="y", lo=0.3, hi=0.7):
    """A card image's band boundaries, in card units from its own top-left corner. `lo`/`hi` bound
    the strip the profile is taken over, across the other axis, so the card's border and its
    rounded corners stay out of it."""
    w, h = 250 * ppu, 350 * ppu
    box = (ox + lo * w, oy, ox + hi * w, oy + h) if axis == "y" else (ox, oy + lo * h, ox + w, oy + hi * h)
    origin = oy if axis == "y" else ox
    start = box[1] if axis == "y" else box[0]
    return [(int(start) + e - origin) / ppu for e in edges(profile(im, box, axis))]


def pair(ours, real, tol=6.0):
    """Match each of our edges to the nearest real one within `tol` card units. Returns
    ([(ours, real or None)], the real ones nothing of ours landed near)."""
    left, out = list(real), []
    for o in ours:
        near = min(left, key=lambda r: abs(r - o), default=None)
        if near is not None and abs(near - o) <= tol:
            left.remove(near)
            out.append((o, near))
        else:
            out.append((o, None))
    return out, left


def calibrate_design(ws, design, names, out_dir, log=print):
    """Render each card in `design` and report its bands against a real printing's scan."""
    if design not in frame.DESIGNS:
        raise MintError(f"design is one of {', '.join(frame.DESIGNS)}, not {design!r}")
    cards, art = Cards(ws.cards_file), Art(ws.art)
    picked = []
    for name in names:
        card = cards.find(name, None, design)
        got = frame.printed_design(card)
        if got != design:
            log(f"  note: {name}: the best printing on file is a {got} frame, not {design}; "
                "`mint cards --kind default_cards` gives the lookup more printings to choose from")
        picked.append(card)
    results = render.render_cards(ws, names, out_dir=out_dir, design=design)
    aw, ah, _ = frame.DESIGNS[design]
    log("")
    log(f"{design}: frame.DESIGNS puts the art at {aw} x {ah} card units ({aw / ah:.4f}:1)")
    deltas = {"y": [], "x": []}
    for r, card in zip(results, picked):
        real = scan(art, card)
        ours = Image.open(r.out).convert("L")
        pr, po = real.width / 250, ours.width / 272   # the scan is the bare card; ours carries bleed
        log("")
        log(f"{card['name']}  ({card['set'].upper()} {card['collector_number']}, "
            f"printed {frame.printed_design(card)})")
        for axis in ("y", "x"):
            mine = bands(ours, 11 * po, 11 * po, po, axis=axis)
            theirs = bands(real, 0, 0, pr, axis=axis)
            matched, missed = pair(mine, theirs)
            log(f"  {'down' if axis == 'y' else 'across'} the card, in 1/100 in:")
            for o, t in matched:
                if t is None:
                    log(f"    {o:7.2f}  ours only")
                else:
                    log(f"    {o:7.2f}  real {t:7.2f}  {o - t:+6.2f}")
                    deltas[axis].append(o - t)
            for t in missed:
                log(f"    {'':7}  real {t:7.2f}  real only")
    log("")
    log("mean offset of the edges that matched, ours minus real, in 1/100 in "
        "(positive = ours sits lower / further right):")
    for axis, ds in deltas.items():
        where = "down" if axis == "y" else "across"
        log(f"  {where:7} {statistics.mean(ds):+.2f} over {len(ds)} edge(s)" if ds
            else f"  {where:7} nothing matched")
    return deltas


def main(argv=None):
    ap = argparse.ArgumentParser(prog="mint calibrate", description=__doc__.split("\n\n")[0])
    ap.add_argument("names", nargs="*", default=DEFAULT)
    ap.add_argument("--out", default=os.path.join("out", "calib"))
    ap.add_argument("--design", choices=list(frame.DESIGNS),
                    help="measure this design's bands against real printings of it, instead of M15 text placement")
    a = ap.parse_args(argv)
    ws = workspace.default()
    if a.design:
        try:
            calibrate_design(ws, a.design, a.names, a.out)
        except MintError as e:
            raise SystemExit(str(e)) from None
        return 0
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

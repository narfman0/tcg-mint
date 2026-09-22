"""Export a set as a folder MPC Autofill can upload.

    mint export --set sets/bls1.json [--styled] [--dpi 800] [--out DIR]
                [--stock "(S30) Standard Smooth"] [--foil] [--back auto|none|FILE]
                [--format png|jpeg] [--absolute] [--no-render] ["Card Name" ...]

The folder holds `images/` -- one file per card, in collector order -- and
`cards.xml`, the order file MPC Autofill's desktop tool reads. Drop the folder
next to the tool and run it there: it uploads the images as they are, with no
Google Drive in the way. The images are plain files, so MakePlayingCards' own
uploader takes them too.

The geometry is MPC Autofill's own. Its desktop tool reads a card's resolution
off the image's height alone -- `img_dpi = 10 * round(height * 300 / 1110)` --
so a card image is 3.70in tall by its arithmetic, and 2.72in wide to match
MakePlayingCards' standard (poker) template: 2.48x3.46in cut out of a
2.72x3.70in bleed rectangle. 800 DPI is where MPC's digital press tops out and
where the tool downscales anything larger, so that is the default here.

A render is 2.72x3.72in, drawn for a 2.5x3.5in cut. The export crops 0.01in of
bleed off the top and bottom -- nothing in the card moves or squashes, and
0.10in of bleed is still there for MPC to cut into.

Cards that have no render yet, whose render has gone stale, or whose render
was made below the export's own resolution -- blowing up a vector frame is the
one thing worth avoiding -- are rendered first, at 1200 DPI: resampling that
down to 800 is a shade crisper than drawing at 800, the way supersampling
always is. `--no-render` exports only what is already there, and says so when
a render is too small for the DPI asked for. A double-faced card
whose back has been rendered (`mint render --faces`) has that back printed
behind it; every other card gets the common card back.
"""
import argparse
import os
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from PIL import Image

from . import back, frame, render, renders, sets, workspace
from .art import Art
from .browser import Browser
from .cards import Cards
from .errors import MintError

# MPC Autofill's card: the cut card inside its bleed rectangle, in inches
MPC_BLEED = (2.72, 3.70)
MPC_CUT = (2.48, 3.46)
MAX_DPI = 800        # where MPC's press tops out, and where the desktop tool downscales to
RENDER_SIZE = (2.72, 3.72)  # what render.py produces
# What a card missing a render is rendered at. Above the export's own resolution on purpose: a card
# drawn at 1200 and resampled down to 800 comes out a shade crisper than one drawn at 800, the way
# supersampling always does (measured: a slightly higher edge gradient, a mean difference under
# 0.5/255 -- and a master that is still right if MPC's press ever goes further).
RENDER_DPI = 1200

# MakePlayingCards' cardstocks, spelled the way the desktop tool's XML wants them
STOCKS = ("(S27) Smooth", "(S30) Standard Smooth", "(S33) Superior Smooth", "(M31) Linen", "(P10) Plastic")
DEFAULT_STOCK = "(S30) Standard Smooth"
# MPC's price brackets for standard-size cards; an order is billed at the next one up
BRACKETS = (18, 36, 55, 72, 90, 108, 126, 144, 162, 180, 198, 216, 234, 396, 504, 612)


def bracket(n):
    """The bracket an order of n cards falls in. Past MPC's largest it is that largest: the order
    has to be split, which the desktop tool says at upload time."""
    return next((b for b in BRACKETS if b >= n), BRACKETS[-1])


def safe(name):
    """A card name as a file name: letters, digits, spaces, apostrophes and dashes survive, the
    rest goes, and Windows will not choke on it."""
    out = re.sub(r"[^A-Za-z0-9 '-]+", " ", name)
    return re.sub(r"\s+", " ", out).strip(" .") or "card"


def mpc_image(src, dest, dpi, fmt="png", quality=95):
    """One render as an MPC card image: cropped to the 2.72x3.70 bleed rectangle about its middle,
    resampled to `dpi`, and stamped with that resolution. Returns (width, height)."""
    with Image.open(src) as im:
        im = im.convert("RGB")
        want = MPC_BLEED[0] / MPC_BLEED[1]
        have = im.width / im.height
        if have > want:                       # too wide: take the middle columns
            w = round(im.height * want)
            box = ((im.width - w) // 2, 0, (im.width - w) // 2 + w, im.height)
        else:                                 # too tall: take the middle rows -- the render's case
            h = round(im.width / want)
            box = (0, (im.height - h) // 2, im.width, (im.height - h) // 2 + h)
        im = im.crop(box)
        size = (round(MPC_BLEED[0] * dpi), round(MPC_BLEED[1] * dpi))
        im = im.resize(size, Image.LANCZOS)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if fmt == "jpeg":
            im.save(dest, "JPEG", quality=quality, subsampling=0, dpi=(dpi, dpi))
        else:
            im.save(dest, "PNG", compress_level=6, dpi=(dpi, dpi))
    return size


def art_headroom(entry, dpi):
    """How hard the art had to be stretched to fill this render's art window at `dpi`: the `cover`
    scale factor, above 1 where the browser had to interpolate up. The window never stretches a
    picture -- `cover` keeps its aspect and crops the excess (`mint check` warns when that crop is
    deep) -- so this is about pixels, not shape. Returns (factor, (want w, h), (have w, h)), or
    None when the art it used cannot be measured."""
    src = (entry.get("source") or {}).get("path")
    design = entry.get("design") or "m15"
    if not src or design not in frame.DESIGNS or not Path(src).is_file():
        return None
    w, h, _ = frame.DESIGNS[design]
    want = (round(w / 100 * dpi), round(h / 100 * dpi))
    try:
        with Image.open(src) as im:
            have = im.size
    except (OSError, ValueError):
        return None
    if not have[0] or not have[1]:
        return None
    return max(want[0] / have[0], want[1] / have[1]), want, have


SOFT = 1.05  # below this the art covers the window; above it the browser is inventing pixels


def under_dpi(entry, dpi):
    """True when this render was made below the export's resolution. Its art may be fine, but the
    card itself -- the vector frame, the text, the rules -- would have to be blown up to reach the
    export, which is the one thing a vector frame should never need."""
    made = entry.get("dpi")
    return bool(made) and made < dpi


def order_xml(fronts, backs, cardback, *, stock=DEFAULT_STOCK, foil=False):
    """The order file. `fronts` and `backs` are [(slot, relative path, card name)]; slots are
    0-based and a card with no back of its own falls through to `cardback`."""
    order = ET.Element("order")
    details = ET.SubElement(order, "details")
    ET.SubElement(details, "quantity").text = str(len(fronts))
    ET.SubElement(details, "bracket").text = str(bracket(len(fronts)))
    ET.SubElement(details, "stock").text = stock
    ET.SubElement(details, "foil").text = "true" if foil else "false"
    for tag, group in (("fronts", fronts), ("backs", backs)):
        if tag == "backs" and not group:
            continue
        parent = ET.SubElement(order, tag)
        for slot, path, name in group:
            card = ET.SubElement(parent, "card")
            ET.SubElement(card, "id").text = path
            ET.SubElement(card, "sourceType").text = "Local File"
            ET.SubElement(card, "slots").text = str(slot)
            ET.SubElement(card, "name").text = os.path.basename(path)
            ET.SubElement(card, "query").text = name.lower()
    if cardback:
        ET.SubElement(order, "cardback").text = cardback
    ET.indent(order, "  ")
    return ET.tostring(order, encoding="unicode") + "\n"


README = """\
{code} -- {n} card(s) for MPC Autofill
{rule}

images/     one file per card, {w}x{h} px: {bw}x{bh}in at {dpi} DPI, which is
            MakePlayingCards' standard-size card ({cw}x{ch}in) inside its bleed.
cards.xml   the order: which image goes in which slot, on {stock}{foilnote}.

To order:

  1. Put MPC Autofill's desktop tool (autofill.exe / autofill) in this folder.
  2. Run it here. It finds cards.xml, uploads the images from images/ as they
     are -- they are local files, so nothing is fetched from Google Drive --
     and fills in a MakePlayingCards project for you.

The paths in cards.xml are relative to this folder, so the folder can be moved
or zipped; run the tool from inside it. `mint export --absolute` writes full
paths instead, for running the tool from somewhere else.

The images are ordinary files at MPC's size, so MakePlayingCards' own uploader
takes them too: upload images/ and the names sort into collector order.
"""


def export(ws, st, names, out_dir, *, styled=False, dpi=MAX_DPI, stock=DEFAULT_STOCK, foil=False,
           card_back="auto", fmt="png", quality=95, absolute=False, render_missing=True, log=print):
    """Write the MPC Autofill folder. Returns {"dir", "images", "xml", "rendered", "size"}."""
    if dpi > MAX_DPI:
        raise MintError(f"{dpi} DPI is past MPC's {MAX_DPI}; the desktop tool would downscale it anyway")
    if stock not in STOCKS:
        raise MintError(f"stock is one of {', '.join(STOCKS)}")
    if fmt not in ("png", "jpeg"):
        raise MintError("format is png or jpeg")
    mode = "styled" if styled else "plain"
    out_dir = Path(out_dir)
    render_dir = ws.home / "out" / st.code.lower()
    cards, art = Cards(ws.cards_file), Art(ws.art)

    made = []
    if render_missing:
        need = set(renders.needing(render_dir, st, cards, art, names, mode=mode))
        for name in names:  # and a render below this export's resolution, which would be blown up
            if name in need:
                continue
            try:
                _, pick, _ = renders.state(render_dir, st, cards, art, name, mode=mode)
            except MintError:
                continue
            if pick and not pick.get("pinned") and under_dpi(pick, dpi):
                need.add(name)
        need = [n for n in names if n in need]  # back into the set's order
        if need:
            log(f"rendering {len(need)} card(s) whose {mode} render is missing, stale or below {dpi} DPI")
            render.render_cards(ws, need, set_path=st.path, styled=styled, dpi=RENDER_DPI, out_dir=str(render_dir),
                                back_faces=True, on_rendered=lambda r: log(f"  {os.path.basename(r.out)}"))
            made = need

    fronts, backs, slot, soft = [], [], 0, []
    for name in names:
        entry = st.card({"name": name})
        every, pick, why = renders.state(render_dir, st, cards, art, name, mode=mode)
        if not pick:
            raise MintError(f"{name}: no {mode} render to export; drop --no-render, or render it first")
        if why:
            log(f"warning: {name}: exporting a stale render ({why})")
        number = pick.get("number") or entry.number or slot + 1
        rel = f"images/{number:03d} {safe(name)}.{fmt if fmt == 'png' else 'jpg'}"
        if under_dpi(pick, dpi):
            log(f"warning: {name}: its render was made at {pick['dpi']} DPI and this export is {dpi} -- "
                f"the card itself, frame and text, is being blown up. Re-render it, or drop --no-render")
        mpc_image(Path(pick["path"]), out_dir / rel, dpi, fmt, quality)
        fronts.append((slot, str(out_dir / rel) if absolute else rel, name))
        head = art_headroom(pick, dpi)
        if head and head[0] > SOFT:
            f, want, have = head
            soft.append(name)
            log(f"warning: {name}: its art is {have[0]}x{have[1]} and the {pick.get('design') or 'm15'} window "
                f"wants {want[0]}x{want[1]} at {dpi} DPI -- {f:.1f}x up. `mint upscale` (or enhance on the "
                f"card page) gives it the pixels")
        log(f"slot {slot}: {rel}")
        bs = renders.backs_of(render_dir, number, styled)
        if bs:
            brel = f"images/{number:03d}b {safe(bs[0]['card'])}.{fmt if fmt == 'png' else 'jpg'}"
            mpc_image(Path(bs[0]["path"]), out_dir / brel, dpi, fmt, quality)
            backs.append((slot, str(out_dir / brel) if absolute else brel, bs[0]["card"]))
        slot += 1

    cardback = None
    if card_back and card_back != "none":
        rel = f"images/back.{fmt if fmt == 'png' else 'jpg'}"
        if card_back == "auto":
            tmp = out_dir / "images" / ".back.part.png"
            tmp.parent.mkdir(parents=True, exist_ok=True)
            try:
                with Browser(600) as b:
                    b.render(back.build_html(ws), tmp, fit=False)
                mpc_image(tmp, out_dir / rel, dpi, fmt, quality)
            finally:
                if tmp.exists():
                    tmp.unlink()
        else:
            if not Path(card_back).is_file():
                raise MintError(f"no card back at {card_back}")
            mpc_image(Path(card_back), out_dir / rel, dpi, fmt, quality)
        cardback = str(out_dir / rel) if absolute else rel

    xml = out_dir / "cards.xml"
    xml.write_text(order_xml(fronts, backs, cardback, stock=stock, foil=foil))
    size = (round(MPC_BLEED[0] * dpi), round(MPC_BLEED[1] * dpi))
    head = f"{st.code} -- {len(fronts)} card(s) for MPC Autofill"
    (out_dir / "README.txt").write_text(README.format(
        code=st.code, n=len(fronts), rule="=" * len(head), w=size[0], h=size[1], dpi=dpi,
        bw=MPC_BLEED[0], bh=MPC_BLEED[1], cw=MPC_CUT[0], ch=MPC_CUT[1], stock=stock,
        foilnote=", holographic front" if foil else ""))
    log(f"{out_dir}: {len(fronts)} front(s), {len(backs)} own back(s), {size[0]}x{size[1]} px at {dpi} DPI, "
        f"bracket {bracket(len(fronts))}")
    if soft:
        log(f"{len(soft)} card(s) whose art does not fill the window at {dpi} DPI: {', '.join(soft[:8])}"
            + (f" and {len(soft) - 8} more" if len(soft) > 8 else ""))
    return {"dir": str(out_dir), "images": len(fronts) + len(backs) + (1 if cardback else 0),
            "xml": str(xml), "rendered": made, "size": size, "fronts": len(fronts), "backs": len(backs),
            "soft": soft}


def main(argv=None):
    ap = argparse.ArgumentParser(prog="mint export", description=__doc__.split("\n\n")[0])
    ap.add_argument("names", nargs="*", help="cards to export (default: the whole set, in order)")
    ap.add_argument("--set", required=True, help="the set file")
    ap.add_argument("--styled", action="store_true", help="export each card's styled render")
    ap.add_argument("--dpi", type=int, default=MAX_DPI, help=f"card image resolution (default {MAX_DPI}, MPC's max)")
    ap.add_argument("--out", help="the folder to write (default: out/<code>/mpc/)")
    ap.add_argument("--stock", default=DEFAULT_STOCK, choices=STOCKS, help="MakePlayingCards cardstock")
    ap.add_argument("--foil", action="store_true", help="order holographic fronts")
    ap.add_argument("--back", default="auto", help="the common card back: auto (mint back), none, or an image")
    ap.add_argument("--format", default="png", choices=("png", "jpeg"), dest="fmt")
    ap.add_argument("--quality", type=int, default=95, help="JPEG quality (default 95)")
    ap.add_argument("--absolute", action="store_true", help="full paths in cards.xml instead of relative ones")
    ap.add_argument("--no-render", action="store_true", help="export only the renders already on disk")
    a = ap.parse_args(argv)
    ws = workspace.default()
    try:
        st = sets.load(a.set)
        names = list(a.names) or st.names()
        out = a.out or ws.home / "out" / st.code.lower() / "mpc"
        export(ws, st, names, out, styled=a.styled, dpi=a.dpi, stock=a.stock, foil=a.foil, card_back=a.back,
               fmt=a.fmt, quality=a.quality, absolute=a.absolute, render_missing=not a.no_render)
    except MintError as e:
        sys.exit(str(e))


if __name__ == "__main__":
    main()

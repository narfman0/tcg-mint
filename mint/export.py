"""Export one or more sets as a folder MPC Autofill can upload.

    mint export --set sets/bls1.json [--set sets/gsh.json ...]
                [--styled] [--dpi 800] [--out DIR]
                [--stock "(S33) Superior Smooth"] [--foil] [--back auto|none|FILE]
                [--foil-profile holo|flat] [--foil-strength 1]
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
behind it; every other card gets its set's back, or the common one.

Several `--set` make a *union order*: one batch, one bracket, one upload, with
each set's cards printing that set's own back (its `back` block, drawn by
back.py). That is how three decks come back sortable -- slivers on the sliver
deck's backs, dinosaurs on the dinosaur deck's -- with nothing on the fronts to
say which deck a card belongs to. Nothing has to be ticked at MakePlayingCards:
more than one distinct image under <backs> is exactly what the desktop tool
branches on to put the project into its different-backs mode.

The cost of that is honest and worth knowing before ordering. A card two decks
both play is two slots and prints twice, because its two copies want different
backs -- so a union costs the sum of its parts, not the size of their union,
and the bracket is read off that sum. Three decks that shared one copy of every
staple were never three playable decks.

A union's images are named with their set's code, since every set numbers its
cards from 001 and they would otherwise overwrite each other. A single-set
export is untouched: same names, same common back, same everything.

`--foil` orders holographic fronts -- cards.xml's <foil> tag, which is the only
thing about the order MakePlayingCards needs told. Nothing about the geometry
changes: the images, their size, their bleed and their DPI are what they were.
What does change is the file's tone, because MPC's holo is a rainbow layer under
the CMYK with no white ink over it: the file is read as a transmittance against a
mirror instead of a reflectance against paper, so an untreated card comes back
dark and flat. `--foil` therefore also runs every image -- the fronts, any own
backs, and the common back, which is on the same stock -- through mint.foil's
`holo` profile. `--foil-profile flat` orders the foil and treats nothing, and
`--foil-strength` scales the treatment: calibrate it with `mint foil --calibrate`
against foil in your own tray before spending an order on a guess.
"""
import argparse
import os
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from PIL import Image

from . import back, frame, orders, render, renders, sets, workspace
from . import foil as foil_mod
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
DEFAULT_STOCK = "(S33) Superior Smooth"
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


def mpc_image(src, dest, dpi, fmt="png", quality=95, foil_profile=None, foil_strength=1.0):
    """One render as an MPC card image: cropped to the 2.72x3.70 bleed rectangle about its middle,
    resampled to `dpi`, and stamped with that resolution. Returns (width, height).

    `foil_profile` (a mint.foil profile or its name) treats the image for a mirror substrate. It runs
    last, after the resample, so the curve's held blacks are measured on the pixels that get printed
    rather than on ones LANCZOS is about to move."""
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
        if foil_profile:
            im = foil_mod.prep(im, foil_profile, foil_strength)
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


def group_slots(items):
    """[(slot, path, name)] as [(slots, path, name)], one entry per image in first-slot order. The
    desktop tool reads <slots> as a comma-separated set, so an image many slots share -- a set's
    card back, behind every card of that set -- is named and uploaded once instead of per card."""
    out = {}
    for slot, path, name in items:
        out.setdefault(path, (path, name, []))[2].append(slot)
    return sorted(((sorted(s), p, n) for p, n, s in out.values()), key=lambda g: g[0][0])


def order_xml(fronts, backs, cardback, *, stock=DEFAULT_STOCK, foil=False):
    """The order file. `fronts` and `backs` are [(slot, relative path, card name)]; slots are
    0-based and a card with no back of its own falls through to `cardback`.

    More than one distinct image under <backs> is what puts the MakePlayingCards project into
    its different-backs mode -- the desktop tool branches on exactly that -- so a union order's
    per-set backs need no other flag."""
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
        for slots, path, name in group_slots(group):
            card = ET.SubElement(parent, "card")
            ET.SubElement(card, "id").text = path
            ET.SubElement(card, "sourceType").text = "Local File"
            ET.SubElement(card, "slots").text = ",".join(str(x) for x in slots)
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
{backpara}{foilpara}

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


def _stale(ws, st, names, render_dir, cards, art, mode, dpi, log):
    """The cards of this set whose render is missing, stale, or below the export's own resolution
    -- blowing up a vector frame is the one thing worth avoiding -- in the set's own order."""
    need = set(renders.needing(render_dir, st, cards, art, names, mode=mode))
    for name in names:
        if name in need:
            continue
        try:
            _, pick, _ = renders.state(render_dir, st, cards, art, name, mode=mode)
        except MintError:
            continue
        if pick and not pick.get("pinned") and under_dpi(pick, dpi):
            need.add(name)
    return [n for n in names if n in need]


def _card_back(ws, out_dir, rel, browser, block, *, dpi, fmt, quality, prep, foil_strength):
    """Draw one card back into the folder at `rel`. `block` is a set's sets.Back, or None for the
    common one. The back is on the same stock as the fronts, so a foil order treats it too."""
    tmp = out_dir / "images" / ".back.part.png"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    try:
        browser.render(back.build_html(ws, block), tmp, fit=False)
        mpc_image(tmp, out_dir / rel, dpi, fmt, quality, prep, foil_strength)
    finally:
        if tmp.exists():
            tmp.unlink()


def _backpara(parts, ext):
    """The paragraph a union order's README carries: which back each set prints, and how many
    cards it is behind, so the folder says what the order is before it is uploaded."""
    rows = "".join(f"  {st.code:<5} {'back ' + st.code + '.' + ext if st.back else 'the common back':<18}"
                   f"{len(names)} card(s)\n" for st, names in parts)
    return ("\nThe sets in this order print different backs, one per set, so the decks can be told\n"
            "apart afterwards without anything on the fronts to say which is which:\n\n" + rows +
            "\nThe desktop tool sees more than one back in cards.xml and puts the MakePlayingCards\n"
            "project into its different-backs mode itself; there is nothing to tick. A card two\n"
            "decks both play is in here twice, once behind each back.\n")


def export(ws, st, names, out_dir, **kw):
    """One set's MPC Autofill folder: `export_union` with a single part."""
    return export_union(ws, [(st, names)], out_dir, **kw)


def export_union(ws, parts, out_dir, *, styled=False, dpi=MAX_DPI, stock=DEFAULT_STOCK, foil=False,
                 foil_profile=None, foil_strength=1.0, card_back="auto", fmt="png", quality=95,
                 absolute=False, render_missing=True, log=print):
    """Write the MPC Autofill folder. `parts` is [(SetFile, [card name])]: each set's cards take
    slots in the order named, and the sets in the order given. Returns {"dir", "images", "xml",
    "rendered", "size", "fronts", "backs", "soft", "sets"}.

    More than one part is a *union order*: one batch at one bracket, with each set's own card back
    (its `back` block, drawn by back.py) printed behind its own cards. That is what makes the decks
    sortable afterwards -- the sliver deck comes back with slivers on its backs -- with nothing on
    the fronts to say which deck a card came out of. Naming several sets is the whole of it: more
    than one distinct image under <backs> is what puts the MakePlayingCards project into its
    different-backs mode, and the desktop tool does that itself.

    A set with no back block falls through to the common back, as every card in a single-set
    export does; nothing about that case changes, file names included. A card two decks both play
    is two slots and prints twice -- distinct backs mean a copy per deck, which a playable deck
    needed anyway -- so a union costs the sum of its parts, not the size of their union.

    `foil` sets cards.xml's <foil> and, unless `foil_profile` says otherwise, treats every image for
    the holo substrate. The profile is only consulted when `foil` is on: a treated file printed on
    ordinary stock would just be a washed-out card."""
    if dpi > MAX_DPI:
        raise MintError(f"{dpi} DPI is past MPC's {MAX_DPI}; the desktop tool would downscale it anyway")
    if stock not in STOCKS:
        raise MintError(f"stock is one of {', '.join(STOCKS)}")
    if fmt not in ("png", "jpeg"):
        raise MintError("format is png or jpeg")
    parts = [(st, list(names)) for st, names in parts]
    if not parts:
        raise MintError("nothing to export: name at least one set")
    codes = [st.code for st, _ in parts]
    if len(set(codes)) != len(codes):
        raise MintError(f"the same set is in the order twice: {', '.join(sorted(codes))}")
    union = len(parts) > 1
    # the profile is the order's, not the image's: no foil, no treatment
    prep = foil_mod.profile(foil_profile or foil_mod.DEFAULT_PROFILE) if foil else None
    mode = "styled" if styled else "plain"
    out_dir = Path(out_dir)
    ext = fmt if fmt == "png" else "jpg"
    cards, art = Cards(ws.cards_file), Art(ws.art)

    made = []
    if render_missing:
        for st, names in parts:
            need = _stale(ws, st, list(dict.fromkeys(names)), ws.home / "out" / st.code.lower(),
                          cards, art, mode, dpi, log)
            if need:
                log(f"rendering {len(need)} {st.code} card(s) whose {mode} render is missing, stale or below {dpi} DPI")
                render.render_cards(ws, need, set_path=st.path, styled=styled, dpi=RENDER_DPI,
                                    out_dir=str(ws.home / "out" / st.code.lower()), back_faces=True,
                                    on_rendered=lambda r: log(f"  {os.path.basename(r.out)}"))
                made += need

    fronts, backs, slot, soft = [], [], 0, []
    mine = {st.code: [] for st, _ in parts}   # the slots each set took, for its own back
    faced = set()                             # slots a double-faced card already has a back for
    written = set()                           # images already on disk this run, for cards printed more than once
    for st, names in parts:
        render_dir = ws.home / "out" / st.code.lower()
        stem = f"{st.code} " if union else ""  # each set numbers from 001, so a union needs its code to sort by
        for name in names:
            entry = st.card({"name": name})
            every, pick, why = renders.state(render_dir, st, cards, art, name, mode=mode)
            if not pick:
                raise MintError(f"{name}: no {mode} render to export; drop --no-render, or render it first")
            if why:
                log(f"warning: {name}: exporting a stale render ({why})")
            number = pick.get("number") or entry.number or slot + 1
            rel = f"images/{stem}{number:03d} {safe(name)}.{ext}"
            if under_dpi(pick, dpi):
                log(f"warning: {name}: its render was made at {pick['dpi']} DPI and this export is {dpi} -- "
                    f"the card itself, frame and text, is being blown up. Re-render it, or drop --no-render")
            if rel not in written:   # a second copy of the same card is another slot, not another file
                mpc_image(Path(pick["path"]), out_dir / rel, dpi, fmt, quality, prep, foil_strength)
                written.add(rel)
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
            if bs:  # a double-faced card's own back, which beats the set's
                brel = f"images/{stem}{number:03d}b {safe(bs[0]['card'])}.{ext}"
                if brel not in written:
                    mpc_image(Path(bs[0]["path"]), out_dir / brel, dpi, fmt, quality, prep, foil_strength)
                    written.add(brel)
                backs.append((slot, str(out_dir / brel) if absolute else brel, bs[0]["card"]))
                faced.add(slot)
            mine[st.code].append(slot)
            slot += 1

    # the backs the order draws: each set's own behind its own slots, and the common one behind
    # every slot left over -- a set with no block, and every card in a single-set export
    with_back = [st for st, _ in parts if st.back]
    cardback = None
    if (card_back and card_back != "none") or with_back:
        with Browser(600) as b:
            for st in with_back:
                rel = f"images/back {st.code}.{ext}"
                _card_back(ws, out_dir, rel, b, st.back, dpi=dpi, fmt=fmt, quality=quality,
                           prep=prep, foil_strength=foil_strength)
                path = str(out_dir / rel) if absolute else rel
                took = [s for s in mine[st.code] if s not in faced]  # a DFC keeps its own back
                backs += [(s, path, f"{st.code} back") for s in took]
                log(f"{st.code}: its own card back behind {len(took)} slot(s), {rel}")
            if card_back and card_back != "none":
                rel = f"images/back.{ext}"
                if card_back == "auto":
                    _card_back(ws, out_dir, rel, b, None, dpi=dpi, fmt=fmt, quality=quality,
                               prep=prep, foil_strength=foil_strength)
                else:
                    if not Path(card_back).is_file():
                        raise MintError(f"no card back at {card_back}")
                    mpc_image(Path(card_back), out_dir / rel, dpi, fmt, quality, prep, foil_strength)
                cardback = str(out_dir / rel) if absolute else rel

    xml = out_dir / "cards.xml"
    xml.write_text(order_xml(fronts, backs, cardback, stock=stock, foil=foil))
    size = (round(MPC_BLEED[0] * dpi), round(MPC_BLEED[1] * dpi))
    code = "+".join(codes)
    head = f"{code} -- {len(fronts)} card(s) for MPC Autofill"
    (out_dir / "README.txt").write_text(README.format(
        code=code, n=len(fronts), rule="=" * len(head), w=size[0], h=size[1], dpi=dpi,
        bw=MPC_BLEED[0], bh=MPC_BLEED[1], cw=MPC_CUT[0], ch=MPC_CUT[1], stock=stock,
        foilnote=", holographic front" if foil else "",
        backpara=_backpara(parts, ext) if union else "",
        foilpara=("\nThese images are treated for foil: their floor is raised and their midtones\n"
                  "lifted, because MPC's holo is a rainbow layer under the CMYK with no white ink\n"
                  "over it, so an untreated file comes back dark. Pure black is held where it is --\n"
                  "the border and the rules text are meant to go matte. They will look washed out on\n"
                  "a monitor. That is the point; judge them on foil, not on screen."
                  if prep else "")))
    log(f"{out_dir}: {len(fronts)} front(s) over {len(codes)} set(s), {len(backs)} slot(s) with a back of "
        f"their own, {size[0]}x{size[1]} px at {dpi} DPI, bracket {bracket(len(fronts))}")
    if foil:
        log(f"holographic: <foil>true</foil>, images treated for {foil_profile or foil_mod.DEFAULT_PROFILE} at "
            f"strength {foil_strength:g}" if prep else "holographic: <foil>true</foil>, images left untreated")
    if soft:
        log(f"{len(soft)} card(s) whose art does not fill the window at {dpi} DPI: {', '.join(soft[:8])}"
            + (f" and {len(soft) - 8} more" if len(soft) > 8 else ""))
    return {"dir": str(out_dir), "images": len(fronts) + len(backs) + (1 if cardback else 0),
            "xml": str(xml), "rendered": made, "size": size, "fronts": len(fronts), "backs": len(backs),
            "soft": soft, "sets": codes}


def main(argv=None):
    ap = argparse.ArgumentParser(prog="mint export", description=__doc__.split("\n\n")[0])
    ap.add_argument("names", nargs="*", help="cards to export (default: the whole set, in order)")
    ap.add_argument("--set", action="append", metavar="FILE", default=[],
                    help="the set file; repeat it to union several sets into one order, each printing its own back")
    ap.add_argument("--order", metavar="NAME",
                    help="an order built with `mint order`: its sets, its counts and its settings")
    ap.add_argument("--styled", action="store_true", help="export each card's styled render")
    ap.add_argument("--dpi", type=int, default=MAX_DPI, help=f"card image resolution (default {MAX_DPI}, MPC's max)")
    ap.add_argument("--out", help="the folder to write (default: out/<code>/mpc/)")
    ap.add_argument("--stock", default=DEFAULT_STOCK, choices=STOCKS, help="MakePlayingCards cardstock")
    ap.add_argument("--foil", action="store_true", help="order holographic fronts, and treat the images for foil")
    ap.add_argument("--foil-profile", default=None, choices=list(foil_mod.PROFILES),
                    help=f"how to treat the images for foil (default {foil_mod.DEFAULT_PROFILE}; `flat` treats nothing)")
    ap.add_argument("--foil-strength", type=float, default=1.0, help="scale the foil treatment (default 1)")
    ap.add_argument("--back", default="auto", help="the common card back: auto (mint back), none, or an image")
    ap.add_argument("--format", default="png", choices=("png", "jpeg"), dest="fmt")
    ap.add_argument("--quality", type=int, default=95, help="JPEG quality (default 95)")
    ap.add_argument("--absolute", action="store_true", help="full paths in cards.xml instead of relative ones")
    ap.add_argument("--no-render", action="store_true", help="export only the renders already on disk")
    a = ap.parse_args(argv)
    ws = workspace.default()
    try:
        if bool(a.order) == bool(a.set):
            sys.exit("name either --set (one or more) or --order, not both")
        if a.order:
            # the order carries its own sets, counts and settings; a flag given here still wins
            o = orders.find(ws, a.order)
            parts = o.parts(orders.loaded_sets(ws, o))
            if not parts:
                sys.exit(f"{o.name}: no set in this order is in the workspace; `mint order show {o.slug}` says which")
            given = {x.dest for x in ap._actions if getattr(a, x.dest, None) != x.default}
            styled = a.styled or (o.mode == "styled" and "styled" not in given)
            dpi = a.dpi if "dpi" in given else (o.dpi or MAX_DPI)
            stock = a.stock if "stock" in given else (o.stock or DEFAULT_STOCK)
            profile = a.foil_profile if "foil_profile" in given else o.foil
            strength = a.foil_strength if "foil_strength" in given else o.foil_strength
            out = a.out or ws.home / "out" / "orders" / o.slug / "mpc"
            export_union(ws, parts, out, styled=styled, dpi=dpi, stock=stock, foil=a.foil or bool(profile),
                         card_back=a.back, foil_profile=profile, foil_strength=strength, fmt=a.fmt,
                         quality=a.quality, absolute=a.absolute, render_missing=not a.no_render)
            return
        loaded = [sets.load(s) for s in a.set]
        if a.names and len(loaded) > 1:
            sys.exit("naming cards picks them out of one set; with several --set the whole of each is ordered")
        parts = [(st, list(a.names) or st.names()) for st in loaded]
        # a union is nobody's set, so it gets its own folder rather than squatting in the first one's
        out = a.out or ws.home / "out" / "-".join(st.code.lower() for st in loaded) / "mpc"
        export_union(ws, parts, out, styled=a.styled, dpi=a.dpi, stock=a.stock, foil=a.foil, card_back=a.back,
                     foil_profile=a.foil_profile, foil_strength=a.foil_strength, fmt=a.fmt, quality=a.quality,
                     absolute=a.absolute, render_missing=not a.no_render)
    except MintError as e:
        sys.exit(str(e))


if __name__ == "__main__":
    main()

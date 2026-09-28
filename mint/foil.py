"""Prepare cards for a mirror substrate -- foil sticker paper here, MakePlayingCards' holo there.

    mint foil --list
    mint foil --proof out/bls1/001.png [--profile holo] [--out proof.png]
    mint foil --prep  out/bls1/001.png [--profile sticker] [--strength 1] [--out prepped.png]
    mint foil --calibrate [--card out/bls1/001.png] [--profile sticker] [--out DIR]

Why a card needs treating at all. Ordinary paper is a diffuse white base: it
throws back most of the light that reaches it, in every direction, so the ink
on top is read against white from wherever you stand. Foil is a mirror with a
rainbow layer under it and no white ink over it, which changes two things at
once:

  * There is no white base. What comes back is the substrate seen *through* the
    ink, so the file's value is a transmittance, not a reflectance. White in the
    file is the foil at full brightness; black in the file is ink thick enough to
    hide the foil, and hides it whatever the foil cost.
  * The reflection is specular. Off its angle the mirror sends the room's light
    somewhere other than your eye, so the whole card reads darker and flatter
    than the same file on paper, and the shadows lose their separation first.

So the treatment is a tone pass, not a colour pass: raise the floor, lift the
midtones, and back the saturation off a little because the ink is now sitting
over a substrate that brings its own colour. Two things are deliberately left
alone. White is not touched -- it is the brightest foil the card can have, and
compressing the top would spend the effect for nothing. And the deepest blacks
are held where they are (`hold`): the border, the art's bevel and the rules
text are the parts that *should* go matte, the way a real foil's text does, and
lifting them to grey is what makes a treated card look washed out instead of
shiny.

A dark picture is the one thing this cannot fix. The lift can only redistribute
what the render already has; a night scene has no light areas to turn into
shine, and the fix for that is the art, not the curve.

`--proof` shows the answer before an order does: the print is ink times
substrate, so multiplying the card by a modelled foil is a fair preview. It
lays out three panels -- the card on paper, the card on foil untreated, and the
card on foil after the prep -- which is the whole argument in one picture.

`--calibrate` writes a sheet to actually print: a step wedge and the frame's own
nine colours, each untreated beside treated, and the card you point it at at a
run of strengths. Print it on the foil in the tray (`mint print -p thick`), look
at it under a lamp, and set `--strength` from what you see. The numbers below are
a starting point, not a measurement -- an inkjet on sticker foil and MPC's press
on holo stock do not share a curve, though they share the physics, so every
design decision the sheet settles carries over to the order even though the
strength does not.
"""
import argparse
import math
import os
import string
import sys
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFont

from . import PKG, frame
from .browser import PAGE, Browser

# impose imports this module to treat a sheet on the way to the printer, so it is imported
# inside the two places that need it rather than at the top, where the cycle would depend on
# which of the two a caller happened to reach first.


@dataclass(frozen=True)
class Profile:
    """A substrate: the tone pass it wants, and enough of its look to proof against.

    lift/gamma/sat/hold drive `prep`; base/rainbow/turns only ever reach `substrate`."""
    lift: float      # the floor black is raised to -- nothing below it can separate on a mirror anyway
    gamma: float     # midtone lift; above 1 brightens, and 1.0 leaves the midtones alone
    taper: float     # how fast the lift fades toward white; 1.0 lifts each pixel by the room it has
    sat: float       # saturation multiplier, under 1 because the substrate adds its own colour
    hold: float      # luminance under this keeps its own value: the border and the text stay matte
    base: float      # how bright the substrate is off its specular angle (proof only)
    rainbow: float   # how saturated the holo sheen is: 0 is a plain mirror (proof only)
    turns: float     # hue cycles across the card's diagonal (proof only)


PROFILES = {
    # MakePlayingCards' holographic foil: a rainbow layer under the CMYK, ordered by cards.xml's
    # <foil> tag. Their press lays less ink than an inkjet, so it wants a shade less lift.
    "holo":    Profile(lift=0.16, gamma=2.10, taper=1.0, sat=0.90, hold=0.12, base=0.56, rainbow=0.34, turns=2.5),
    # foil sticker paper through the ET-8500: ink on a non-absorbent mirror sits heavier and dries
    # glossier than on stock, so it starts stronger. This is the one to calibrate; holo follows it.
    "sticker": Profile(lift=0.20, gamma=2.20, taper=1.0, sat=0.86, hold=0.12, base=0.54, rainbow=0.38, turns=2.5),
    # a plain metallic or mirror sheet: the same tone problem with none of the rainbow
    "silver":  Profile(lift=0.16, gamma=2.10, taper=1.0, sat=0.92, hold=0.12, base=0.58, rainbow=0.0, turns=0.0),
    # the control. `prep` is the identity here, so a calibration sheet can carry the untreated card
    # beside the treated ones and a caller can say "no treatment" without a branch.
    "flat":    Profile(lift=0.0, gamma=1.0, taper=1.0, sat=1.0, hold=0.0, base=0.56, rainbow=0.34, turns=2.5),
}
DEFAULT_PROFILE = "holo"
CAL_STRENGTHS = (0.0, 0.25, 0.5, 0.75, 1.0)  # five cards, which fills an imposed page with the four patch cards


def profile(p):
    """A profile by name, or a Profile through unchanged, or None for no treatment at all."""
    if p is None or isinstance(p, Profile):
        return p
    if p not in PROFILES:
        raise ValueError(f"no foil profile {p!r}; one of {', '.join(PROFILES)}")
    return PROFILES[p]


def _clamp(v, lo=0.0, hi=1.0):
    return lo if v < lo else hi if v > hi else v


def curve(pr, strength=1.0):
    """The tone pass as a 256-entry LUT. White maps to white at every strength -- it is the brightest
    foil the card can have -- and 0 maps to `lift`, scaled by `strength`.

    The lift fades out toward white (`taper`) instead of running straight into it, and that taper is
    the whole difference between a card that survives this pass and one that does not. White is
    clamped, so a curve that keeps lifting as it approaches white squeezes everything against the
    ceiling: with a plain gamma the local contrast at the top comes out at (1 - lift) / gamma, which
    is about half. Half is enough to ruin light ink on a mid ground -- the retro frame letters a gold
    card's title in white, and the band underneath rose far enough to swallow it -- and the black hold
    is no help there, because it protects dark ink on light grounds, the opposite case.

    At taper 1.0 the weight is simply (1 - v): each pixel is lifted in proportion to the room it has
    left, which is also the honest statement of what the lift is for. A mid-grey frame band is not
    buried and does not need raising; a crushed shadow is and does. Taken with a gamma steep enough
    to make up for it, that separates the bottom of the range *better* than the untapered curve did
    (measured on the wedge: 62 levels of spread across the first 10% of input against 56) while
    moving a mid band barely half as far, and it roughly doubles the contrast left at the top.

    What it costs is overall brightness -- the midtones land around 164/255 where the untapered curve
    put them at 190. That cost is real and is the right way to pay: the range between `lift` and white
    is fixed, so slope handed to one part is taken from another, and the dimness of a mirror seen off
    its angle is not something an 8-bit file can fix in the first place. Tilting the card fixes it."""
    lut = []
    for i in range(256):
        v = i / 255
        out = pr.lift + (1 - pr.lift) * v ** (1 / pr.gamma)
        w = 1 - v ** pr.taper          # 1 at black, 0 at white: the lift and its slope both vanish there
        lut.append(round(255 * _clamp(v + (out - v) * w * strength)))
    return lut


def hold_mask(im, hold):
    """Where the lift applies: 255 for the lifted card, 0 for the pixels held as they are, with a
    smoothstep between so the border does not get a ring around it. None when nothing is held.

    Measured on the *original* luminance, not per channel: a saturated red is a bright pixel with a
    dark blue channel, and holding that channel would shift its hue instead of protecting a black."""
    if hold <= 0:
        return None
    top = max(1, round(hold * 255))
    return im.convert("L").point(lambda v: round(255 * (t := min(1.0, v / top)) ** 2 * (3 - 2 * t)))


def prep(im, pr=DEFAULT_PROFILE, strength=1.0):
    """A finished card image as the file to print on `pr`. Returns a new RGB image; the input is
    left alone. `strength` scales the whole treatment, so 0 gives the card back unchanged."""
    pr = profile(pr)
    im = im.convert("RGB")
    if pr is None or strength <= 0:
        return im
    lut = curve(pr, strength)
    out = im.point(lut * 3)
    sat = 1 + (pr.sat - 1) * strength
    if sat != 1:
        out = ImageEnhance.Color(out).enhance(sat)
    mask = hold_mask(im, pr.hold)
    return Image.composite(out, im, mask) if mask else out


def substrate(size, pr=DEFAULT_PROFILE, phase=0.5, band=0.55):
    """The modelled foil the proof multiplies by: a specular sweep up the diagonal, carrying the
    holo layer's hue, dark at the corners where the mirror is pointing the room somewhere else.

    Drawn small and resampled up -- it is a smooth gradient, so 192px carries it, and a Python loop
    over a 2176x2960 card would not be worth waiting for."""
    pr = profile(pr) or PROFILES["flat"]
    n = 192
    s = Image.new("HSV", (n, n))
    px = s.load()
    for y in range(n):
        for x in range(n):
            t = (x + (n - 1 - y)) / (2 * (n - 1))               # 0 at bottom-left, 1 at top-right
            d = _clamp((t - phase) / band, -0.5, 0.5) * math.pi  # the band, a raised cosine across `band`
            spec = math.cos(d) ** 2
            val = pr.base + (1 - pr.base) * spec
            # the rainbow rolls along the same axis and saturates with the sweep: a holo layer is a
            # sheen over a metallic base, not a spectrum -- it tints the ink, it does not replace it,
            # and off its angle it shows its colour faintly and only bands where it catches light
            hue = ((t * pr.turns) % 1.0) if pr.turns else 0.0
            px[x, y] = (round(hue * 255), round(pr.rainbow * 255 * (0.35 + 0.65 * spec)), round(val * 255))
    return s.convert("RGB").resize(size, Image.BICUBIC)


def on_foil(im, pr=DEFAULT_PROFILE, **kw):
    """One card as it would come back off the substrate: ink times foil, which is what a print with
    no white ink under it actually does."""
    im = im.convert("RGB")
    return ImageChops.multiply(im, substrate(im.size, pr, **kw))


# --- the proof sheet -------------------------------------------------------------------------
CAPTION = 0.055   # caption strip height, as a fraction of a panel's height
GAP = 0.03        # gutter between panels, same units
FONT = PKG / "fonts" / "Montserrat-SemiBold.otf"


def _font(px):
    try:
        return ImageFont.truetype(str(FONT), px)
    except OSError:
        return ImageFont.load_default()


def proof(src, out, pr=DEFAULT_PROFILE, strength=1.0, width=2400):
    """Three panels of one card: on paper, on the foil untreated, and on the foil after the prep.
    The middle panel is the one that makes the case -- it is what an untreated order comes back as."""
    pr = profile(pr)
    with Image.open(src) as im:
        card = im.convert("RGB")
    panels = [("on paper", card),
              ("on foil, untreated", on_foil(card, pr)),
              (f"on foil, prepped ({strength:g})", on_foil(prep(card, pr, strength), pr))]
    pw = round((width - 2 * round(width / 3 * GAP)) / 3)
    ph = round(pw * card.height / card.width)
    gap, cap = round(pw * GAP), max(12, round(ph * CAPTION))
    sheet = Image.new("RGB", (3 * pw + 2 * gap, ph + cap), (255, 255, 255))
    draw, font = ImageDraw.Draw(sheet), _font(round(cap * 0.62))
    for i, (label, panel) in enumerate(panels):
        x = i * (pw + gap)
        sheet.paste(panel.resize((pw, ph), Image.LANCZOS), (x, cap))
        draw.text((x + pw // 2, cap // 2), label, font=font, fill=(20, 20, 20), anchor="mm")
    os.makedirs(os.path.dirname(os.path.abspath(out)) or ".", exist_ok=True)
    sheet.save(out, compress_level=6)
    return sheet.size


# --- the calibration sheet -------------------------------------------------------------------
# The wedge's steps, in percent. Weighted to the dark end on purpose: an even 0-100 ramp spends nine of
# its twelve steps above 30%, where foil has never been in any doubt, and leaves two below 20%, which is
# the only part of the range the substrate actually decides.
WEDGE = (0, 2, 4, 6, 8, 10, 14, 20, 30, 45, 70, 100)
PATCH_HTML = """<!doctype html><meta charset=utf-8><style>
  @page { size: ${w}px ${h}px; margin: 0 }
  * { margin: 0; padding: 0; box-sizing: border-box }
  html, body { width: ${w}px; height: ${h}px; background: #000; overflow: hidden }
  body { font: 600 5px/1.1 $font; color: #fff; padding: 8px; display: flex; flex-direction: column }
  h1 { font-size: 7px; letter-spacing: .04em; text-transform: uppercase; margin-bottom: 4px }
  p { font-size: 4.4px; opacity: .72; margin-bottom: 6px; font-weight: 400 }
  .grid { flex: 1; display: grid; gap: 2px; grid-template-columns: repeat($cols, 1fr) }
  /* the outline is what makes the 0% patch a rectangle rather than a hole in the card */
  .cell { position: relative; display: flex; align-items: flex-end; justify-content: center;
          padding-bottom: 2px; outline: .5px solid #6a6a6a; outline-offset: -.25px }
  .cell span { font-size: 4px; text-shadow: 0 0 2px #000, 0 0 2px #000 }
</style><h1>$title</h1><p>$note</p><div class="grid">$cells</div>"""


def _patch_card(title, note, cells, cols):
    return string.Template(PATCH_HTML).substitute(
        w=PAGE["width"], h=PAGE["height"], font=frame.stack(["Montserrat"]), title=title, note=note,
        cols=cols, cells="".join(
            f'<div class="cell" style="background:{bg}"><span style="color:{fg}">{label}</span></div>'
            for bg, fg, label in cells))


def wedge_card():
    """A neutral step wedge. On foil the question is where the bottom steps stop being distinguishable
    from each other -- that is the floor `lift` has to clear."""
    cells = [(f"rgb({v},{v},{v})", "#fff" if v < 55 else "#000", f"{pc}%")
             for pc, v in ((pc, round(pc * 255 / 100)) for pc in WEDGE)]
    return _patch_card("neutral wedge", "the lowest step you can still tell from its neighbour is the floor.",
                       cells, 4)


def palette_card():
    """The frame's own nine colours, which is the question that actually matters: black's frame band
    is nearly the border, and no lift will make it shine."""
    cells = [(FR[0], "#fff" if kind in ("B", "U", "G") else "#000", kind)
             for kind, FR in frame.FRAMES.items()]
    return _patch_card("frame colours", "the nine frame bands. which of these still reads as foil?",
                       cells, 3)


def calibrate(out_dir, pr="sticker", card=None, dpi=600, paper="letter", log=print):
    """Write the calibration cards and an imposed PDF to print on the foil in the tray. Returns
    {"dir", "cards", "pdf", "pages"}."""
    pr = profile(pr)
    out_dir = Path(out_dir)
    (out_dir / "cards").mkdir(parents=True, exist_ok=True)
    made = []

    def save(im, name):
        p = out_dir / "cards" / name
        im.save(p, compress_level=6)
        made.append(str(p))
        log(f"  {name}")
        return p

    log(f"calibration for {pr.lift:.2f}/{pr.gamma:.2f}/{pr.sat:.2f} lift/gamma/sat")
    with Browser(dpi) as b:
        for key, html in (("wedge", wedge_card()), ("palette", palette_card())):
            tmp = out_dir / "cards" / f".{key}.part.png"
            b.render(html, tmp, fit=False)
            with Image.open(tmp) as im:
                raw = im.convert("RGB")
            tmp.unlink()
            # each patch card twice: untreated, then treated, so the sheet carries its own control
            save(raw, f"1-{key}-untreated.png")
            save(prep(raw, pr), f"2-{key}-prepped.png")

    if card:
        with Image.open(card) as im:
            base = im.convert("RGB")
        for s in CAL_STRENGTHS:
            save(prep(base, pr, s), f"3-card-strength-{s:g}.png")
    else:
        log("no --card given: the sheet carries the patch cards only. Point it at a render to get a "
            "run of strengths on a real card, which is what you actually judge by.")

    from . import impose

    name = next((k for k, v in PROFILES.items() if v == pr), "custom")  # a caller may pass a Profile of its own
    pdf = out_dir / f"foil-calibration-{name}.pdf"
    pages = impose.impose(made, str(pdf), paper, 0.04, dpi, log=log)
    log(f"print it with: mint print -p thick {pdf}")
    return {"dir": str(out_dir), "cards": made, "pdf": str(pdf), "pages": pages}


def main(argv=None):
    ap = argparse.ArgumentParser(prog="mint foil", description=__doc__.split("\n\n")[0])
    ap.add_argument("--list", action="store_true", help="the profiles and their numbers")
    ap.add_argument("--proof", metavar="RENDER", help="a three-panel proof of this render")
    ap.add_argument("--prep", metavar="RENDER", help="write this render treated for the profile")
    ap.add_argument("--calibrate", action="store_true", help="a sheet to print on the foil in the tray")
    ap.add_argument("--card", help="--calibrate: the render to show at a run of strengths")
    ap.add_argument("--profile", "-p", default=None, help=f"one of {', '.join(PROFILES)}")
    ap.add_argument("--strength", type=float, default=1.0, help="scale the treatment (default 1)")
    ap.add_argument("--dpi", type=int, default=600, help="--calibrate: the sheet's resolution")
    from . import impose
    ap.add_argument("--paper", default="letter", choices=list(impose.PAPER))
    ap.add_argument("--out", help="where to write (default beside the input, or out/foil-cal/)")
    a = ap.parse_args(argv)

    if a.list:
        print(f"{'profile':9} {'lift':>5} {'gamma':>6} {'taper':>6} {'sat':>5} {'hold':>5}   what")
        for name, p in PROFILES.items():
            what = {"holo": "MakePlayingCards' holographic foil (cards.xml <foil>)",
                    "sticker": "foil sticker paper through the ET-8500 -- calibrate this one",
                    "silver": "a plain metallic sheet: no rainbow",
                    "flat": "the control: no treatment"}[name]
            print(f"{name:9} {p.lift:5.2f} {p.gamma:6.2f} {p.taper:6.2f} {p.sat:5.2f} {p.hold:5.2f}   {what}")
        return 0
    if not (a.proof or a.prep or a.calibrate):
        ap.error("one of --list, --proof, --prep or --calibrate")
    try:
        if a.calibrate:
            # not out/foil/: a set coded FOIL renders there, and the two would sit on top of each other
            r = calibrate(a.out or "out/foil-cal", a.profile or "sticker", a.card, a.dpi, a.paper)
            print(r["pdf"])
        if a.proof:
            out = a.out or str(Path(a.proof).with_suffix("")) + "-foil-proof.png"
            proof(a.proof, out, a.profile or DEFAULT_PROFILE, a.strength)
            print(out)
        if a.prep:
            out = a.out or str(Path(a.prep).with_suffix("")) + "-foil.png"
            with Image.open(a.prep) as im:
                prep(im, a.profile or DEFAULT_PROFILE, a.strength).save(out, compress_level=6)
            print(out)
    except (ValueError, OSError) as e:
        sys.exit(str(e))
    return 0


if __name__ == "__main__":
    sys.exit(main())

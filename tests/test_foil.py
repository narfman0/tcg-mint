"""mint foil: the tone pass a mirror substrate wants, and the two destinations that apply it."""
import xml.etree.ElementTree as ET

import pytest
from PIL import Image

from mint import export, foil, impose


def test_the_curve_holds_both_ends():
    """White is the brightest foil the card can have, so it is never compressed; 0 goes to the floor,
    because nothing below it can separate on a mirror anyway. And it never doubles back."""
    for name, pr in foil.PROFILES.items():
        lut = foil.curve(pr)
        assert lut[255] == 255, name
        assert lut[0] == round(255 * pr.lift), name
        assert all(lut[i + 1] >= lut[i] for i in range(255)), name
    assert foil.curve(foil.PROFILES["flat"]) == list(range(256))          # the control is the identity
    assert foil.curve(foil.PROFILES["holo"], 0) == list(range(256))       # and so is strength 0


def test_the_border_and_the_rules_text_stay_matte():
    """The hold is the whole reason a treated card does not look washed out: pure black is what the
    border, the art's bevel and the rules text are, and those are meant to go matte on foil."""
    card = Image.new("RGB", (8, 8), (0, 0, 0))
    card.paste((60, 70, 80), (2, 2, 6, 6))       # a dark picture inside a black border
    out = foil.prep(card, "holo")
    assert out.getpixel((0, 0)) == (0, 0, 0)                 # the border, untouched
    assert out.getpixel((3, 3))[0] > 60 + 20                 # the picture, opened up
    assert foil.prep(card, "holo", 0).tobytes() == card.tobytes()   # strength 0 changes nothing
    assert foil.prep(card, "flat").tobytes() == card.tobytes()      # and neither does the control


def test_the_hold_reads_luminance_not_channels():
    """A saturated red is a bright pixel with a dark blue channel. Holding that channel would shift
    its hue instead of protecting a black, so the mask is measured on luminance."""
    red = Image.new("RGB", (4, 4), (220, 0, 0))
    out = foil.prep(red, "holo")
    assert out.getpixel((0, 0))[2] > 20, "the blue channel of a bright red was held as if it were black"
    black = Image.new("RGB", (4, 4), (0, 0, 0))
    assert foil.prep(black, "holo").getpixel((0, 0)) == (0, 0, 0)


def test_the_lift_never_darkens_and_never_clips():
    """Every value comes back at least where it started and inside the range: the pass opens the
    shadows, and the only thing it is allowed to take away is saturation."""
    ramp = Image.new("L", (256, 1))
    for i in range(256):
        ramp.putpixel((i, 0), i)
    out = foil.prep(ramp.convert("RGB"), "sticker")
    vals = [out.getpixel((i, 0))[0] for i in range(256)]
    assert all(0 <= v <= 255 for v in vals)
    assert all(v >= i for i, v in enumerate(vals))
    # and it stays smooth: a step big enough to contour would show as a ring in the deep shadows
    assert max(vals[i + 1] - vals[i] for i in range(255)) <= 8


def test_the_lift_leaves_the_highlights_their_contrast():
    """The bug this guards: white is clamped, so a curve that keeps lifting as it nears white squeezes
    everything against the ceiling. With a plain gamma the slope at the top is (1 - lift) / gamma --
    about half -- which was enough to swallow the retro frame's white title on its gold band. The
    taper has to hand that contrast back."""
    for name, pr in foil.PROFILES.items():
        if name == "flat":
            continue
        lut = foil.curve(pr)
        top = (lut[255] - lut[255 - 20]) / 20          # local slope over the last 8% of the range
        assert top >= 0.85, f"{name}: highlights compressed to {top:.2f}x"

    # and end to end: white lettering on a mid ground keeps most of its separation
    card = Image.new("RGB", (8, 8), (130, 120, 90))    # the retro gold band
    card.paste((255, 255, 255), (2, 2, 6, 6))          # the title's white letters
    out = foil.prep(card, "sticker")
    before = card.getpixel((3, 3))[0] - card.getpixel((0, 0))[0]
    after = out.getpixel((3, 3))[0] - out.getpixel((0, 0))[0]
    assert after > before * 0.6, f"the band rose into the lettering: {before} -> {after}"


def test_the_lift_is_spent_where_there_is_room_for_it():
    """What the taper means: a pixel is raised in proportion to the room it has left. A buried shadow
    is what the lift is for; a mid-grey frame band is not buried and moving it only costs the contrast
    of whatever is printed over it."""
    for name, pr in foil.PROFILES.items():
        if name == "flat":
            continue
        lut = foil.curve(pr)
        raised = [lut[i] - i for i in range(256)]           # how far each input was moved
        assert raised[26] > 2 * raised[128], name           # shadows move much further than midtones
        assert raised[242] <= 3, name                       # and near white, barely at all
        assert raised[0] == round(255 * pr.lift), name      # the floor is still the floor


def test_an_unknown_profile_is_refused():
    with pytest.raises(ValueError, match="no foil profile"):
        foil.profile("rainbow-sparkle")
    assert foil.profile(None) is None
    assert foil.profile(foil.PROFILES["holo"]) is foil.PROFILES["holo"]


def test_the_substrate_is_a_mirror_a_multiply_can_model():
    """The proof is ink times foil, so the substrate can only ever take light away -- which is the
    honest model of a print with no white ink under it."""
    card = Image.new("RGB", (40, 56), (200, 200, 200))
    sub = foil.substrate(card.size, "holo")
    assert sub.size == card.size
    got = foil.on_foil(card, "holo")
    assert all(v <= 200 for v in got.tobytes())
    px = lambda im: [tuple(im.tobytes()[i:i + 3]) for i in range(0, len(im.tobytes()), 3)]  # noqa: E731
    # a plain mirror has no rainbow in it: every pixel of its substrate is neutral
    assert all(r == g == b for r, g, b in px(foil.substrate((16, 16), "silver")))
    # a holo one does
    assert any(max(p) - min(p) > 12 for p in px(foil.substrate((64, 64), "holo")))


def test_the_wedge_crowds_the_dark_end_and_the_palette_carries_every_frame():
    """The wedge is only useful where the substrate is actually in doubt, and the palette card has
    to ask about every frame the set could print."""
    from mint import frame
    assert sorted(foil.WEDGE) == list(foil.WEDGE) and foil.WEDGE[0] == 0 and foil.WEDGE[-1] == 100
    assert sum(1 for p in foil.WEDGE if p <= 20) >= 8, "the dark end is where the answer is"
    html = foil.palette_card()
    for kind, colours in frame.FRAMES.items():
        assert colours[0] in html, kind
    assert all(f"{p}%" in foil.wedge_card() for p in foil.WEDGE)


def test_a_proof_lays_the_argument_out_in_three_panels(tmp_path):
    src = tmp_path / "card.png"
    Image.new("RGB", (272, 372), (30, 40, 50)).save(src)
    out = tmp_path / "proof.png"
    w, h = foil.proof(src, out, "holo")
    assert out.is_file() and w > h                      # three cards wide, one deep, plus captions
    with Image.open(out) as im:
        assert im.size == (w, h)


# --- the two destinations -----------------------------------------------------------------
def test_an_mpc_image_is_treated_last(tmp_path):
    """After the resample, so the held blacks are the pixels that get printed rather than ones
    LANCZOS is about to move."""
    src = tmp_path / "render.png"
    im = Image.new("RGB", (272, 372), (0, 0, 0))
    im.paste((60, 60, 60), (40, 40, 232, 332))
    im.save(src)
    plain, foiled = tmp_path / "a.png", tmp_path / "b.png"
    assert export.mpc_image(src, plain, 300) == export.mpc_image(src, foiled, 300, foil_profile="holo")
    with Image.open(plain) as a, Image.open(foiled) as b:
        assert b.getpixel((408, 555))[0] > a.getpixel((408, 555))[0]   # the middle was lifted
        assert a.getpixel((4, 4)) == b.getpixel((4, 4)) == (0, 0, 0)   # the bleed stayed black


def test_the_order_file_says_foil_and_nothing_else_moves():
    """The only thing about the order that changes is the tag: MakePlayingCards wants the same
    images, at the same size, with the same bleed."""
    args = ([(0, "images/001 Alpha.png", "Alpha")], [], "images/back.png")
    plain = ET.fromstring(export.order_xml(*args))
    foiled = ET.fromstring(export.order_xml(*args, foil=True))
    assert plain.find("details").findtext("foil") == "false"
    assert foiled.find("details").findtext("foil") == "true"
    for tag in ("quantity", "bracket", "stock"):
        assert plain.find("details").findtext(tag) == foiled.find("details").findtext(tag)


def test_imposing_a_sheet_can_treat_it_on_the_way(tmp_path):
    """Foil in the tray has no white ink under it either, so the sheet wants the same lift."""
    src = tmp_path / "card.png"
    im = Image.new("RGB", (272, 372), (0, 0, 0))
    im.paste((70, 70, 70), (30, 30, 242, 342))
    im.save(src)
    plain = impose.prepare(str(src), 0.04, 100, str(tmp_path), 0)
    foiled = impose.prepare(str(src), 0.04, 100, str(tmp_path), 1, foil="sticker")
    with Image.open(plain) as a, Image.open(foiled) as b:
        assert a.size == b.size
        assert b.getpixel((129, 179))[0] > a.getpixel((129, 179))[0]
    with pytest.raises(ValueError, match="no foil profile"):
        impose.impose([str(src)], str(tmp_path / "s.pdf"), foil="glitter")

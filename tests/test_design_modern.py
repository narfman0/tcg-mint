"""The modern design, the 2003 frame (mint/designs/modern.css): golden renders of a creature, a legend and a
basic land in it, compared pixel-wise against tests/golden/design-modern-*.png the way tests/test_golden.py
does (synthetic cards, dot symbols, the packaged fonts alone, 150 dpi), the frame's features read straight off
the renders, and the css checked for its conventions.

After an intentional change to the design, regenerate its goldens and commit them:

    MINT_UPDATE_GOLDEN=1 pytest -m render tests/test_design_modern.py
"""
import os
import re
import shutil
import statistics

import pytest
from PIL import Image

from mint import frame
from tests import test_golden
from tests.conftest import synthetic_card
from tests.test_golden import GOLDEN, MEAN_TOL, OUTLIER_FRAC, OUTLIER_LEVEL, DotSymbols, compare

pytest.importorskip("playwright")

browser = test_golden.browser  # the golden suite's one Chromium, a module fixture, registered here under its name

# a plain creature (the conftest's default: a blue rare with a P/T box, which M15 would stamp), the golden suite's
# legend (a two-colour mythic: no crown here, gold's palette, no stamp) and a basic land (the land band with the
# plate in the basic's own colour, the mana glyph in the text box)
CARDS = {
    "creature": {},
    "legend": test_golden.CARDS["legend"],
    "basic": dict(name="Proving Ground", type_line="Basic Land — Forest", colors=[], mana_cost="", rarity="common",
                  power=None, toughness=None, oracle_text="({T}: Add {G}.)", flavor_text=None, produced_mana=["G"]),
}


def render(name, art, tmp_path, browser, design="modern"):
    card = synthetic_card(**(CARDS[name] if name in CARDS else test_golden.CARDS[name]))
    fonts_css = frame.local_fonts(tmp_path / "no-workspace-fonts")  # the packaged faces: Almendra stands in for Matrix
    html = frame.build_html(card, symbols=DotSymbols(), art_url="file://" + art, theme="wizards", fonts_css=fonts_css,
                            set_size=3, maker="tester", year="2026", design=design)
    assert "fonts.googleapis.com" not in html  # the wizards theme stays offline
    if frame.layout_of(card) not in frame.M15_LAYOUTS:
        assert f" design-{design} " in html and " kind-" in html
    out = tmp_path / f"{name}-{design}.png"
    return out, browser.render(html, out)


def rules(css):
    """(selector, declarations) for each rule of the css, comments stripped."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    return [(sel.strip(), body) for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css)]


def test_the_css_is_scoped_and_paints_every_kind():
    """Every rule is under the design's class; the palette names every frame kind the base has, on the variables
    the base draws from; the crown, the tongues and the stamp are hidden, the bars reshaped rather than the
    base's pieces restated; the title face is Matrix Bold first."""
    css = frame.design_css("modern")
    for sel, _ in rules(css):
        for part in sel.split(","):
            assert part.strip().startswith(".design-modern"), f"a rule outside the design's class: {sel}"
    for kind in frame.FRAMES:
        decls = [(sel, body) for sel, body in rules(css)
                 if re.fullmatch(rf"\.design-modern\.kind-{kind}(:not\(\.pair\))?", sel)]
        assert decls, f"no palette for {kind}"
        every = "".join(body for _, body in decls)
        assert "--frame:" in every and "--bar:" in every and "--box:" in every
        assert ("--pinline:" in every) == (kind != "land")  # a land's plate is the base's tint, darkened
        # the bars and the text box of a two-colour card are the base's (PAIR_BAR, DUAL_BOX, both colours): the
        # design has no second colour to answer with, so its own must stand aside for .pair
        for var in ("--bar:", "--box:"):
            holders = [sel for sel, body in decls if var in body]
            assert holders, f"{kind}: no {var}"
            if kind in ("gold", "land"):  # where frame_kind puts a two-colour card: a hybrid spell and a dual land
                assert all(":not(.pair)" in sel for sel in holders), f"{kind} {var} overrides a pair's"
    assert ".design-modern .crown-o, .design-modern .crown, .design-modern .pl-crown { display: none; }" in css
    assert ".design-modern .stamp { display: none; }" in css
    assert "--title-font: 'Matrix Bold'" in css
    assert re.search(r"\.design-modern \.bar \{[^}]*clip-path: none;[^}]*border-radius: 3\.5px / 50%", css)


def test_the_design_takes_the_card_and_the_layouts_fall_back(art):
    """A 2003-frame printing resolves to the design; build_html drops it for the layouts whose art is elsewhere."""
    assert frame.printed_design(synthetic_card(frame="2003")) == "modern"
    html = frame.build_html(synthetic_card(), symbols=DotSymbols(), art_url="file://" + art, design="modern")
    assert 'class="card normal stamped stamp-oval design-modern rarity-rare kind-U"' in html
    assert ".design-modern .stamp { display: none; }" in html  # the base still marks the stamp; the design hides it
    saga = frame.build_html(synthetic_card(**test_golden.CARDS["saga"]), symbols=DotSymbols(), art_url="file://" + art,
                            design="modern")
    assert "design-m15" in saga and "design-modern" not in saga


def pixel(im, x, y):
    """The pixel under a point in card units, at 150 dpi (1.5 px per unit, the card at 11,11 in the page)."""
    return im.getpixel((int((x + 11) * 1.5), int((y + 11) * 1.5)))


def band(im, x0, x1, y0, y1):
    """The median brightness of a rectangle in card units: the painted texture swings 60 to 200 pixel to pixel,
    so the band's tone is only readable over an area."""
    return statistics.median(sum(im.getpixel((x, y))) / 3
                             for x in range(int((x0 + 11) * 1.5), int((x1 + 11) * 1.5))
                             for y in range(int((y0 + 11) * 1.5), int((y1 + 11) * 1.5)))


def lightest(im, x0, x1, y0, y1):
    """The whitest pixel in a rectangle: the collector line's ink against its band."""
    return max(min(im.getpixel((x, y))) for x in range(int((x0 + 11) * 1.5), int((x1 + 11) * 1.5))
               for y in range(int((y0 + 11) * 1.5), int((y1 + 11) * 1.5)))


@pytest.mark.render
def test_the_2003_geometry(art, tmp_path, browser):
    """Read off the creature's render: the border 12 wide, the band up to it at the foot (no arc: the band's own
    blue at 330 in the corner, where M15 shows black), the plate's dark blue between the bar and the art, the
    art's black line at 40 and 195, the text box lower and shorter (its face at 220 and 313, the plate at 316),
    no stamp in the box's foot, and the collector line's black ink on the band."""
    out, sizes = render("creature", art, tmp_path, browser)
    im = Image.open(out).convert("RGB")
    u = lambda x, y: pixel(im, x, y)
    assert sizes["text"] == 12.6  # the shorter box still holds the fixture's text unshrunk
    assert u(6, 120) == (0, 0, 0) and u(11, 120) == (0, 0, 0) and u(13, 120) != (0, 0, 0)  # the border to 12
    assert max(u(14, 330)) > 60 and max(u(236, 330)) > 60  # the band still there at the foot's corners
    assert u(125, 39)[2] > 120 and max(u(125, 39)) < 200  # the plate between the bar and the art: the 2003 blue
    assert max(u(125, 40.5)) < 50 and max(u(125, 194.5)) < 50  # the art's line above and below the image
    assert max(u(20.5, 120)) < 50 and max(u(229.5, 120)) < 50  # and beside it
    face = u(225, 222)  # the box's face, clear of the text, at its top right and bottom left (220 to 313)
    near = lambda a, b: all(abs(x - y) <= 4 for x, y in zip(a, b))  # the paper grain is a shade either way
    assert min(face) > 200 and near(u(30, 311), face) and near(u(225, 300), face)
    assert u(125, 316) != face and max(u(125, 316)) < 200  # the plate under it
    assert u(125, 322) != face and max(u(125, 320.5)) < 200  # no stamp: the band's bevel and the band, not silver
    assert any(max(u(x, 334)) < 40 for x in range(20, 60))  # black collector ink on the band


@pytest.mark.render
def test_a_legend_has_no_crown_and_a_basic_keeps_its_tint_on_a_darkening_band(art, tmp_path, browser):
    out, _ = render("legend", art, tmp_path, browser)
    im = Image.open(out).convert("RGB")
    u = lambda x, y: pixel(im, x, y)
    assert max(u(125, 13)) > 60 and max(u(125, 15)) > 60  # the band runs over the top: no crown's valleys
    assert max(u(30, 17)) > 40 and u(30, 17) != (0, 0, 0)  # the plate above the bar, where the crown's outline would be
    out, _ = render("basic", art, tmp_path, browser)
    im = Image.open(out).convert("RGB")
    u = lambda x, y: pixel(im, x, y)
    r, g, b = u(125, 39)  # the plate on a Forest is green's tint darkened, not the land brown
    assert g > r and g > b
    # and the land band darkens down the card (the prints' foot reads 0.66 of the rails beside the art), which is
    # what the white collector line is printed on
    assert band(im, 150, 225, 321, 336) < 0.85 * band(im, 12.4, 14.4, 60, 180)
    assert lightest(im, 19, 130, 320, 337) > 200  # white ink on it


@pytest.mark.render
def test_a_planeswalker_keeps_the_base_box_on_a_black_foot(art, tmp_path, browser):
    """The design leaves a planeswalker's sheet, its badges and its loyalty shield where the base puts them --
    the 2003 print puts that block within 4 of there -- so no black shows past the box's edges; the stamp's bite
    goes with the stamp; and below the box the card is black to its edge, the collector line white on it."""
    out, _ = render("planeswalker", art, tmp_path, browser)
    im = Image.open(out).convert("RGB")
    u = lambda x, y: pixel(im, x, y)
    assert min(u(226, 222)) > 200  # the box's face, inside its outline at the top right
    assert min(u(125, 317)) > 200  # and at its foot in the middle: no bite where the stamp would be
    assert max(u(233, 250)) > 60  # the strip beside the box, not the sheet: no black past the box's outline
    assert u(125, 330) == (0, 0, 0)  # no bottom band under the box, as the print has none
    assert lightest(im, 19, 130, 323, 337) > 200  # white collector ink on the black


@pytest.mark.render
@pytest.mark.parametrize("name", list(CARDS))
def test_golden_modern(name, art, tmp_path, browser):
    out, sizes = render(name, art, tmp_path, browser)
    assert Image.open(out).size == (408, 558)
    assert sizes["text"] == 12.6
    golden = GOLDEN / f"design-modern-{name}.png"
    if os.environ.get("MINT_UPDATE_GOLDEN"):
        GOLDEN.mkdir(exist_ok=True)
        shutil.copy(out, golden)
        return
    assert golden.exists(), f"no golden for {name}; create it with MINT_UPDATE_GOLDEN=1 ({golden})"
    mean, outliers, diff = compare(out, golden)
    if mean >= MEAN_TOL or outliers >= OUTLIER_FRAC:
        diff_fn = tmp_path / f"design-modern-{name}.diff.png"
        diff.point(lambda v: min(255, v * 4)).save(diff_fn)
        pytest.fail(f"{name} differs from {golden}: mean |diff| {mean:.3f} (limit {MEAN_TOL}), "
                    f"{outliers:.2%} of pixels off by more than {OUTLIER_LEVEL} (limit {OUTLIER_FRAC:.1%}). "
                    f"render: {out}  diff: {diff_fn}")

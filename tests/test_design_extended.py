"""The extended-art design (mint/designs/extended.css): golden renders of a creature, a legend and a common in
it, compared pixel-wise against tests/golden/design-extended-*.png the way tests/test_golden.py does, the
features read off the renders (the art in the bleed, the glass type bar, the crown's cut), and the proof that
a layout whose art lives elsewhere (a saga) still renders as M15 in it.

After an intentional change to the design, regenerate its goldens and commit them:

    MINT_UPDATE_GOLDEN=1 pytest -m render tests/test_design_extended.py
"""
import os
import shutil

import pytest
from PIL import Image

from mint import frame
from tests import test_golden
from tests.conftest import synthetic_card
from tests.test_golden import GOLDEN, MEAN_TOL, OUTLIER_FRAC, OUTLIER_LEVEL, DotSymbols, compare

pytest.importorskip("playwright")

browser = test_golden.browser  # the golden suite's one Chromium, a module fixture, registered here under its name

# a plain creature (the conftest's default: rare, stamped, a P/T box) and the golden suite's legend (a crown, a
# two-colour pair, a mythic stamp); a common creature for the white edge the black type bar gives its set symbol
CARDS = {
    "creature": {},
    "legend": test_golden.CARDS["legend"],
    "common": dict(name="Fixture Scout", type_line="Creature — Fixture Scout", colors=["G"], mana_cost="{1}{G}",
                   rarity="common", power="2", toughness="1", oracle_text="Vigilance", flavor_text="It watches."),
}


def render(name, art, tmp_path, browser, design="extended"):
    card = synthetic_card(**(CARDS[name] if name in CARDS else test_golden.CARDS[name]))
    fonts_css = frame.local_fonts(tmp_path / "no-workspace-fonts")
    html = frame.build_html(card, symbols=DotSymbols(), art_url="file://" + art, theme="wizards", fonts_css=fonts_css,
                            set_size=3, maker="tester", year="2026", design=design)
    if frame.layout_of(card) not in frame.M15_LAYOUTS:
        assert f"design-{design}" in html
    out = tmp_path / f"{name}-{design}.png"
    return out, browser.render(html, out)


def check(out, golden, tmp_path, label):
    if os.environ.get("MINT_UPDATE_GOLDEN"):
        GOLDEN.mkdir(exist_ok=True)
        shutil.copy(out, golden)
        return
    assert golden.exists(), f"no golden for {label}; create it with MINT_UPDATE_GOLDEN=1 ({golden})"
    mean, outliers, diff = compare(out, golden)
    if mean >= MEAN_TOL or outliers >= OUTLIER_FRAC:
        diff_fn = tmp_path / f"{label}.diff.png"
        diff.point(lambda v: min(255, v * 4)).save(diff_fn)
        pytest.fail(f"{label} differs from {golden}: mean |diff| {mean:.3f} (limit {MEAN_TOL}), "
                    f"{outliers:.2%} of pixels off by more than {OUTLIER_LEVEL} (limit {OUTLIER_FRAC:.1%}). "
                    f"render: {out}  diff: {diff_fn}")


@pytest.mark.render
@pytest.mark.parametrize("name", list(CARDS))
def test_golden_extended(name, art, tmp_path, browser):
    out, sizes = render(name, art, tmp_path, browser)
    assert Image.open(out).size == (408, 558)
    assert sizes["text"] == 12.6  # the text box is the M15 one, nothing was shrunk
    check(out, GOLDEN / f"design-extended-{name}.png", tmp_path, f"design-extended-{name}")


def pixel(im, x, y):
    """The pixel under a point in card units, at 150 dpi (1.5 px per unit, the card at 11,11 in the page)."""
    return im.getpixel((int((x + 11) * 1.5), int((y + 11) * 1.5)))


@pytest.mark.render
def test_extended_art_reaches_the_bleed_and_the_type_bar_is_black_glass(art, tmp_path, browser):
    """The art at the page's edges beside the window, the type bar a black glass over it (its face carries the
    art's own colour, fading to black at the foot), the M15 window's pieces (the coloured band beside the art,
    the pinline round the type bar) gone: read straight off the render."""
    out, _ = render("creature", art, tmp_path, browser)
    im = Image.open(out).convert("RGB")
    u = lambda x, y: pixel(im, x, y)
    # the M15 art is a gradient from black at its top-left, never grey: the page's edge beside the art carries it
    assert u(-10, 120) != (0, 0, 0) and u(259, 120) != (0, 0, 0)
    assert u(-10, 25) == (0, 0, 0) and u(-10, 300) == (0, 0, 0)  # the bleed is black above and below
    # the glass: the fixture art's red rises with x, and so does the bar's face just under the rim, darker than
    # the art above the bar at the same x; at the foot the face is near black whatever the art
    assert u(60, 192)[0] < u(180, 192)[0]
    assert u(60, 201)[0] < u(180, 201)[0] < u(180, 192)[0]
    assert 0.3 < u(180, 201)[0] / u(180, 192)[0] < 0.8
    assert max(u(190, 214)) < 32
    # and its text is light
    assert any(sum(u(x, 207)) > 600 for x in range(24, 60))


@pytest.mark.render
def test_extended_crown_stops_at_the_bar(art, tmp_path, browser):
    """A legendary's crown has no tongue beside the art: at y 50 both sides are art (the fixture's flat blue,
    128, in every art pixel); the plate under the bar bows to 41.7 at the ends, in the crown's own colour, with
    the black line beneath it."""
    out, _ = render("legend", art, tmp_path, browser)
    im = Image.open(out).convert("RGB")
    u = lambda x, y: pixel(im, x, y)
    assert all(abs(u(x, 50)[2] - 128) <= 2 for x in (12, 14, 16, 234, 236, 238))
    assert u(24, 40) == u(24, 38) and u(226, 40) == u(226, 38)  # the plate is the crown at its ends
    assert u(24, 40)[2] != 128 and max(u(24, 42)) < 40  # not art, and the line under it
    assert max(u(125, 39.2)) < 40 and abs(u(125, 41)[2] - 128) <= 2  # the middle keeps the M15 line and image


@pytest.mark.render
def test_other_layouts_stay_m15_in_extended(art, tmp_path, browser):
    """A saga's art is not the window the design widens: in the extended design it renders exactly as in M15."""
    out, _ = render("saga", art, tmp_path, browser)
    mean, outliers, _ = compare(out, GOLDEN / "saga.png")
    assert mean < MEAN_TOL and outliers < OUTLIER_FRAC


def test_the_frame_keeps_m15_for_the_layouts_whose_art_is_elsewhere(art):
    """build_html drops the design for a saga, class, split or battle (frame.M15_LAYOUTS), so no design css
    needs a layout in its selectors."""
    from tests.test_golden import DotSymbols
    for name in ("saga", "split"):
        card = synthetic_card(**test_golden.CARDS[name])
        html = frame.build_html(card, symbols=DotSymbols(), art_url="file://" + art, design="extended")
        assert "design-m15" in html and "design-extended" not in html
    for d in ("extended", "borderless", "fullart"):
        css = frame.design_css(d)
        for layout in frame.M15_LAYOUTS:
            assert f".{layout}" not in css

"""The extended-art design (mint/designs/extended.css): golden renders of a creature and a legend in it,
compared pixel-wise against tests/golden/design-extended-*.png the way tests/test_golden.py does, and
the proof that a layout whose art lives elsewhere (a saga) still renders as M15 in it.

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


@pytest.mark.render
def test_extended_art_reaches_the_bleed_and_the_type_bar_is_black(art, tmp_path, browser):
    """The art at the page's edges beside the window, the type bar's face near black, the M15 window's pieces
    (the coloured band beside the art, the pinline round the type bar) gone: read straight off the render, at
    150 dpi (1.5 px per card unit, the card at 11,11 in the page)."""
    out, _ = render("creature", art, tmp_path, browser)
    im = Image.open(out).convert("RGB")
    u = lambda x, y: im.getpixel((round((x + 11) * 1.5), round((y + 11) * 1.5)))  # card units to a pixel
    # the M15 art is a gradient from black at its top-left, never grey: the page's edge beside the art carries it
    assert u(-10, 120) != (0, 0, 0) and u(259, 120) != (0, 0, 0)
    assert u(-10, 25) == (0, 0, 0) and u(-10, 300) == (0, 0, 0)  # the bleed is black above and below
    # the type bar's face, right of its text: near black, well under the M15 bar's light fill
    r, g, b = u(190, 212)
    assert max(r, g, b) < 40
    # and its text is light
    assert any(sum(u(x, 207)) > 600 for x in range(24, 60))


@pytest.mark.render
def test_other_layouts_stay_m15_in_extended(art, tmp_path, browser):
    """A saga's art is not the window the design widens: in the extended design it renders exactly as in M15."""
    out, _ = render("saga", art, tmp_path, browser)
    mean, outliers, _ = compare(out, GOLDEN / "saga.png")
    assert mean < MEAN_TOL and outliers < OUTLIER_FRAC


def test_extended_css_is_scoped_to_the_window_layouts():
    css = frame.design_css("extended")
    assert ".design-extended:is(.normal, .planeswalker, .adventure)" in css
    for layout in ("saga", "class", "split", "battle"):
        assert f".{layout}" not in css.replace("(saga, class, split, battle)", "")

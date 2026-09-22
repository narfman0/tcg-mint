"""The full-art design (mint/designs/fullart.css): golden renders of a creature and a basic land, the same
way tests/test_golden.py does the M15 frame (synthetic cards, dot symbols, 150 dpi), against
tests/golden/design-fullart-*.png. Regenerate after an intentional change:

    MINT_UPDATE_GOLDEN=1 pytest -m render tests/test_design_fullart.py
"""
import os
import shutil

import pytest
from PIL import Image

from mint import frame
from tests.conftest import synthetic_card
from tests.test_golden import CARDS, DPI, GOLDEN, MEAN_TOL, OUTLIER_FRAC, OUTLIER_LEVEL, DotSymbols, compare

pytest.importorskip("playwright")

# a legendary mythic creature (crown, stamp, P/T, flavour: everything that floats over the art at once)
# and a basic land (no plate, the type bar at the foot with the mana medallion)
FULLART = {
    "creature": CARDS["legend"],
    "basic": dict(name="Proving Ground", type_line="Basic Land — Forest", colors=[], mana_cost="", rarity="common",
                  power=None, toughness=None, oracle_text="({T}: Add {G}.)", flavor_text=None, produced_mana=["G"]),
}


@pytest.fixture(scope="module")
def browser():  # test_golden's, again: a module-scoped fixture is not importable, only conftest's are shared
    from mint.browser import Browser
    with Browser(DPI) as b:
        yield b


def render(name, art, tmp_path, browser):
    card = synthetic_card(**FULLART[name])
    fonts_css = frame.local_fonts(tmp_path / "no-workspace-fonts")
    html = frame.build_html(card, symbols=DotSymbols(), art_url="file://" + art, theme="wizards", fonts_css=fonts_css,
                            set_size=len(FULLART), maker="tester", year="2026", design="fullart")
    assert 'class="card' in html and " design-fullart" in html
    assert ".design-fullart .art { left: -11px; top: -11px; width: 272px; height: 372px; }" in html
    out = tmp_path / f"design-fullart-{name}.png"
    return out, browser.render(html, out)


def test_the_css_moves_the_art_and_hides_the_band_only():
    """The design file moves or hides M15 pieces; it never sets the bars' or the text box's geometry."""
    css = frame.design_css("fullart")
    assert ".design-fullart .frame" in css and ".design-fullart .pl-art { display: none; }" in css
    for piece in (".titlebar {", ".pl-title {", ".pt {", ".stamp {", ".footer {"):
        assert piece not in css.replace(".design-fullart", ""), f"restated: {piece}"


@pytest.mark.render
@pytest.mark.parametrize("name", list(FULLART))
def test_golden_fullart(name, art, tmp_path, browser):
    out, sizes = render(name, art, tmp_path, browser)
    assert Image.open(out).size == (408, 558)
    assert sizes["text"] == 12.6  # neither card's text needed shrinking: the plate is the M15 box, the medallion holds one pip
    golden = GOLDEN / f"design-fullart-{name}.png"
    if os.environ.get("MINT_UPDATE_GOLDEN"):
        GOLDEN.mkdir(exist_ok=True)
        shutil.copy(out, golden)
        return
    assert golden.exists(), f"no golden for {name}; create it with MINT_UPDATE_GOLDEN=1 ({golden})"
    mean, outliers, diff = compare(out, golden)
    if mean >= MEAN_TOL or outliers >= OUTLIER_FRAC:
        diff_fn = tmp_path / f"design-fullart-{name}.diff.png"
        diff.point(lambda v: min(255, v * 4)).save(diff_fn)
        pytest.fail(f"{name} differs from {golden}: mean |diff| {mean:.3f} (limit {MEAN_TOL}), "
                    f"{outliers:.2%} of pixels off by more than {OUTLIER_LEVEL} (limit {OUTLIER_FRAC:.1%}). "
                    f"render: {out}  diff: {diff_fn}")

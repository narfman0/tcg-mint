"""Golden renders: three synthetic cards through the wizards theme, with only the
packaged fonts, compared pixel-wise against tests/golden/*.png.

After an intentional change to the frame, regenerate the goldens and commit them:

    MINT_UPDATE_GOLDEN=1 pytest -m render tests/test_golden.py

On failure the amplified diff image is written next to the render in the pytest
tmp dir; the assertion message carries both paths.
"""
import base64
import os
import shutil
from pathlib import Path

import pytest
from PIL import Image, ImageChops

from mint import frame
from tests.conftest import synthetic_card

pytest.importorskip("playwright")

GOLDEN = Path(__file__).parent / "golden"
DPI = 150
MEAN_TOL = 1.5          # mean absolute channel difference (0-255) allowed
OUTLIER_LEVEL = 24      # a pixel "differs" when some channel is off by more than this...
OUTLIER_FRAC = 0.005    # ...and at most this share of pixels may


class DotSymbols:
    """Stands in for frame.Symbols: every mana symbol is one inline circle, so no Scryfall SVG is needed."""
    SVG = base64.b64encode(b"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 20 20'>"
                           b"<circle cx='10' cy='10' r='9' fill='#c9c1a6' stroke='#000' stroke-width='1'/></svg>").decode()

    def data_uri(self, sym):
        return "data:image/svg+xml;base64," + self.SVG


LONG_RULES = ("This land enters tapped unless you control two or more other lands.\n"
              "{T}: Add {C}.\n"
              "{2}, {T}: Look at the top card of your library. You may put it into your graveyard. "
              "If you do, draw a card. (Reminder text goes here.)\n"
              "{4}, {T}, Sacrifice this land: Search your library for a basic land card, put it onto the "
              "battlefield tapped, then shuffle. Activate only as a sorcery.")

# no Wizards text or art: names, rules and flavor are made up, the art is a gradient
CARDS = {
    "legend": dict(name="Test Subject, the Fixture", type_line="Legendary Creature — Fixture Wizard",
                   colors=["U", "R"], mana_cost="{2}{U}{R}", rarity="mythic", power="3", toughness="4",
                   oracle_text="Flying, haste\n{T}, {U}: Draw a card, then discard a card. (Reminder text goes here.)",
                   flavor_text="A *fixture* speaks, and the room listens."),
    "land": dict(name="Proving Grounds", type_line="Land — Fixture", colors=[], mana_cost="", rarity="uncommon",
                 power=None, toughness=None, oracle_text=LONG_RULES, flavor_text=None),
    "artifact": dict(name="Fixture's Tools", type_line="Artifact — Equipment", colors=[], mana_cost="{3}",
                     rarity="common", power=None, toughness=None,
                     oracle_text="Equipped creature gets +1/+1.\nEquip {2} ({2}: Fasten this to a creature you control. "
                                 "Do it only when you could cast a sorcery.)",
                     flavor_text="Every fixture needs fixing."),
}


@pytest.fixture(scope="module")
def browser():
    from mint.browser import Browser
    with Browser(DPI) as b:
        yield b


def render(name, art, tmp_path, browser):
    card = synthetic_card(**CARDS[name])
    fonts_css = frame.local_fonts(tmp_path / "no-workspace-fonts")  # only the packaged faces, never the user's
    html = frame.build_html(card, symbols=DotSymbols(), art_url="file://" + art, theme="wizards", fonts_css=fonts_css,
                            number=list(CARDS).index(name) + 1, set_code="TST", set_size=len(CARDS),
                            maker="tester", maker_code="TS", year="2026")
    assert "fonts.googleapis.com" not in html  # the wizards theme is fully offline
    assert str(frame.FONTS) in html
    out = tmp_path / f"{name}.png"
    return out, browser.render(html, out)


def compare(got, want):
    """(mean absolute channel difference, share of pixels off by more than OUTLIER_LEVEL, diff image)."""
    a, b = Image.open(got).convert("RGB"), Image.open(want).convert("RGB")
    assert a.size == b.size, f"{got} is {a.size}, golden {want} is {b.size}"
    diff = ImageChops.difference(a, b)
    n = a.width * a.height
    mean = sum((i % 256) * c for i, c in enumerate(diff.histogram())) / (3 * n)
    r, g, bl = diff.split()
    worst = ImageChops.lighter(ImageChops.lighter(r, g), bl)
    outliers = sum(worst.histogram()[OUTLIER_LEVEL + 1:]) / n
    return mean, outliers, diff


@pytest.mark.render
@pytest.mark.parametrize("name", list(CARDS))
def test_golden(name, art, tmp_path, browser):
    out, sizes = render(name, art, tmp_path, browser)
    assert Image.open(out).size == (408, 558)
    if name == "land":
        assert frame.TEXT_FLOOR <= sizes["text"] < 11.6  # the long text was shrunk to fit
    else:
        assert sizes["text"] == 11.6
    golden = GOLDEN / f"{name}.png"
    if os.environ.get("MINT_UPDATE_GOLDEN"):
        GOLDEN.mkdir(exist_ok=True)
        shutil.copy(out, golden)
        return
    assert golden.exists(), f"no golden for {name}; create it with MINT_UPDATE_GOLDEN=1 ({golden})"
    mean, outliers, diff = compare(out, golden)
    if mean >= MEAN_TOL or outliers >= OUTLIER_FRAC:
        diff_fn = tmp_path / f"{name}.diff.png"
        diff.point(lambda v: min(255, v * 4)).save(diff_fn)
        pytest.fail(f"{name} differs from {golden}: mean |diff| {mean:.3f} (limit {MEAN_TOL}), "
                    f"{outliers:.2%} of pixels off by more than {OUTLIER_LEVEL} (limit {OUTLIER_FRAC:.1%}). "
                    f"render: {out}  diff: {diff_fn}")

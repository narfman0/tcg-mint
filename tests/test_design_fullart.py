"""The full-art design (mint/designs/fullart.css): golden renders of a creature and a basic land, the same
way tests/test_golden.py does the M15 frame (synthetic cards, dot symbols, 150 dpi), against
tests/golden/design-fullart-*.png. Regenerate after an intentional change:

    MINT_UPDATE_GOLDEN=1 pytest -m render tests/test_design_fullart.py
"""
import base64
import os
import re
import shutil

import pytest
from PIL import Image

from mint import frame
from tests.conftest import synthetic_card
from tests.test_golden import CARDS, DPI, GOLDEN, MEAN_TOL, OUTLIER_FRAC, OUTLIER_LEVEL, DotSymbols, compare

pytest.importorskip("playwright")

# a legendary mythic creature (stamp, P/T, flavour: everything that floats over the art at once; the crown is
# hidden, as on the legendary promos) and a basic land (no plate, the type bar at the foot with the medallion)
FULLART = {
    "creature": CARDS["legend"],
    "basic": dict(name="Proving Ground", type_line="Basic Land — Forest", colors=[], mana_cost="", rarity="common",
                  power=None, toughness=None, oracle_text="({T}: Add {G}.)", flavor_text=None, produced_mana=["G"]),
}


class GlyphSymbols(DotSymbols):
    """The dot with a glyph on it, the way Scryfall's symbols are drawn (the disc first, the glyph's path over
    it), so the medallion has a glyph to mask out: a diamond."""
    SVG = base64.b64encode(b"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 20 20'>"
                           b"<circle cx='10' cy='10' r='9' fill='#c9c1a6' stroke='#000' stroke-width='1'/>"
                           b"<path d='M10 3 L16 10 L10 17 L4 10 Z' fill='#0d0f0f'/></svg>").decode()


@pytest.fixture(scope="module")
def browser():  # test_golden's, again: a module-scoped fixture is not importable, only conftest's are shared
    from mint.browser import Browser
    with Browser(DPI) as b:
        yield b


def render(name, art, tmp_path, browser):
    card = synthetic_card(**FULLART[name])
    fonts_css = frame.local_fonts(tmp_path / "no-workspace-fonts")
    html = frame.build_html(card, symbols=GlyphSymbols(), art_url="file://" + art, theme="wizards", fonts_css=fonts_css,
                            set_size=len(FULLART), maker="tester", year="2026", design="fullart")
    assert 'class="card' in html and " design-fullart" in html
    assert ".design-fullart .art { left: -11px; top: -11px; width: 272px; height: 372px; }" in html
    out = tmp_path / f"design-fullart-{name}.png"
    return out, browser.render(html, out)


def rules(css):
    """(selector, declarations) for each rule of the css, comments stripped."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    return [(sel.strip(), body) for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css)]


def test_the_css_moves_or_hides_m15_pieces_and_leaves_the_bars_outline_alone():
    """The design file moves the art, hides the band, the crown and the window's plate and line, and restyles the
    type bar and the text box (glass on a text card, the medallion on a basic); it never touches the title bar,
    the P/T plate, the stamp or the footer, and never repaints a bar's background -- the outline, caps and bevel
    are template.html's layers over the fill, so the glass comes through the --bar variable alone."""
    css = frame.design_css("fullart")
    assert ".design-fullart .frame" in css and ".design-fullart .pl-art { display: none; }" in css
    assert ".design-fullart .crown-o, .design-fullart .crown { display: none; }" in css
    for sel, body in rules(css):
        assert sel.startswith(".design-fullart"), f"a rule outside the design's class: {sel}"
        last = sel.split()[-1]
        assert last not in (".titlebar", ".pt", ".stamp", ".footer", ".name", ".type", ".cost"), f"restated: {sel}"
        if ".typebar" in sel:
            assert "background" not in body and "border" not in body, f"the bar's own layers repainted: {sel}"


def test_the_medallion_glyph_hook():
    """frame.glyph_uri drops a symbol's disc (the first shape) and leaves the glyph, and a basic's text box carries
    it as --glyph in every design; frame.basic_symbol is the rule render_text's big symbol follows."""
    basic = synthetic_card(**FULLART["basic"])
    assert frame.basic_symbol(basic) == "{G}"
    assert frame.basic_symbol(synthetic_card(type_line="Land — Fixture", oracle_text="({T}: Add {G}.)")) is None
    glyph = frame.glyph_uri(GlyphSymbols().data_uri("{G}"))
    svg = base64.b64decode(glyph.split(",", 1)[1])
    assert b"<circle" not in svg and b"<path d='M10 3" in svg
    assert frame.glyph_uri("data:sym/G") == "data:sym/G"  # a stand-in that is not an SVG passes through
    for design in ("m15", "fullart"):
        html = frame.build_html(basic, symbols=GlyphSymbols(), art_url="", theme="wizards", fonts_css="", set_size=1,
                                maker="t", year="2026", design=design)
        assert f'<div class="textbox " id="text" style="--glyph: url({glyph})"><p class="big-sym">' in html
    html = frame.build_html(synthetic_card(**FULLART["creature"]), symbols=GlyphSymbols(), art_url="", theme="wizards",
                            fonts_css="", set_size=1, maker="t", year="2026")
    assert "--glyph" not in html


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

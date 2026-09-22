"""The retro design (mint/designs/retro.css, the 1997 frame): golden renders of a legendary gold creature, a land
and an artifact, the same way tests/test_golden.py does the M15 frame (synthetic cards, dot symbols, 150 dpi),
against tests/golden/design-retro-*.png. Regenerate after an intentional change:

    MINT_UPDATE_GOLDEN=1 pytest -m render tests/test_design_retro.py
"""
import os
import re
import shutil

import pytest
from PIL import Image

from mint import frame
from tests.conftest import synthetic_card
from tests.test_design_fullart import GlyphSymbols
from tests.test_golden import CARDS, DPI, GOLDEN, MEAN_TOL, OUTLIER_FRAC, OUTLIER_LEVEL, compare

pytest.importorskip("playwright")

# a legendary mythic gold creature (the gold plate with black lettering, a P/T, no crown, no stamp), a land with
# long rules text (the bevelled land box, the fit at work) and an artifact (the brown plate, pips in the title)
RETRO = {"legend": CARDS["legend"], "land": CARDS["land"], "artifact": CARDS["artifact"]}

# the texture table from retro.css, in frame.TEXTURES' terms; the css carries each tile as a data URI
TEXTURES = {
    "W":        ("0.08", 3, 3, ("veins", 0.06, 0.25, 0.3), "#e4dccf", "#baae98"),
    "U":        ("0.04", 3, 5, ("veins", 0.06, -0.3, 0.45), "#6fa0b5", "#2f3d64"),
    "B":        ("0.14", 2, 7, ("veins", 0.05, 0.25, 0.5), "#6e6a68", "#160e0a"),
    "R":        ("0.15", 2, 11, ("veins", 0.04, 0.25, 0.35), "#bd7d70", "#8a3820"),
    "G":        ("0.16 0.05", 2, 13, ("tone", 0, 0, 0.6), "#737b62", "#33351c"),
    "gold":     ("0.02 0.06", 2, 17, ("tone", 0, 0, 1.0), "#dccf98", "#4e3f22"),
    "artifact": ("0.15", 2, 19, ("tone", 0, 0, 0.6), "#8f7d77", "#48311f"),
    "land":     ("0.12", 2, 23, ("tone", 0, 0, 0.6), "#90735e", "#48321f"),
    "C":        ("0.15", 2, 19, ("tone", 0, 0, 0.6), "#8f7d77", "#48311f"),
}


@pytest.fixture(scope="module")
def browser():  # test_golden's, again: a module-scoped fixture is not importable, only conftest's are shared
    from mint.browser import Browser
    with Browser(DPI) as b:
        yield b


def render(name, art, tmp_path, browser):
    card = synthetic_card(**RETRO[name])
    fonts_css = frame.local_fonts(tmp_path / "no-workspace-fonts")
    html = frame.build_html(card, symbols=GlyphSymbols(), art_url="file://" + art, theme="wizards", fonts_css=fonts_css,
                            set_size=len(RETRO), maker="tester", year="2026", design="retro")
    assert 'class="card' in html and " design-retro" in html and f" kind-{frame.frame_kind(card)}" in html
    assert "fonts.googleapis.com" not in html  # the retro faces are local: Almendra is packaged
    assert ".design-retro .art { left: 28.75px; top: 35.05px; width: 192.5px; height: 153.7px; }" in html
    out = tmp_path / f"design-retro-{name}.png"
    return out, browser.render(html, out)


def rules(css):
    """(selector, declarations) for each rule of the css, comments stripped."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    return [(sel.strip(), body) for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css)]


def test_the_css_moves_and_repaints_m15_pieces_inside_its_class():
    """Every rule is scoped by the design's class; the pinline plate, the crown, the stamp, the P/T plate and the
    planeswalker's black plate are hidden, not restyled; the palette is set per kind through the base's variables."""
    css = frame.design_css("retro")
    for sel, _ in rules(css):
        assert sel.startswith(".design-retro"), f"a rule outside the design's class: {sel}"
    assert ".design-retro .pinlines, .design-retro .crown-o, .design-retro .crown { display: none; }" in css
    assert ".design-retro .stamp { display: none; }" in css
    assert ".design-retro .pt .plate { display: none; }" in css
    assert ".design-retro .pw-line { display: none; }" in css
    for kind in frame.FRAMES:
        assert re.search(rf"\.design-retro\.kind-{kind}\b[^{{]*{{ --frame: #[0-9a-f]{{6}}; --box: #[0-9a-f]{{6}};", css), kind
    # the M15 frame is untouched: its page carries none of this
    assert "design-retro" not in frame.build_html(synthetic_card(**CARDS["legend"]), symbols=GlyphSymbols(), art_url="",
                                                  theme="wizards", fonts_css="", set_size=1, maker="t", year="2026")


def test_the_textures_are_texture_uri_tiles_with_the_documented_parameters(monkeypatch):
    """Each kind's --retro-texture is exactly what frame.texture_uri draws from the table in the css's comment
    (kept here as TEXTURES), so the tiles are reproducible and the comment is the truth."""
    css = frame.design_css("retro")
    monkeypatch.setattr(frame, "TEXTURES", TEXTURES)
    for kind in TEXTURES:
        m = re.search(rf'\.design-retro\.kind-{kind} {{ --retro-texture: url\("([^"]+)"\); }}', css)
        assert m, f"no tile for {kind}"
        assert m.group(1) == frame.texture_uri(kind), f"the {kind} tile is not the table's"
    assert ".design-retro .frame::before { background-image: var(--retro-texture); }" in css


def test_the_layouts_that_take_the_design(art):
    """A planeswalker and an adventure render in the design (their rows and adventure box inside the retro text
    box); a saga, a split card and a battle fall back to M15 in build_html, as for every design."""
    for name in ("planeswalker", "adventure"):
        html = frame.build_html(synthetic_card(**CARDS[name]), symbols=GlyphSymbols(), art_url="file://" + art,
                                theme="wizards", fonts_css="", set_size=1, maker="t", year="2026", design="retro")
        assert " design-retro" in html
    for name in ("saga", "split"):
        html = frame.build_html(synthetic_card(**CARDS[name]), symbols=GlyphSymbols(), art_url="file://" + art,
                                theme="wizards", fonts_css="", set_size=1, maker="t", year="2026", design="retro")
        assert " design-m15" in html and "design-retro" not in html


@pytest.mark.render
@pytest.mark.parametrize("name", list(RETRO))
def test_golden_retro(name, art, tmp_path, browser):
    out, sizes = render(name, art, tmp_path, browser)
    assert Image.open(out).size == (408, 558)
    assert sizes["name"] == 14  # no name needed shrinking in the title's 190 units
    golden = GOLDEN / f"design-retro-{name}.png"
    if os.environ.get("MINT_UPDATE_GOLDEN"):
        GOLDEN.mkdir(exist_ok=True)
        shutil.copy(out, golden)
        return
    assert golden.exists(), f"no golden for {name}; create it with MINT_UPDATE_GOLDEN=1 ({golden})"
    mean, outliers, diff = compare(out, golden)
    if mean >= MEAN_TOL or outliers >= OUTLIER_FRAC:
        diff_fn = tmp_path / f"design-retro-{name}.diff.png"
        diff.point(lambda v: min(255, v * 4)).save(diff_fn)
        pytest.fail(f"{name} differs from {golden}: mean |diff| {mean:.3f} (limit {MEAN_TOL}), "
                    f"{outliers:.2%} of pixels off by more than {OUTLIER_LEVEL} (limit {OUTLIER_FRAC:.1%}). "
                    f"render: {out}  diff: {diff_fn}")

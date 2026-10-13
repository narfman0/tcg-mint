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
    # the other layouts: a planeswalker, a saga, an adventure and a split card, all made up
    "planeswalker": dict(name="Fixture, Who Waits", type_line="Legendary Planeswalker — Fixture", colors=["W"],
                         mana_cost="{2}{W}", rarity="mythic", power=None, toughness=None, loyalty="4", flavor_text=None,
                         oracle_text="Each opponent can't attack you with more than one creature each turn.\n"
                                     "+1: You gain 2 life.\n−3: Exile target creature. (It goes.)\n−7: You get an emblem."),
    "saga": dict(name="The Fixing of the Fixture", type_line="Enchantment — Saga", colors=["B"], mana_cost="{2}{B}",
                 rarity="rare", power=None, toughness=None, flavor_text=None,
                 oracle_text="(As this Saga enters and after your draw step, add a lore counter. Sacrifice after III.)\n"
                             "I — Each opponent discards a card.\nII — Each opponent loses 2 life.\n"
                             "III — Return target creature card from your graveyard to the battlefield."),
    "adventure": dict(name="Fixture Knight // Fix It", type_line="Creature — Fixture Knight // Instant — Adventure", colors=["G"],
                      mana_cost="{2}{G}", rarity="uncommon", power="3", toughness="3", layout="adventure", oracle_text="Trample",
                      flavor_text="A knight, and a plan.",
                      card_faces=[dict(name="Fixture Knight", type_line="Creature — Fixture Knight", mana_cost="{2}{G}",
                                       oracle_text="Trample"),
                                  dict(name="Fix It", type_line="Instant — Adventure", mana_cost="{G}",
                                       oracle_text="Destroy target artifact. (Then exile this card. You may cast the creature "
                                                   "later from exile.)")]),
    "split": dict(name="Fix // Fixture", type_line="Instant // Sorcery", colors=["R", "U"], mana_cost="{1}{R} // {2}{U}",
                  rarity="uncommon", power=None, toughness=None, layout="split", oracle_text="", flavor_text=None,
                  card_faces=[dict(name="Fix", type_line="Instant", mana_cost="{1}{R}",
                                   oracle_text="Fix deals 2 damage to any target."),
                              dict(name="Fixture", type_line="Sorcery", mana_cost="{2}{U}", oracle_text="Draw two cards.")]),
    # the double-faced cards, each face with the other in hand (_other): a transform pair wears the plain badges, the
    # front a ghost of the back's P/T and the back its colour indicator; a modal pair the teardrops and the foot strips
    "transform": dict(name="Fixture Delver", type_line="Creature — Fixture", colors=["U"], mana_cost="{U}", rarity="common",
                      power="1", toughness="1", layout="transform", face_index=0, flavor_text=None,
                      oracle_text="At the beginning of your upkeep, look at the top card of your library.",
                      _other=dict(name="Fixture Aberration", type_line="Creature — Fixture Insect", power="3", toughness="2")),
    "transform-back": dict(name="Fixture Aberration", type_line="Creature — Fixture Insect", colors=["U"], mana_cost="",
                           rarity="common", power="3", toughness="2", layout="transform", face_index=1,
                           color_indicator=["U"], oracle_text="Flying", flavor_text="The fixture is out.",
                           _other=dict(name="Fixture Delver", type_line="Creature — Fixture", mana_cost="{U}", power="1",
                                       toughness="1")),
    "modal": dict(name="Fixture's Awakening", type_line="Sorcery", colors=["G"], mana_cost="{2}{G}", rarity="rare",
                  power=None, toughness=None, layout="modal_dfc", face_index=0, flavor_text="Wake up.",
                  oracle_text="Return target creature card from your graveyard to your hand.",
                  _other=dict(name="Fixture Grove", type_line="Land", colors=[], mana_cost="", face_index=1,
                              oracle_text="As this land enters, you may pay 3 life.\n{T}: Add {G}.", produced_mana=["G"])),
    "modal-back": dict(name="Fixture Grove", type_line="Land", colors=[], mana_cost="", rarity="rare", power=None,
                       toughness=None, layout="modal_dfc", face_index=1, flavor_text=None, produced_mana=["G"],
                       oracle_text="As this land enters, you may pay 3 life. If you don't, it enters tapped.\n{T}: Add {G}.",
                       _other=dict(name="Fixture's Awakening", type_line="Sorcery", colors=["G"], mana_cost="{2}{G}",
                                   face_index=0, oracle_text="Return target creature card.")),
    "battle": dict(name="Invasion of the Fixture", type_line="Battle — Siege", colors=["W", "B"], mana_cost="{2}{W}{B}",
                   rarity="rare", power=None, toughness=None, defense="5", layout="transform", face_index=0, flavor_text=None,
                   oracle_text="(As a Siege enters, choose an opponent to protect it. You and others can attack it. When "
                               "it's defeated, exile it, then cast it transformed.)\nWhen this Siege enters, draw a card.",
                   _other=dict(name="The Fixed Sky", type_line="Enchantment", colors=["W", "B"], mana_cost="")),
}


@pytest.fixture(scope="module")
def browser():
    from mint.browser import Browser
    with Browser(DPI) as b:
        yield b


def render(name, art, tmp_path, browser):
    spec = dict(CARDS[name])
    other = spec.pop("_other", None)
    card = synthetic_card(**spec)
    fonts_css = frame.local_fonts(tmp_path / "no-workspace-fonts")  # only the packaged faces, never the user's
    html = frame.build_html(card, symbols=DotSymbols(), art_url="file://" + art, theme="wizards", fonts_css=fonts_css,
                            set_size=len(CARDS), maker="tester", year="2026", other_face=other)
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
    base = {"planeswalker": 8.8, "saga": 11, "battle": 9.6}.get(name, 12.6)  # these layouts set their text smaller to begin with
    if name == "land":
        assert frame.TEXT_FLOOR <= sizes["text"] < 12.6  # the long text was shrunk to fit
    else:
        assert sizes["text"] == base
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

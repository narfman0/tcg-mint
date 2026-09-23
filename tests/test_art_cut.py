"""The scan cut: the picture a design's own printing carries, taken off the full-card scan.

Scryfall's art_crop is the M15 window whatever the printing is, so a textless promo -- whose picture
runs the height of the card -- can only give us its art this way (todo/frame-designs.md, phase 5).
"""
import pytest
from PIL import Image

from mint import frame, sets
from mint.art import Art, cut_base, cut_hash, is_cut
from mint.errors import MintError
from tests.conftest import synthetic_card
from tests.test_art import make

SET = {"code": "TST", "name": "t", "design": "textless", "style": {"name": "ink", "prompt": "pen and ink"},
       "cards": {"Test Subject": {"number": 1}}}


def textless(**over):
    """A printing Scryfall marks textless -- the one whose scan carries more than the crop."""
    return synthetic_card(textless=True, **over)


def scanned(art, card, size=(745, 1040)):
    """Stand in for Scryfall's scan. Every pixel says where it is (x and y in its red and green),
    so what came out of a cut can be checked against the rectangle that was asked for."""
    im = Image.new("RGB", size)
    px = im.load()
    for y in range(size[1]):
        for x in range(size[0]):
            px[x, y] = (x % 256, y % 256, 0)
    fn = art.scan(card, fetch=False)
    fn.parent.mkdir(parents=True, exist_ok=True)
    im.save(fn)
    return fn


def test_every_design_says_where_its_art_sits():
    assert set(frame.ART_ORIGIN) == set(frame.DESIGNS)
    for d in frame.DESIGNS:
        x, y, w, h = frame.art_rect(d)
        assert (w, h) == frame.DESIGNS[d][:2]  # the size is DESIGNS', never restated
        assert x >= -11 and y >= -11           # the page is the card plus 11 units of bleed each way


def test_only_a_design_the_crop_cannot_serve_has_a_cut():
    # the two designs whose printings carry picture the crop has never had, and nothing else. fullart is
    # the one that looks like it belongs here: Scryfall crops its basics tall by itself, and on its other
    # kinds everything past the crop is under printed text (SCAN_CUT's comment holds the numbers)
    assert set(frame.SCAN_CUT) == {"textless", "extended"}
    for d in ("m15", "borderless", "fullart", "modern", "retro"):
        assert frame.scan_cut(d) is None, f"{d} has a cut nobody measured"
    assert frame.scan_cut(None) is None
    assert frame.scan_cut("textless") == (19.6, 39.6, 210.6, 281.0)  # each design's own css header
    assert frame.scan_cut("extended") == (0, 39.7, 250, 156.6)
    off = lambda d, aspect: abs(aspect / frame.art_aspect(d) - 1)  # noqa: E731 - how hard `cover` cuts
    for d, (x, y, w, h) in frame.SCAN_CUT.items():
        assert 0 <= x and x + w <= 250 and 0 <= y and y + h <= 350, f"{d}'s cut leaves the card face"
        # both beat the crop: a shape closer to the design, more picture, or both
        assert off(d, w / h) < off(d, frame.art_aspect("m15")) or w > frame.DESIGNS["m15"][0], d
    # textless is the loud case -- the crop is half that picture -- and extended the quiet one: near
    # enough in shape, but 250 units of picture across against the window's 210.6
    assert not frame.fits("textless", frame.art_aspect("m15"))
    assert frame.fits("extended", frame.art_aspect("m15"))
    assert frame.scan_cut("extended")[2] > frame.DESIGNS["m15"][0]


def test_a_cut_is_only_for_a_printing_of_that_design(tmp_path):
    art = Art(tmp_path)
    assert art.cut_for(textless(), "textless") == "textless"
    assert art.cut_for(synthetic_card(), "textless") is None  # a plain printing's scan has no more picture
    assert art.cut_for(textless(), "m15") is None             # the crop already is that window
    assert art.cut_for(textless(), None) is None
    assert art.cut(synthetic_card(), "m15") is None
    ext = synthetic_card(frame_effects=["extendedart"])
    assert art.cut_for(ext, "extended") == "extended"
    assert art.cut_for(ext, "textless") is None               # the printing is not one


def test_a_full_art_printing_keeps_its_crop(tmp_path):
    """The design that looks like it wants a cut and does not: Scryfall crops a full-art basic tall on
    its own (0.838:1 against the window's 0.731, six measured), which beats any rectangle of clean
    picture the card has, and its other kinds hide the rest of their art under printed text."""
    art = Art(tmp_path)
    basic = synthetic_card(full_art=True, type_line="Basic Land — Forest", name="Forest")
    other = synthetic_card(full_art=True, type_line="Creature — Elf Druid")
    assert frame.printed_design(basic) == "fullart" and frame.printed_design(other) == "fullart"
    assert art.cut_for(basic, "fullart") is None and art.cut_for(other, "fullart") is None
    assert art.cut(basic, "fullart", fetch=False) is None


def test_the_cut_comes_off_the_scan_at_the_measured_rectangle(tmp_path):
    art = Art(tmp_path)
    card = textless()
    scanned(art, card)
    fn = art.cut(card, "textless")
    assert fn.name == "cut_textless_" + card["illustration_id"] + ".png"
    ppu = 745 / 250  # the scan is the bare card, 250 units across: calibrate.py's convention
    x, y, w, h = frame.scan_cut("textless")
    left, top = round(x * ppu), round(y * ppu)
    with Image.open(fn) as im:
        assert im.size == (round((x + w) * ppu) - left, round((y + h) * ppu) - top)
        assert im.getpixel((0, 0)) == (left % 256, top % 256, 0)  # it starts where it was told to
    assert frame.fits("textless", im.width / im.height)
    before = fn.stat().st_mtime_ns
    assert art.cut(card, "textless") == fn and fn.stat().st_mtime_ns == before  # cached, not re-cut
    assert art.cut(textless(illustration_id="11111111-1111-1111-1111-111111111111"),
                   "textless", fetch=False).name.endswith("111111.png")  # a path without going to Scryfall


def test_resolve_renders_a_textless_card_from_its_cut(tmp_path):
    art = Art(tmp_path)
    card = textless()
    art.crop(card, fetch=False).write_bytes(b"jpg")
    scanned(art, card)
    assert art.resolve(card).kind == "crop"                 # no design named: nothing moves
    assert art.resolve(card, design="m15").kind == "crop"
    s = art.resolve(card, design="textless")
    assert s.kind == "cut" and s.label == "textless" and s.describe() == "cut textless"
    assert s.path == art.cut(card, "textless")
    assert s.hash == cut_hash("textless")  # not a variant, but it has a name the stale check can hold
    # a plain printing in the same design keeps the crop: there is nothing else to have
    assert art.resolve(synthetic_card(), design="textless").kind == "crop"


def test_resolve_takes_the_enhance_of_the_cut_not_of_the_crop(tmp_path):
    art = Art(tmp_path)
    card = textless()
    art.crop(card, fetch=False).write_bytes(b"jpg")
    scanned(art, card)
    of_crop = make(art, card, "enhance", "enhance", "crop", {"model": "m", "base": "crop"})
    assert art.resolve(card).hash == of_crop.hash                  # m15 still enhances off the crop
    assert art.resolve(card, design="textless").kind == "cut"      # but that is the wrong picture here
    recipe = {"model": "m", "base": cut_base("textless")}
    of_cut = make(art, card, "enhance", "enhance", cut_base("textless"), recipe)
    got = art.resolve(card, design="textless")
    assert got.kind == "enhance" and got.hash == of_cut.hash


def test_the_base_vocabulary(tmp_path):
    art = Art(tmp_path)
    card = textless()
    scanned(art, card)
    assert is_cut("cut") and is_cut("cut:textless")
    assert not any(is_cut(b) for b in ("crop", "none", "cutlery", "deadbeef", ""))
    assert not sets.is_label("cut:textless")  # a label means "this card's newest variant so named"
    assert art.base_path(card, "cut:textless") == art.cut(card, "textless")
    assert art.base_path(card, "cut", design="textless") == art.cut(card, "textless")
    with pytest.raises(MintError, match="needs the design"):
        art.base_path(card, "cut")
    with pytest.raises(MintError, match="no scan cut measured"):
        art.base_path(card, "cut:m15")


def test_a_set_starts_its_restyles_and_clips_from_the_cut():
    st = sets.from_dict(SET)
    card, plain = textless(), synthetic_card()
    assert st.design_of(card) == "textless"
    assert st.recipe(card)["base"] == "cut:textless"
    assert st.recipe(plain)["base"] == "crop"  # the same set: this printing has no more picture
    r = st.recipe(card)
    assert r["height"] > r["width"]            # and the size follows the design, as the picture does
    assert st.motion_recipe(card)["base"] == "cut:textless"
    # a base spelled out in the file is left alone
    assert sets.from_dict({**SET, "base": "ink"}).recipe(card)["base"] == "ink"
    assert sets.from_dict({**SET, "design": "m15"}).recipe(card)["base"] == "crop"
    # a bare "cut" is spelled out into the design it means, even one with no cut, so base_path says why
    assert sets.from_dict({**SET, "base": "cut"}).recipe(card)["base"] == "cut:textless"
    assert sets.from_dict({**SET, "design": "m15", "base": "cut"}).recipe(card)["base"] == "cut:m15"


def test_the_stale_check_agrees_with_the_render_without_fetching(tmp_path):
    """want_hashes must answer what the render will use, whether or not the file is cut yet: the
    decision is the card's design, not what happens to be on disk."""
    from mint import renders
    art = Art(tmp_path)
    st = sets.from_dict(SET)
    card = textless()
    want = renders.want_hashes(st, card, art)
    assert want["plain"] == cut_hash("textless")
    assert not art.cut(card, "textless", fetch=False).exists()  # nothing was fetched to answer it

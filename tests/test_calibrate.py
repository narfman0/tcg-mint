"""The band finder behind `mint calibrate --design`: edges at the half-way point of a step."""
import pytest
from PIL import Image

from mint import calibrate, frame


def stepped(values, height=350, width=250, scale=3):
    """A card-shaped grey image with horizontal bands: [(until_card_unit, grey), ...]."""
    im = Image.new("L", (width * scale, height * scale))
    px = im.load()
    for y in range(im.height):
        u = y / scale
        grey = next(g for until, g in values if u < until)
        for x in range(im.width):
            px[x, y] = grey
    return im


def test_an_edge_lands_on_the_half_way_point():
    """A clean step from 40 to 200 halfway through: the edge is the crossing, not the sample before
    or after it."""
    prof = [40.0] * 20 + [200.0] * 20
    assert calibrate.edges(prof) == pytest.approx([19.5], abs=0.6)
    # a ramp over four samples: still the half-way point, in the middle of the ramp
    prof = [40.0] * 20 + [72.0, 104.0, 136.0, 168.0] + [200.0] * 20
    assert calibrate.edges(prof) == pytest.approx([21.5], abs=1.0)
    assert calibrate.edges([50.0] * 40) == []          # no step, no edge
    assert calibrate.edges([1.0, 2.0]) == []           # too short to judge


def test_bands_are_reported_in_card_units():
    """Three bands with boundaries at 40 and 210 card units come back as 40 and 210, whatever the
    image's resolution."""
    for scale in (2, 3, 5):
        im = stepped([(40, 30), (210, 220), (350, 30)], scale=scale)
        got = calibrate.bands(im, 0, 0, scale, axis="y")
        assert got == pytest.approx([40, 210], abs=1.0), scale


def test_bleed_is_taken_off_the_offset():
    """Our renders carry 11 units of bleed; a band 40 units down the card is 51 down the file, and
    has to be reported as 40 so it compares with a scan."""
    scale = 3
    im = Image.new("L", (272 * scale, 372 * scale))
    px = im.load()
    for y in range(im.height):
        for x in range(im.width):
            px[x, y] = 30 if (y / scale - 11) < 40 else 220
    assert calibrate.bands(im, 11 * scale, 11 * scale, scale, axis="y") == pytest.approx([40], abs=1.0)


def test_edges_across_the_card_too():
    scale = 3
    im = Image.new("L", (250 * scale, 350 * scale))
    px = im.load()
    for y in range(im.height):
        for x in range(im.width):
            px[x, y] = 220 if 20 <= x / scale < 230 else 30
    assert calibrate.bands(im, 0, 0, scale, axis="x") == pytest.approx([20, 230], abs=1.0)


def test_pairing_ours_against_real():
    matched, missed = calibrate.pair([10.0, 40.2, 99.0], [9.8, 40.0, 210.0])
    assert matched == [(10.0, 9.8), (40.2, 40.0), (99.0, None)]   # 99 is nowhere near a real edge
    assert missed == [210.0]                                      # and nothing of ours found 210
    # each real edge is claimed once, by whichever of ours is nearest
    matched, missed = calibrate.pair([40.0, 41.0], [40.5])
    assert matched == [(40.0, 40.5), (41.0, None)] and missed == []


def test_an_unknown_design_is_refused(tmp_path):
    from mint.errors import MintError
    from mint.workspace import Workspace
    ws = Workspace(tmp_path, tmp_path / "cards.jsonl")
    with pytest.raises(MintError, match="design is one of"):
        calibrate.calibrate_design(ws, "showcase", [], tmp_path)
    assert "retro" in frame.DESIGNS and "m15" in frame.DESIGNS


@pytest.mark.render
def test_the_band_finder_lands_on_the_art_window_of_a_real_render(tmp_path, art):
    """The proof that this measures anything: run it on our own render and the art rectangle it
    finds is the one frame.DESIGNS declares, to within a card unit."""
    from mint.browser import Browser
    from tests.conftest import synthetic_card
    from tests.test_frame import NoSymbols

    html = frame.build_html(synthetic_card(), symbols=NoSymbols(), art_url="file://" + art, design="m15")
    out = tmp_path / "m15.png"
    with Browser(300) as b:
        b.render(html, out)
    im = Image.open(out).convert("L")
    ppu = im.width / 272
    down = calibrate.bands(im, 11 * ppu, 11 * ppu, ppu, axis="y")
    across = calibrate.bands(im, 11 * ppu, 11 * ppu, ppu, axis="x")
    nearest = lambda got, want: min(got, key=lambda v: abs(v - want))

    # the template puts the art window at left 19.6, top 39.7, 210.6 x 154
    assert nearest(down, 39.7) == pytest.approx(39.7, abs=1.5)
    assert nearest(down, 193.7) == pytest.approx(193.7, abs=1.5)
    assert nearest(across, 19.6) == pytest.approx(19.6, abs=1.5)
    assert nearest(across, 230.2) == pytest.approx(230.2, abs=1.5)
    aw, ah, _ = frame.DESIGNS["m15"]
    assert nearest(across, 230.2) - nearest(across, 19.6) == pytest.approx(aw, abs=2)
    assert nearest(down, 193.7) - nearest(down, 39.7) == pytest.approx(ah, abs=2)

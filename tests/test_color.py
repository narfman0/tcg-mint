"""Colour matching: a drifted picture's palette moves to the reference's, by the knob's strength."""
from PIL import Image, ImageStat

from mint import color


def test_match_moves_the_means_and_strength_blends():
    ref = Image.new("RGB", (40, 40), (200, 40, 40))       # a red reference
    drifted = Image.new("RGB", (40, 40), (120, 110, 100))  # gone brown-grey
    full = color.match(drifted, ref, 1.0)
    assert ImageStat.Stat(full).mean[0] > 180 and ImageStat.Stat(full).mean[1] < 60
    none = color.match(drifted, ref, 0.0)
    assert ImageStat.Stat(none).mean == [120, 110, 100]
    half = color.match(drifted, ref, 0.5)
    assert 120 < ImageStat.Stat(half).mean[0] < ImageStat.Stat(full).mean[0]


def test_match_file_writes_in_place(tmp_path):
    p = tmp_path / "x.png"
    Image.new("RGB", (8, 8), (10, 10, 10)).save(p)
    ref = tmp_path / "r.png"
    Image.new("RGB", (8, 8), (200, 200, 200)).save(ref)
    color.match_file(p, ref, 1.0)
    assert ImageStat.Stat(Image.open(p)).mean[0] > 150

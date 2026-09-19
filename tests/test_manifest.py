from mint.art import ArtSource
from mint.manifest import Manifest
from mint.render import Rendered


def test_manifest_merges_and_saves(tmp_path):
    m = Manifest(tmp_path)
    r = Rendered("Alpha", 1, "wizards", str(tmp_path / "001_Alpha.png"), ArtSource(tmp_path / "a.jpg", "crop"),
                 {"text": 7.5, "name": 13.5}, None, ["warn"])
    m.add(r, set_code="TST", fhash="abcd1234")
    m.save()
    m2 = Manifest(tmp_path)
    e = m2.entries["001_Alpha.png"]
    assert e["card"] == "Alpha" and e["shrunk"] is True and e["source"]["kind"] == "crop" and e["warnings"] == ["warn"]
    m2.add(Rendered("Beta", 2, "wizards", str(tmp_path / "002_Beta.png"), ArtSource(tmp_path / "b.jpg", "crop")))
    m2.save()
    assert set(Manifest(tmp_path).entries) == {"001_Alpha.png", "002_Beta.png"}

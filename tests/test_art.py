"""Variants and the resolve() decision, on a temporary art directory."""
from mint import sets
from mint.art import Art
from tests.conftest import synthetic_card


def make(art, card, label, kind, base, recipe):
    v = art.new_variant(card, label, kind, recipe, base, sets.recipe_hash(recipe))
    v.path.parent.mkdir(parents=True, exist_ok=True)
    v.path.write_bytes(b"png")
    return art.record(v)


def test_resolve_precedence(tmp_path):
    art = Art(tmp_path)
    card = synthetic_card()
    art.crop(card, fetch=False).write_bytes(b"jpg")  # pretend the crop is cached
    assert art.resolve(card).kind == "crop"
    assert art.resolve(card, override="/x/mine.png").kind == "override"

    enh = make(art, card, "enhance", "enhance", "crop", {"model": "m", "base": "crop"})
    assert art.resolve(card).kind == "enhance" and art.resolve(card).hash == enh.hash
    assert art.resolve(card, enhance=False).kind == "crop"

    styled = make(art, card, "ink", "restyle", "crop", {"prompt": "x", "base": "crop"})
    s = art.resolve(card, style_hash=styled.hash)
    assert s.kind == "styled" and s.hash == styled.hash
    assert art.resolve(card, style_hash="00000000").kind == "enhance"  # unknown style: fall through

    enh2 = make(art, card, "enhance", "enhance", styled.hash, {"model": "m", "base": styled.hash})
    s = art.resolve(card, style_hash=styled.hash)
    assert s.kind == "styled" and s.hash == enh2.hash and s.variant.base == styled.hash

    assert {v.hash for v in art.variants(card)} == {enh.hash, styled.hash, enh2.hash}
    assert art.base_path(card, styled.hash) == styled.path
    assert art.base_path(card, "crop") == art.crop(card, fetch=False)


def test_variants_ignore_broken_sidecars(tmp_path):
    art = Art(tmp_path)
    card = synthetic_card()
    d = art.variant_dir(card)
    d.mkdir(parents=True)
    (d / "ink-deadbeef.json").write_text("{not json")
    (d / "ink-cafebabe.json").write_text('{"label": "ink"}')  # missing fields
    assert art.variants(card) == []


def test_a_crop_wanted_twice_at_once_is_fetched_once(tmp_path, monkeypatch):
    """The printing picker asks for the default printing's crop twice in one breath: one download,
    both callers get the whole file, and no .part is left behind."""
    import io
    import threading
    import time

    from mint import scryfall

    opened = []

    class Slow(io.BytesIO):
        def read(self, n=-1):
            time.sleep(0.05)  # long enough for the second caller to arrive mid-download
            return super().read(n)

    def _open(url, timeout):
        opened.append(url)
        return Slow(b"jpeg bytes " * 1000)
    monkeypatch.setattr(scryfall, "_open", _open)
    dest = tmp_path / "art" / "abc.jpg"
    got = []
    ts = [threading.Thread(target=lambda: got.append(scryfall.fetch("https://x/abc.jpg", dest))) for _ in range(3)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert opened == ["https://x/abc.jpg"] and got == [str(dest)] * 3
    assert dest.read_bytes() == b"jpeg bytes " * 1000 and list(dest.parent.iterdir()) == [dest]

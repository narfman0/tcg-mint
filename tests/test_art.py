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

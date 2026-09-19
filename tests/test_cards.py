"""The card index over a tiny synthetic bulk file."""
import json

import pytest

from mint.cards import Cards, front_face
from mint.errors import CardNotFound
from tests.conftest import synthetic_card


@pytest.fixture
def bulk(tmp_path):
    fn = tmp_path / "cards.jsonl"
    rows = [
        synthetic_card(name="Alpha", set="aaa", collector_number="1", released_at="2020-01-01"),
        synthetic_card(name="Alpha", set="spm", collector_number="9", released_at="2025-01-01", security_stamp="triangle"),
        synthetic_card(name="Alpha", layout="art_series", set="aaa", collector_number="A1", released_at="2026-01-01"),
        {"name": "Front // Back", "layout": "transform", "set": "dfc", "collector_number": "3", "released_at": "2021-01-01",
         "card_faces": [{"object": "card_face", "name": "Front", "type_line": "Creature", "illustration_id": "f-1",
                         "image_uris": {"art_crop": "x"}}, {"object": "card_face", "name": "Back"}]},
    ]
    fn.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return fn


def test_index_and_lookup(bulk):
    c = Cards(bulk)
    assert c.count() == 4
    assert c.find("alpha")["set"] == "aaa"            # newest non-crossover printing
    assert c.find("Alpha", printing="spm:9")["set"] == "spm"
    assert [p["set"] for p in c.printings("Alpha")] == ["spm", "aaa"]  # art series excluded, newest first
    with pytest.raises(CardNotFound):
        c.find("Omega")
    with pytest.raises(CardNotFound):
        c.find("Alpha", printing="zzz:1")


def test_front_face(bulk):
    c = Cards(bulk)
    card = c.find("Front")
    assert card["name"] == "Front" and card["full_name"] == "Front // Back" and card["illustration_id"] == "f-1"
    assert c.by_illustration("f-1")["name"] == "Front"
    assert front_face(synthetic_card())["name"] == "Test Subject"


def test_index_rebuilds_when_file_changes(bulk):
    c = Cards(bulk)
    assert c.count() == 4
    with open(bulk, "a") as f:
        f.write(json.dumps(synthetic_card(name="Beta")) + "\n")
    import os
    os.utime(bulk, (0, 10**9))  # make sure mtime differs
    c2 = Cards(bulk)
    assert c2.count() == 5 and c2.find("Beta")["name"] == "Beta"


def test_default_printing_is_the_newest_plain_one():
    from mint.cards import default_printing, oddness
    plain = lambda **o: {"name": "X", "illustration_id": "i", "set_type": "expansion", "border_color": "black",
                         "lang": "en", "released_at": "2020-01-01", "collector_number": "10", **o}
    lair = plain(set="sld", set_type="box", border_color="borderless", frame_effects=["inverted"], released_at="2026-01-01")
    promo = plain(set="prm", set_type="promo", promo=True, digital=True, released_at="2025-01-01")
    unreleased = plain(set="zzz", released_at="2999-01-01")
    variant = plain(set="cmm", collector_number="509", frame_effects=["showcase"], released_at="2023-01-01")
    regular = plain(set="cmm", collector_number="150", released_at="2023-01-01")
    older = plain(set="rtr", released_at="2012-01-01")
    assert oddness(regular) == (0, []) and oddness(older) == (0, [])
    assert oddness(lair)[0] > oddness(variant)[0] > 0
    assert "digital" in oddness(promo)[1] and "unreleased" in oddness(unreleased)[1]
    cands = [unreleased, lair, promo, variant, regular, older]  # newest first, as printings() returns them
    assert default_printing(cands) is regular
    assert default_printing([lair, promo]) is lair  # only odd ones on file: the least odd still wins
    assert default_printing([]) is None

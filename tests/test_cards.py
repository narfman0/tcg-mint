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

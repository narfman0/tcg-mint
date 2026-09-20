"""`mint describe`: a vision model's answer becomes a card's subject line, and a `new` scene from it."""
import json

import pytest

from mint import describe, sets, workspace
from mint.art import Art
from mint.describe import Describer, describe_card, facts, parse
from mint.errors import MintError
from tests.conftest import synthetic_card

ANSWER = ('Here you go:\n{"description": "A tall  armoured figure holds a lantern in a flooded crypt.",'
          ' "subject": "an armoured knight with a brass lantern,  wading through a flooded crypt, raising the dead."}')


def test_parse_takes_the_json_out_of_prose_and_tidies_it():
    d = parse(ANSWER)
    assert d["description"] == "A tall armoured figure holds a lantern in a flooded crypt."
    assert d["subject"] == "an armoured knight with a brass lantern, wading through a flooded crypt, raising the dead"
    with pytest.raises(MintError, match="no subject line"):
        parse("I cannot see the image.")
    with pytest.raises(MintError, match="no subject line"):
        parse('{"description": "x", "subject": "  "}')


def test_facts_carry_the_card_and_the_entry(card):
    entry = sets.CardEntry(flavor="Mine.", subject="a fixture")
    f = facts(card, entry)
    assert "Name: Test Subject" in f and "Type: Creature — Fixture" in f
    assert "Text: Flying / When this enters" in f and "Flavor: Mine." in f and "Power/toughness: 2/3" in f
    assert f.endswith("Current subject line: a fixture")
    assert "Flavor: A *fixture* speaks." in facts(card)  # the printed flavor when the entry has none


def test_ready_needs_a_key_for_claude_and_nothing_for_ollama(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    ok, why = Describer("claude").ready()
    assert not ok and "ANTHROPIC_API_KEY" in why
    assert Describer("claude", key="k").ready() == (True, "")
    assert Describer("ollama", url="http://box:1/").ready() == (True, "") and Describer("ollama", url="http://box:1/").url == "http://box:1"
    with pytest.raises(MintError, match="describer must be one of"):
        Describer("gpt")
    with pytest.raises(MintError, match="not set up"):
        Describer("claude").describe("x.png", synthetic_card())


def test_describe_card_writes_the_reading_beside_the_image(tmp_path, art, card, monkeypatch):
    a = Art(tmp_path / "art")
    a.dir.mkdir()
    (a.dir / (card["illustration_id"] + ".jpg")).write_bytes(open(art, "rb").read())
    asked = {}

    def fake_ask(self, data, mime_type, text):
        asked.update(mime=mime_type, text=text, size=len(data))
        return ANSWER
    monkeypatch.setattr(Describer, "_ask", fake_ask)
    st = sets.from_dict({"code": "TST", "cards": {card["name"]: {"number": 1}}})
    d = describe_card(Describer("claude", key="k", model="m"), a, card, st)
    assert asked["mime"] == "image/jpeg" and asked["size"] > 0 and "Name: Test Subject" in asked["text"]
    assert d["subject"].startswith("an armoured knight") and d["model"] == "claude:m" and d["base"] == "crop" and d["created"]
    assert a.described(card) == d
    assert a.variants(card) == []  # described.json is not a variant
    assert (a.dir / card["illustration_id"] / "described.json").exists()


def test_a_one_off_new_remix_names_a_new_variant(card):
    st = sets.from_dict({"code": "TST", "style": {"name": "look", "prompt": "oil on canvas", "remix": "restyle"},
                         "cards": {card["name"]: {"subject": "a knight", "remix": "repose"}}})
    r = st.recipe(card, remix="new")
    assert r["remix"] == "new" and r["base"] == "none" and r["prompt"] == "a knight, oil on canvas"
    assert "repose_strength" not in r
    assert st.recipe(card)["remix"] == "repose"  # the entry's own mode, untouched
    assert sets.recipe_hash(r) != sets.recipe_hash(st.recipe(card))


def test_cli_writes_subjects_and_keeps_hand_written_ones(tmp_path, art, card, monkeypatch, capsys):
    monkeypatch.setenv("MINT_HOME", str(tmp_path))
    monkeypatch.delenv("MINT_CARDS", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.setattr(workspace, "_default", None)
    ws = workspace.default()
    ws.cards_file.write_text(json.dumps(card) + "\n" + json.dumps(synthetic_card(name="Other", illustration_id="1" * 36)) + "\n")
    ws.art.mkdir()
    for c in (card, synthetic_card(name="Other", illustration_id="1" * 36)):
        (ws.art / (c["illustration_id"] + ".jpg")).write_bytes(open(art, "rb").read())
    ws.sets.mkdir()
    sets.save(ws.sets / "tst.json", sets.from_dict({"code": "TST", "cards": {card["name"]: {"number": 1},
                                                                            "Other": {"number": 2, "subject": "by hand"}}}))
    monkeypatch.setattr(Describer, "_ask", lambda self, data, mime_type, text: ANSWER)
    describe.main(["--set", str(ws.sets / "tst.json")])
    out = capsys.readouterr().out
    assert "described Test Subject: an armoured knight" in out and "kept      Other: by hand" in out
    st = sets.load(ws.sets / "tst.json")
    assert st.cards[card["name"]].subject.startswith("an armoured knight") and st.cards["Other"].subject == "by hand"
    assert st.cards[card["name"]].number == 1  # the rest of the entry survives
    describe.main(["--set", str(ws.sets / "tst.json"), "--force", "Other"])
    assert sets.load(ws.sets / "tst.json").cards["Other"].subject.startswith("an armoured knight")

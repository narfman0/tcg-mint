"""The set schema: strict keys, round trips, recipes and their hashes."""
import pytest

from mint import sets
from mint.errors import SetError

BASE = {"code": "TST", "name": "t", "style": {"name": "ink", "prompt": "pen and ink"},
        "cards": {"Alpha": {"number": 1, "subject": "a dog"}, "Beta": {"number": 2}}}


def test_round_trip_keeps_only_what_was_set(tmp_path):
    st = sets.from_dict(BASE)
    d = st.to_dict()
    assert d["cards"] == BASE["cards"]
    assert d["style"] == {"name": "ink", "prompt": "pen and ink"}  # defaults are not written out...
    st.style.denoise = 0.9
    assert st.to_dict()["style"]["denoise"] == 0.9                 # ...changes are
    spelled = sets.from_dict({**BASE, "style": {**BASE["style"], "control": "canny"}})
    assert spelled.to_dict()["style"]["control"] == "canny"        # ...and so is anything the file spelled out
    st.style.denoise = 0.85
    sets.save(tmp_path / "t.json", st)
    assert sets.load(tmp_path / "t.json") == st


def test_unknown_keys_are_errors():
    with pytest.raises(SetError, match="unknown key.*controll"):
        sets.from_dict({**BASE, "style": {**BASE["style"], "controll": "canny"}})
    with pytest.raises(SetError, match=r"cards\['Alpha'\].*flavour"):
        sets.from_dict({**BASE, "cards": {"Alpha": {"flavour": "x"}}})
    with pytest.raises(SetError, match="control must be"):
        sets.from_dict({**BASE, "style": {**BASE["style"], "control": "sketch"}})
    with pytest.raises(SetError, match="denoise"):
        sets.from_dict({**BASE, "style": {**BASE["style"], "denoise": 1.5}})
    with pytest.raises(SetError, match="number should be int"):
        sets.from_dict({**BASE, "cards": {"Alpha": {"number": "1"}}})


def test_recipe_has_subject_seed_and_base():
    st = sets.from_dict(BASE)
    alpha = {"name": "Alpha", "illustration_id": "aaaa"}
    r = st.recipe(alpha)
    assert r["prompt"] == "a dog, pen and ink"
    assert r["base"] == "crop" and "name" not in r and "seed_rule" not in r
    assert r["seed"] == 7000 + __import__("zlib").crc32(b"aaaa") % 1000
    # stable: the seed does not move when a card is inserted ahead of it
    st2 = sets.from_dict({**BASE, "cards": {"Zeta": {"number": 0}, **BASE["cards"]}})
    assert st2.recipe(alpha)["seed"] == r["seed"]
    # position: the legacy rule
    st3 = sets.from_dict({**BASE, "style": {**BASE["style"], "seed_rule": "position"}})
    assert st3.recipe({"name": "Beta", "illustration_id": "b"})["seed"] == 7001
    # explicit seed and base win
    st4 = sets.from_dict({**BASE, "cards": {"Alpha": {"seed": 42, "base": "deadbeef"}}})
    assert st4.recipe(alpha)["seed"] == 42 and st4.recipe(alpha)["base"] == "deadbeef"


def test_recipe_hash_changes_with_any_knob():
    st = sets.from_dict(BASE)
    alpha = {"name": "Alpha", "illustration_id": "aaaa"}
    h = sets.recipe_hash(st.recipe(alpha))
    assert len(h) == 8 and h == sets.recipe_hash(st.recipe(alpha))
    # 6 and 6.0 are the same knob
    assert sets.recipe_hash({"cfg": 6, "x": [1, {"y": 2}]}) == sets.recipe_hash({"cfg": 6.0, "x": [1.0, {"y": 2.0}]})
    assert sets.recipe_hash({"g": True}) != sets.recipe_hash({"g": 1.0})
    st.style.denoise = 0.9
    assert sets.recipe_hash(st.recipe(alpha)) != h
    st.style.denoise = 0.85
    st.cards["Alpha"].base = "12345678"
    assert sets.recipe_hash(st.recipe(alpha)) != h


def test_card_lookup_by_face_or_full_name():
    st = sets.from_dict({"code": "T", "cards": {"Front // Back": {"number": 3}}})
    assert st.card({"name": "Front", "full_name": "Front // Back"}).number == 3
    assert st.card({"name": "Other"}).number is None

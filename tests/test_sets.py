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


def test_save_then_load_is_equal_and_picks_up_css(tmp_path):
    st = sets.from_dict({"code": "TST", "name": "n", "size": 2, "note": "hi", "art_filter": "sepia(1)",
                         "cards": {"Alpha": {"number": 1, "flavor": "f", "art": "a.png", "printing": "rvr:40"},
                                   "Beta": None}})
    fn = tmp_path / "sets" / "tst.json"   # the directory is created
    sets.save(fn, st)
    assert st.path == fn and not fn.with_suffix(".json.part").exists()
    (tmp_path / "sets" / "tst.css").write_text(".name { color: red }")
    back = sets.load(fn)
    assert back == st and back.path == fn and back.css == ".name { color: red }"
    assert back.cards["Beta"] == sets.CardEntry() and back.to_dict() == st.to_dict()
    # a plain dict saves too
    sets.save(fn, {"code": "X"})
    assert sets.load(fn).code == "X"


def test_from_dict_rejects_bad_shapes():
    with pytest.raises(SetError, match="cards must be an object"):
        sets.from_dict({"code": "T", "cards": [{"number": 1}]})
    with pytest.raises(SetError, match="needs a code"):
        sets.from_dict({"name": "no code"})
    with pytest.raises(SetError, match="expected an object"):
        sets.from_dict({"code": "T", "cards": {"Alpha": 1}})


def test_load_errors_name_the_file(tmp_path):
    with pytest.raises(SetError, match="no set file"):
        sets.load(tmp_path / "missing.json")
    (tmp_path / "bad.json").write_text("{")
    with pytest.raises(SetError, match="not valid JSON"):
        sets.load(tmp_path / "bad.json")


def test_card_lookup_by_face_or_full_name():
    st = sets.from_dict({"code": "T", "cards": {"Front // Back": {"number": 3}}})
    assert st.card({"name": "Front", "full_name": "Front // Back"}).number == 3
    assert st.card({"name": "Other"}).number is None


def test_clip_skip_is_a_knob_only_when_set():
    from mint import restyle
    st = sets.from_dict({**BASE, "style": {"name": "s", "prompt": "p"}})
    alpha = {"name": "Alpha", "illustration_id": "a"}
    assert "clip_skip" not in st.recipe(alpha)  # default 1: hashes of existing variants stay put
    h = sets.recipe_hash(st.recipe(alpha))
    assert "CLIPSetLastLayer" not in {n["class_type"] for n in restyle.workflow("x.png", st.recipe(alpha), "p").values()}
    st.style.clip_skip = 2
    r = st.recipe(alpha)
    assert r["clip_skip"] == 2 and sets.recipe_hash(r) != h
    w = restyle.workflow("x.png", r, "p")
    assert w["5"] == {"class_type": "CLIPSetLastLayer", "inputs": {"clip": ["4", 1], "stop_at_clip_layer": -2}}
    assert w["7"]["inputs"]["clip"] == ["5", 0] and w["8"]["inputs"]["clip"] == ["5", 0]
    with pytest.raises(SetError, match="clip_skip"):
        sets.from_dict({**BASE, "style": {"name": "s", "prompt": "p", "clip_skip": 0}})


def test_base_by_label_resolves_through_the_art_cache(tmp_path):
    from mint.art import Art
    art = Art(tmp_path)
    alpha = {"name": "Alpha", "illustration_id": "a"}
    st = sets.from_dict({**BASE, "base": "spore"})
    assert sets.is_label("spore") and not sets.is_label("deadbeef") and not sets.is_label("crop")
    assert st.recipe(alpha)["base"] == "spore"  # no cache to look in: the label stands
    assert st.recipe(alpha, art=art)["base"] == "spore"  # nothing made yet: still the label, so check/UI can say so
    old = art.record(art.new_variant(alpha, "spore", "restyle", {"x": 1}, "crop", "11111111"))
    old.path.write_bytes(b"png")
    old.created = "2026-01-01T00:00:00+00:00"
    art.record(old)
    new = art.record(art.new_variant(alpha, "spore", "restyle", {"x": 2}, "crop", "22222222"))
    new.path.write_bytes(b"png")
    assert art.latest(alpha, "spore").hash == "22222222"
    assert st.recipe(alpha, art=art)["base"] == "22222222"
    st.cards["Alpha"].base = "11111111"  # a card's own base wins over the set's
    assert st.recipe(alpha, art=art)["base"] == "11111111"
    assert sets.from_dict(st.to_dict()).base == "spore"  # round-trips
    art.delete(new)
    assert not new.path.exists() and not new.sidecar.exists() and art.latest(alpha, "spore").hash == "11111111"


def test_refine_is_a_knob_only_when_on():
    from mint import restyle
    alpha = {"name": "Alpha", "illustration_id": "a"}
    st = sets.from_dict({**BASE, "style": {"name": "s", "prompt": "p"}})
    r = st.recipe(alpha)
    assert "refine" not in r and "refine_scale" not in r
    assert "22" not in restyle.workflow("x.png", r, "p")
    st.style.refine, st.style.refine_scale = 0.4, 1.5
    r = st.recipe(alpha)
    assert r["refine"] == 0.4 and r["refine_scale"] == 1.5
    w = restyle.workflow("x.png", r, "p")
    assert w["20"]["inputs"]["scale_by"] == 1.5 and w["22"]["inputs"]["denoise"] == 0.4
    assert w["22"]["inputs"]["positive"] == ["7", 0] and w["22"]["inputs"]["seed"] == r["seed"] + 1
    assert w["16"]["inputs"]["image"] == ["23", 0]  # the ESRGAN pass takes the refined image
    with pytest.raises(SetError, match="refine_scale"):
        sets.from_dict({**BASE, "style": {"name": "s", "prompt": "p", "refine": 0.4, "refine_scale": 5}})


def test_remix_modes_change_the_workflow_and_the_hash():
    from mint import restyle
    alpha = {"name": "Alpha", "illustration_id": "a", "type_line": "Creature — Test"}
    st = sets.from_dict({**BASE, "style": {"name": "s", "prompt": "p"}})
    r1 = st.recipe(alpha)
    assert "remix" not in r1 and r1["base"] == "crop"  # level 1 is the old recipe, hash unchanged
    w1 = restyle.workflow("x.png", r1, "p")
    assert w1["12"]["class_type"] == "VAEEncode" and w1["13"]["inputs"]["positive"] == ["11", 0]

    st.style.remix = "repose"
    r2 = st.recipe(alpha)
    assert r2["remix"] == "repose" and r2["base"] == "crop" and r2["prompt"] == "a dog, p"
    w2 = restyle.workflow("x.png", r2, "p")
    assert w2["12"]["class_type"] == "EmptyLatentImage" and w2["13"]["inputs"]["denoise"] == 1.0
    assert w2["13"]["inputs"]["positive"] == ["11", 0] and "1" in w2  # still guided by the base

    st.style.remix = "new"
    r3 = st.recipe(alpha)
    assert r3["remix"] == "new" and r3["base"] == "none" and r3["prompt"] == "a dog, p"  # the subject is the thread
    w3 = restyle.workflow(None, r3, "p")
    assert "1" not in w3 and "11" not in w3 and w3["13"]["inputs"]["positive"] == ["7", 0]
    beta = {"name": "Beta", "illustration_id": "b", "type_line": "Creature — Test"}
    assert st.recipe(beta)["prompt"] == "Beta, Creature — Test, p"  # no subject: the card itself stands in

    st.style.remix = "restyle"
    st.cards["Alpha"].remix = "repose"  # a card's own mode wins
    assert st.recipe(alpha)["remix"] == "repose"
    assert len({sets.recipe_hash(x) for x in (r1, r2, r3)}) == 3
    with pytest.raises(SetError, match="remix"):
        sets.from_dict({**BASE, "style": {"name": "s", "prompt": "p", "remix": "wilder"}})


def test_one_off_seed_overrides_without_pinning():
    st = sets.from_dict({**BASE, "style": {"name": "s", "prompt": "p", "seed": 7}})
    alpha = {"name": "Alpha", "illustration_id": "a"}
    assert st.recipe(alpha, seed=999)["seed"] == 999      # the roll a "generate" passes
    assert st.cards["Alpha"].seed is None                  # the file is untouched
    st.cards["Alpha"].seed = 55
    assert st.recipe(alpha)["seed"] == 55                  # a pinned seed is used when no override
    assert st.recipe(alpha, seed=999)["seed"] == 999       # an override still wins for its one run
    assert sets.recipe_hash(st.recipe(alpha, seed=1)) != sets.recipe_hash(st.recipe(alpha, seed=2))


def test_repose_has_its_own_control_hold():
    """The repose knobs are in a repose recipe and in no other, so restyle hashes never move."""
    alpha = {"name": "Alpha", "illustration_id": "aaaa"}
    st = sets.from_dict(BASE)
    r = st.recipe(alpha)
    assert "repose_strength" not in r and "repose_end" not in r
    st2 = sets.from_dict({**BASE, "style": {**BASE["style"], "remix": "repose"}})
    r2 = st2.recipe(alpha)
    assert (r2["repose_strength"], r2["repose_end"]) == (0.5, 0.3) and r2["remix"] == "repose"
    st3 = sets.from_dict({**BASE, "style": {**BASE["style"], "remix": "repose", "repose_end": 0.2}})
    assert sets.recipe_hash(st3.recipe(alpha)) != sets.recipe_hash(r2)
    with pytest.raises(SetError, match="repose_end"):
        sets.from_dict({**BASE, "style": {**BASE["style"], "repose_end": 2}})
    # the workflow feeds the ControlNet the repose hold in repose mode, the restyle hold otherwise
    from mint import restyle
    hold = lambda rec: (lambda n: (n["strength"], n["end_percent"]))(restyle.workflow("x.png", rec, "p")["11"]["inputs"])  # noqa: E731
    assert hold(r2) == (0.5, 0.3) and hold(r) == (0.8, 0.9)
    # repose reads one image -- the card's pose, else its base -- and only its OpenPose skeleton
    assert r2["control"] == "openpose" and r2["base"] == "crop" and r["control"] == "canny"
    st4 = sets.from_dict({**BASE, "style": {**BASE["style"], "remix": "repose"},
                          "cards": {"Alpha": {"base": "deadbeef", "pose": "art/other.png"}}})
    r4 = st4.recipe(alpha)
    assert r4["base"] == "art/other.png" and restyle.workflow("x.png", r4, "p")["3"]["class_type"] == "DWPreprocessor"


def test_pick_names_the_styled_art_over_the_recipe(tmp_path):
    from mint.art import Art
    art = Art(tmp_path)
    alpha = {"name": "Alpha", "illustration_id": "a"}
    st = sets.from_dict(BASE)
    derived = sets.recipe_hash(st.recipe(alpha, art=art))
    assert st.styled_hash(alpha, art=art) == derived
    st.cards["Alpha"].pick = "deadbeef"
    assert st.styled_hash(alpha, art=art) == "deadbeef"  # the pick wins, whatever the recipe says
    assert st.recipe(alpha, art=art)["seed"] == st.card_seed("Alpha", "a")  # and leaves the recipe alone
    assert sets.from_dict(st.to_dict()).cards["Alpha"].pick == "deadbeef"
    nostyle = sets.from_dict({"code": "N", "name": "n", "cards": {"Alpha": {"pick": "deadbeef"}, "Beta": {}}})
    assert nostyle.styled_hash(alpha) == "deadbeef" and nostyle.styled_hash({"name": "Beta"}) is None
    with pytest.raises(SetError, match="pick should be a variant hash"):
        sets.from_dict({"code": "N", "name": "n", "cards": {"Alpha": {"pick": "spore"}}})


def test_inspire_reads_the_base_through_an_ip_adapter_and_no_controlnet():
    """inspire: an empty latent, the words, and the base as an image prompt. Its knobs are in
    its recipe alone, and the ControlNet / img2img knobs are out of it, so no other mode's hash moves."""
    from mint import restyle
    alpha = {"name": "Alpha", "illustration_id": "a", "type_line": "Creature — Test"}
    plain = sets.from_dict({**BASE, "style": {"name": "s", "prompt": "p"}})
    r0 = plain.recipe(alpha)
    assert not any(k.startswith("inspire_") for k in r0)
    st = sets.from_dict({**BASE, "style": {"name": "s", "prompt": "p", "remix": "inspire"}})
    r = st.recipe(alpha)
    assert r["remix"] == "inspire" and r["base"] == "crop" and r["prompt"] == "a dog, p"
    assert (r["inspire_weight"], r["inspire_end"], r["inspire_type"]) == (0.5, 0.8, "standard")
    assert not any(k in r for k in ("control", "control_strength", "control_end", "controlnet", "denoise"))
    beta = {"name": "Beta", "illustration_id": "b", "type_line": "Creature — Test"}
    assert st.recipe(beta)["prompt"] == "Beta, Creature — Test, p"  # no subject: the card itself sets the scene
    w = restyle.workflow("x.png", r, "p")
    assert w["1"]["inputs"]["image"] == "x.png" and "3" not in w and "11" not in w  # read, not preprocessed
    assert w["30"]["class_type"] == "IPAdapterUnifiedLoader" and w["31"]["inputs"]["image"] == ["2", 0]
    assert (w["31"]["inputs"]["weight"], w["31"]["inputs"]["end_at"], w["31"]["inputs"]["weight_type"]) == (0.5, 0.8, "linear")
    assert w["31"]["inputs"]["embeds_scaling"] == "K+V w/ C penalty"
    assert w["13"]["inputs"]["model"] == ["31", 0] and w["13"]["inputs"]["positive"] == ["7", 0]
    assert w["12"]["class_type"] == "EmptyLatentImage" and w["13"]["inputs"]["denoise"] == 1.0
    st2 = sets.from_dict({**BASE, "style": {"name": "s", "prompt": "p", "remix": "inspire", "inspire_type": "prompt first", "refine": 0.4}})
    w2 = restyle.workflow("x.png", st2.recipe(alpha), "p")
    assert w2["31"]["inputs"]["weight_type"] == "ease out"
    assert w2["13"]["inputs"]["model"] == ["31", 0] and w2["22"]["inputs"]["model"] == ["4", 0]  # the refine pass: no image prompt
    assert sets.recipe_hash(st2.recipe(alpha)) != sets.recipe_hash(r)
    with pytest.raises(SetError, match="inspire_type"):
        sets.from_dict({**BASE, "style": {"name": "s", "prompt": "p", "inspire_type": "vibes"}})
    with pytest.raises(SetError, match="inspire_weight"):
        sets.from_dict({**BASE, "style": {"name": "s", "prompt": "p", "inspire_weight": 3}})

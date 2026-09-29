"""Orders: the union of sets that goes to the printer, its counts, and what the bracket costs."""
import json

import pytest
from fastapi.testclient import TestClient

from mint import orders, sets, workspace
from mint.errors import SetError
from mint.web.server import create_app
from tests.conftest import synthetic_card


def deck(code, *names):
    return sets.from_dict({"code": code, "name": code.title(),
                           "cards": {n: {"number": i} for i, n in enumerate(names, 1)}})


@pytest.fixture
def three():
    return {"SLV": deck("SLV", "Sol Ring", "Sliver Overlord", "Island"),
            "GSH": deck("GSH", "Sol Ring", "Gishath"),
            "URE": deck("URE", "Ureni")}


def order(*lines, **kw):
    return orders.from_dict({"name": "october", "sets": list(lines), **kw})


def test_a_count_per_card_is_the_whole_vocabulary(three):
    """One number says everything an order can say about a card: how many to print. The set's
    default covers the rest, so the file never copies a card list."""
    o = order({"code": "SLV", "cards": {"Sol Ring": 2, "Island": 0}}, {"code": "GSH"})
    assert o.names(three["SLV"]) == ["Sol Ring", "Sol Ring", "Sliver Overlord"]   # 2 copies, no Island
    assert o.names(three["GSH"]) == ["Sol Ring", "Gishath"]                        # untouched: one of each
    assert o.names(three["URE"]) == []                                            # not in the order at all


def test_a_set_the_order_opts_into_card_by_card(three):
    """copies 0 is how one card comes out of a big set without listing the other two hundred."""
    o = order({"code": "SLV", "copies": 0, "cards": {"Sol Ring": 1}})
    assert o.names(three["SLV"]) == ["Sol Ring"]


def test_a_card_added_to_a_deck_is_in_the_order(three):
    """The order names the set, not its contents, so the set stays the aggregate of cards."""
    o = order({"code": "SLV"})
    assert len(o.names(three["SLV"])) == 3
    three["SLV"].cards["Mana Crypt"] = sets.CardEntry(number=4)
    assert "Mana Crypt" in o.names(three["SLV"])   # nothing about the order had to change


def test_the_bill_is_the_bracket(three):
    """MakePlayingCards sells fixed project sizes, so the order is billed at the next one up and
    the slots between are paid for either way -- which is the whole reason to union."""
    o = order({"code": "SLV"}, {"code": "GSH"}, {"code": "URE"})
    b = o.bill(three)
    assert b["total"] == 6 and b["bracket"] == 18
    assert b["headroom"] == 12                      # 12 more cards cost nothing
    assert b["under"] is None and b["drop"] is None  # nothing below 18 to fall back to
    assert [r["code"] for r in b["rows"]] == ["SLV", "GSH", "URE"]
    assert [r["cards"] for r in b["rows"]] == [3, 2, 1]
    assert b["problems"] == []


def test_the_bracket_is_read_off_the_sum_of_copies(three):
    big = deck("BIG", *[f"Card {i}" for i in range(40)])
    o = order({"code": "BIG", "copies": 6})
    b = o.bill({"BIG": big})
    assert b["total"] == 240 and b["bracket"] == 396 and b["under"] == 234
    assert b["drop"] == 6 and b["headroom"] == 156


def test_the_bill_reports_a_deck_edited_out_from_under_the_order(three):
    """A count for a card the set no longer has is the one way an order can go quietly wrong."""
    o = order({"code": "SLV", "cards": {"Mana Crypt": 2}}, {"code": "XXX"})
    b = o.bill(three)
    assert b["rows"][0]["missing"] == ["Mana Crypt"]
    assert b["rows"][1]["gone"] is True
    assert any("Mana Crypt" in p for p in b["problems"])
    assert any("XXX" in p for p in b["problems"])
    assert o.parts(three) == [(three["SLV"], ["Sol Ring", "Sliver Overlord", "Island"])]  # the dead line is skipped


def test_editing_writes_down_only_what_changed(three):
    o = order({"code": "SLV"})
    o.set_count("SLV", "Sol Ring", 2)
    assert o.to_dict()["sets"] == [{"code": "SLV", "cards": {"Sol Ring": 2}}]
    o.set_count("SLV", "Sol Ring", 1)              # back at the set's default
    assert o.to_dict()["sets"] == [{"code": "SLV"}]  # so the exception goes, rather than being written
    o.add_set("gsh")
    assert [e.code for e in o.sets] == ["SLV", "GSH"]
    o.add_set("GSH", 2)                            # adding a set already in it sets its default
    assert len(o.sets) == 2 and o.entry("GSH").copies == 2
    o.drop_set("SLV")
    assert [e.code for e in o.sets] == ["GSH"]
    with pytest.raises(SetError, match="not in this order"):
        o.drop_set("SLV")


def test_a_broken_order_says_what_is_wrong():
    for bad, why in (({"name": "x", "sets": [{"code": "A"}, {"code": "a"}]}, "in the order twice"),
                     ({"name": "x", "sets": [{"code": "A", "copies": -1}]}, "copies must be"),
                     ({"name": "x", "sets": [{"code": "A", "cards": {"X": "two"}}]}, "must be a whole number"),
                     ({"name": "x", "mode": "fancy"}, "mode must be one of"),
                     ({"name": "x", "dpi": "lots"}, "dpi must be"),
                     ({"name": "x", "sets": [{"code": "A", "quantity": 2}]}, "unknown key"),
                     ({"sets": []}, "an order needs a name")):
        with pytest.raises(SetError, match=why):
            orders.from_dict(bad)


def test_the_name_becomes_the_file_name():
    assert orders.slug("October run!") == "october-run"
    assert orders.slug("???") == "order"
    assert orders.from_dict({"name": "October run!"}).slug == "october-run"


def test_settings_round_trip():
    o = orders.from_dict({"name": "x", "stock": "(M31) Linen", "dpi": 600, "mode": "styled", "foil": "holo"})
    assert orders.from_dict(o.to_dict()) == o
    assert "foil_strength" not in o.to_dict()          # left at its default, so it stays out of the file
    assert orders.from_dict({"name": "x"}).to_dict() == {"name": "x", "sets": []}


def test_a_set_is_found_by_its_code_not_its_file_name(tmp_path, monkeypatch):
    """A set file is not named after its code -- sets/bls1.json holds BLS -- and two files can
    carry the same code, so an order's line has to be resolved by reading them."""
    monkeypatch.setenv("MINT_HOME", str(tmp_path))
    monkeypatch.setattr(workspace, "_default", None)
    ws = workspace.default()
    ws.sets.mkdir()
    sets.save(ws.sets / "bls1.json", deck("BLS", "Alpha"))
    sets.save(ws.sets / "mer.json", deck("MER", "Beta"))
    sets.save(ws.sets / "mer-missing.json", deck("MER", "Gamma"))
    (ws.sets / "broken.json").write_text("{not json")

    every = orders.by_code(ws)
    assert set(every) == {"BLS", "MER"}                   # the broken file is skipped, not fatal
    # two files carry MER; what matters is that an order resolves a code to the same set the
    # workbench does, whichever that is, so a line never points at a different deck than the page
    from mint.web.server import State
    S = State(ws)
    for code, st in every.items():
        assert st.path == S.find_set(code).path
    o = order({"code": "BLS"})
    assert orders.loaded_sets(ws, o)["BLS"].names() == ["Alpha"]
    assert o.bill(orders.loaded_sets(ws, o))["total"] == 1   # and not "no such set any more"


# --- over the API ---------------------------------------------------------------------
@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("MINT_HOME", str(tmp_path))
    monkeypatch.delenv("MINT_CARDS", raising=False)
    monkeypatch.setattr(workspace, "_default", None)
    ws = workspace.default()
    ws.sets.mkdir()
    ws.cards_file.write_text("".join(json.dumps(synthetic_card(
        name=n, collector_number=str(i), illustration_id=f"{i:08d}-0000-0000-0000-000000000000")) + "\n"
        for i, n in enumerate(["Alpha", "Beta", "Gamma"], 1)))
    sets.save(ws.sets / "slv.json", deck("SLV", "Alpha", "Beta"))
    sets.save(ws.sets / "gsh.json", deck("GSH", "Alpha", "Gamma"))
    c = TestClient(create_app(ws))
    c.ws = ws
    return c


def test_the_workbench_builds_an_order(client):
    assert client.get("/api/orders").json() == []
    o = client.post("/api/orders", json={"name": "October", "sets": ["SLV"]}).json()
    assert o["slug"] == "october" and o["bill"]["total"] == 2 and o["bill"]["bracket"] == 18

    o = client.post("/api/orders/october/sets", json={"code": "GSH"}).json()
    assert [s["code"] for s in o["sets"]] == ["SLV", "GSH"] and o["bill"]["total"] == 4
    # Alpha is in both decks, so it is in the order twice -- one copy per back
    assert [c["count"] for d in o["detail"] for c in d["cards"] if c["name"] == "Alpha"] == [1, 1]

    o = client.put("/api/orders/october/cards", json={"code": "SLV", "name": "Alpha", "count": 3}).json()
    assert o["bill"]["total"] == 6
    o = client.put("/api/orders/october/cards", json={"code": "SLV", "name": "Beta", "count": 0}).json()
    assert o["bill"]["total"] == 5

    o = client.put("/api/orders/october", json={"mode": "styled", "dpi": 600}).json()
    assert o["mode"] == "styled" and o["dpi"] == 600
    assert orders.load(client.ws.orders / "october.json").mode == "styled"   # and it is on disk

    o = client.request("DELETE", "/api/orders/october/sets/SLV").json()
    assert [s["code"] for s in o["sets"]] == ["GSH"] and o["bill"]["total"] == 2
    assert client.request("DELETE", "/api/orders/october").json() == {"deleted": "october"}
    assert client.get("/api/orders").json() == []


def test_the_api_refuses_what_would_make_a_dead_order(client):
    client.post("/api/orders", json={"name": "october"})
    assert client.post("/api/orders", json={"name": "October"}).status_code == 409   # same slug
    assert client.post("/api/orders", json={"name": "  "}).status_code == 400
    assert client.post("/api/orders/october/sets", json={"code": "NOPE"}).status_code == 404
    assert client.put("/api/orders/october", json={"stock": "(S99) Glitter"}).status_code == 400
    assert client.put("/api/orders/october", json={"mode": "fancy"}).status_code == 400
    assert client.put("/api/orders/nope/cards", json={"code": "SLV", "name": "Alpha", "count": 1}).status_code == 404
    client.post("/api/orders/october/sets", json={"code": "SLV"})
    assert client.put("/api/orders/october/cards",
                      json={"code": "SLV", "name": "Alpha", "count": 500}).status_code == 400

"""The workbench's set, card and style-template CRUD, over the API with a tiny card file."""
import json

import pytest
from fastapi.testclient import TestClient

from mint import sets, workspace
from mint.web.server import create_app
from tests.conftest import synthetic_card


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("MINT_HOME", str(tmp_path))
    monkeypatch.delenv("MINT_CARDS", raising=False)
    monkeypatch.setattr(workspace, "_default", None)
    ws = workspace.default()
    ws.sets.mkdir()
    ws.styles.mkdir()
    cards = [synthetic_card(name=n, collector_number=str(i), illustration_id=f"{i:08d}-0000-0000-0000-000000000000")
             for i, n in enumerate(["Alpha", "Beta", "Gamma", "Delta"], 1)]
    ws.cards_file.write_text("".join(json.dumps(c) + "\n" for c in cards))
    (ws.styles / "look.json").write_text(json.dumps({"name": "look", "prompt": "a look", "cfg": 4}))
    (ws.styles / "look.css").write_text(".card { color: red }")
    c = TestClient(create_app(ws))
    c.ws = ws
    return c


def test_set_crud(client):
    r = client.post("/api/sets", json={"code": "tst", "name": "Test", "decklist": "1 Alpha\n2x Beta\nGamma\n", "style": "look"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["code"] == "TST" and [c["name"] for c in d["cards_detail"]] == ["Alpha", "Beta", "Gamma"]
    assert d["style"]["name"] == "look" and d["css"] == ".card { color: red }"
    assert client.post("/api/sets", json={"code": "TST", "name": "again", "names": ["Alpha"]}).status_code == 400
    assert client.post("/api/sets", json={"code": "T-1", "name": "bad", "names": ["Alpha"]}).status_code == 400

    r = client.patch("/api/sets/TST", json={"name": "Renamed", "note": "hi", "base": "look", "art_filter": ""})
    assert r.status_code == 200 and r.json()["name"] == "Renamed" and r.json()["base"] == "look"
    st = sets.load(client.ws.sets / "tst.json")
    assert st.note == "hi" and st.art_filter is None and st.style.cfg == 4  # the style block survives a patch
    assert client.patch("/api/sets/TST", json={"cards": {}}).status_code == 400
    assert client.patch("/api/sets/TST", json={"code": ""}).status_code == 400
    r = client.patch("/api/sets/TST", json={"code": "new"})
    assert r.json()["code"] == "NEW" and client.get("/api/sets/NEW").status_code == 200

    r = client.delete("/api/sets/NEW")
    assert r.status_code == 200 and not (client.ws.sets / "tst.json").exists() and not (client.ws.sets / "tst.css").exists()
    assert client.get("/api/sets/NEW").status_code == 404


def test_card_crud(client):
    client.post("/api/sets", json={"code": "TST", "name": "t", "names": ["Alpha", "Beta"]})
    r = client.post("/api/sets/TST/cards", json={"decklist": "1 Gamma\n1 Nope\n"})
    assert r.status_code == 400 and "Nope" in r.json()["detail"]
    r = client.post("/api/sets/TST/cards", json={"names": ["Gamma", "Beta"]})
    assert r.status_code == 200 and r.json()["added"] == 1
    names = lambda: sets.load(client.ws.sets / "tst.json").names()  # noqa: E731
    assert names() == ["Alpha", "Beta", "Gamma"]
    assert sets.load(client.ws.sets / "tst.json").cards["Gamma"].number == 3

    r = client.put("/api/sets/TST/cards/Gamma", json={"subject": "a fixture", "flavor": "f", "number": 9})
    assert r.status_code == 200 and r.json()["entry"] == {"number": 9, "flavor": "f", "subject": "a fixture"}
    r = client.put("/api/sets/TST/cards/Gamma", json={"flavor": None})
    assert r.json()["entry"] == {"number": 9, "subject": "a fixture"}

    assert client.put("/api/sets/TST/cards", json={"order": ["Gamma", "Alpha"]}).status_code == 400
    r = client.put("/api/sets/TST/cards", json={"order": ["Gamma", "Alpha", "Beta"], "renumber": True})
    assert r.status_code == 200 and names() == ["Gamma", "Alpha", "Beta"]
    assert [c.number for c in sets.load(client.ws.sets / "tst.json").cards.values()] == [1, 2, 3]

    r = client.post("/api/sets/TST/cards/Alpha/rename", json={"name": "Delta"})
    assert r.status_code == 200 and names() == ["Gamma", "Delta", "Beta"]
    assert client.post("/api/sets/TST/cards/Delta/rename", json={"name": "Beta"}).status_code == 400

    r = client.delete("/api/sets/TST/cards/Delta")
    assert r.status_code == 200 and names() == ["Gamma", "Beta"] and r.json()["size"] == 2
    assert client.delete("/api/sets/TST/cards/Delta").status_code == 404


def test_style_templates(client):
    r = client.get("/api/styles")
    assert r.status_code == 200
    names = {t["name"]: t for t in r.json()}
    assert names["look"]["style"] == {"name": "look", "prompt": "a look", "cfg": 4} and names["look"]["css"]
    assert names["neon"]["builtin"] and not names["look"]["builtin"]

    # create: only the keys given are spelled out; a bad knob is refused
    r = client.put("/api/styles/mine", json={"style": {"prompt": "p", "denoise": 0.7, "steps": 28}, "css": ".x{}"})
    assert r.status_code == 200, r.text
    body = json.loads((client.ws.styles / "mine.json").read_text())
    assert body == {"name": "mine", "prompt": "p", "denoise": 0.7, "steps": 28}
    assert (client.ws.styles / "mine.css").read_text() == ".x{}"
    assert client.put("/api/styles/mine", json={"style": {"prompt": "p", "denoise": 7}}).status_code == 400
    assert client.put("/api/styles/bad name", json={"style": {"prompt": "p"}}).status_code == 400

    # move to the private tier: one file, in one place
    r = client.put("/api/styles/mine", json={"style": {"prompt": "p2"}, "private": True})
    assert r.json()["private"] and (client.ws.styles / "private" / "mine.json").exists()
    assert not (client.ws.styles / "mine.json").exists() and not (client.ws.styles / "mine.css").exists()

    # a set takes a template, a template is saved from a set, and the usage is reported
    client.post("/api/sets", json={"code": "TST", "name": "t", "names": ["Alpha"]})
    r = client.post("/api/sets/TST/style/template", json={"template": "mine"})
    assert r.status_code == 200 and r.json()["style"] == {"name": "mine", "prompt": "p2"}
    assert client.get("/api/styles/mine").json()["sets"] == ["TST"]
    assert client.post("/api/sets/TST/style/template", json={"template": "nothing"}).status_code == 400
    r = client.post("/api/styles", json={"set": "TST", "name": "copy"})
    assert r.status_code == 200 and (client.ws.styles / "copy.json").exists()
    assert client.post("/api/styles", json={"set": "TST", "name": "copy"}).status_code == 400  # exists, no force
    assert client.post("/api/styles", json={"set": "TST", "name": "copy", "force": True}).status_code == 200

    assert client.delete("/api/styles/mine").status_code == 200
    assert client.delete("/api/styles/neon").status_code == 400  # a built-in has no file
    assert client.get("/api/styles/mine").status_code == 404


def test_restyle_job_takes_a_template_whole(client):
    client.post("/api/sets", json={"code": "TST", "name": "t", "names": ["Alpha"], "style": "look"})
    r = client.post("/api/jobs", json={"kind": "restyle", "set": "TST", "names": ["Alpha"], "template": "neon"})
    assert r.status_code == 200, r.text
    assert r.json()["title"] == "restyle 1 card(s) as neon" and r.json()["params"]["template"] == "neon"
    job = lambda **kw: client.post("/api/jobs", json={"kind": "restyle", "set": "TST", "names": ["Alpha"], **kw}).status_code  # noqa: E731
    assert job(template="nope") == 400
    # a set without a style can still restyle as a template
    client.put("/api/sets/TST/style", json={})
    assert job() == 400 and job(template="look") == 200


def test_restyle_takes_roll_a_seed_each(client):
    client.post("/api/sets", json={"code": "TST", "name": "t", "names": ["Alpha"], "style": "look"})
    r = client.post("/api/jobs", json={"kind": "restyle", "set": "TST", "names": ["Alpha"], "takes": 3})
    assert r.status_code == 200 and r.json()["params"]["takes"] == 3
    assert r.json()["title"] == "restyle 1 card(s) as look x 3 takes, drafts: enhance the keeper"
    r = client.post("/api/jobs", json={"kind": "restyle", "set": "TST", "names": ["Alpha"], "takes": 3, "upscale": True})
    assert r.json()["title"] == "restyle 1 card(s) as look x 3 takes"
    r = client.post("/api/jobs", json={"kind": "restyle", "set": "TST", "names": ["Alpha"], "takes": 99})
    assert r.json()["params"]["takes"] == 16  # capped

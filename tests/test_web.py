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

    # a template carries frame knobs: saved slim, reported whole, and applied to a set with the style
    r = client.put("/api/styles/dressed", json={"style": {"prompt": "d"}, "frame": {"watermark": 0.6, "art_bevel": 1.0}})
    assert r.status_code == 200 and r.json()["frame"]["watermark"] == 0.6
    assert json.loads((client.ws.styles / "dressed.json").read_text())["frame"] == {"watermark": 0.6}
    assert client.get("/api/styles/mine").json()["frame"] is None
    assert client.post("/api/sets/TST/style/template", json={"template": "dressed"}).json()["frame"]["watermark"] == 0.6
    assert sets.load(client.ws.sets / "tst.json").frame.watermark == 0.6
    assert client.put("/api/styles/dressed", json={"style": {"prompt": "d"}, "frame": {"watermark": 5}}).status_code == 400
    r = client.post("/api/styles", json={"set": "TST", "name": "fromset"})
    assert json.loads((client.ws.styles / "fromset.json").read_text())["frame"] == {"watermark": 0.6}
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


def test_pick_is_the_styled_art_and_clears_with_its_variant(client):
    from mint.art import Art
    client.post("/api/sets", json={"code": "TST", "name": "t", "names": ["Alpha"], "style": "look"})
    ws = client.ws
    card = json.loads(ws.cards_file.read_text().splitlines()[0])
    art = Art(ws.art)
    crop = art.crop(card, fetch=False)
    crop.parent.mkdir(parents=True, exist_ok=True)
    crop.write_bytes(b"jpg")
    v = art.new_variant(card, "look", "restyle", {"prompt": "x", "base": "crop", "seed": 5}, "crop", "abcd1234")
    v.path.parent.mkdir(parents=True, exist_ok=True)
    v.path.write_bytes(b"png")
    art.record(v)
    r = client.get("/api/sets/TST/cards/Alpha")
    assert r.status_code == 200 and r.json()["current"] is None and "picked" not in r.json()
    assert r.json()["styled"]["kind"] != "styled"
    r = client.put("/api/sets/TST/cards/Alpha", json={"pick": "abcd1234"})
    assert r.status_code == 200 and r.json()["picked"]["hash"] == "abcd1234"
    assert r.json()["styled"]["kind"] == "styled" and r.json()["styled"]["hash"] == "abcd1234"
    assert client.put("/api/sets/TST/cards/Alpha", json={"pick": "nope"}).status_code == 400
    r = client.delete("/api/sets/TST/cards/Alpha/variants/abcd1234")
    assert r.status_code == 200 and "pick" not in r.json()["entry"]
    assert sets.load(ws.sets / "tst.json").cards["Alpha"].pick is None


def test_printrun_job_takes_paper_and_stock(client):
    client.post("/api/sets", json={"code": "TST", "name": "t", "names": ["Alpha", "Beta"]})
    r = client.post("/api/jobs", json={"kind": "printrun", "set": "TST", "names": ["Alpha"], "paper": "a4"})
    assert r.status_code == 200, r.text
    assert r.json()["title"] == "print run: TST plain, 1 card(s) on a4, PDF only" and r.json()["params"]["stock"] is None
    r = client.post("/api/jobs", json={"kind": "printrun", "set": "TST", "styled": True, "stock": "matte", "copies": 2})
    assert r.status_code == 200 and r.json()["title"] == "print run: TST styled, 2 card(s) on letter, 2x on matte"
    assert client.post("/api/jobs", json={"kind": "printrun", "set": "TST", "paper": "tabloid"}).status_code == 400
    assert client.post("/api/jobs", json={"kind": "printrun", "set": "TST", "stock": "papyrus"}).status_code == 400
    assert client.get("/api/workspace").json()["print"]["paper"] == ["letter", "a4"]


def _pdf(path, pages=2):
    from PIL import Image
    ims = [Image.new("RGB", (120, 160), (200 + i * 20, 200, 200)) for i in range(pages)]
    ims[0].save(path, "PDF", save_all=True, append_images=ims[1:])


def test_pdfs_list_export_delete(client, tmp_path, monkeypatch):
    """The pdf page: a set's print runs and the impose file are listed, exported to export_dir
    (refusing to clobber unless forced), downloadable through /file, and deletable."""
    import shutil
    client.post("/api/sets", json={"code": "TST", "name": "t", "names": ["Alpha"]})
    assert client.get("/api/sets/TST/pdfs").json()["pdfs"] == []
    run = client.ws.home / "out" / "tst" / "print"
    run.mkdir(parents=True)
    _pdf(run / "TST-plain-1.pdf")
    _pdf(client.ws.home / "out" / "tst.pdf", pages=1)
    monkeypatch.setattr(client.ws, "export_dir", str(tmp_path / "desk"))
    d = client.get("/api/sets/TST/pdfs").json()
    assert d["export_dir"] == str(tmp_path / "desk")
    assert {(p["file"], p["origin"]) for p in d["pdfs"]} == {("TST-plain-1.pdf", "print run"), ("tst.pdf", "mint impose")}
    if shutil.which("pdfinfo"):
        assert {p["file"]: p["pages"] for p in d["pdfs"]} == {"TST-plain-1.pdf": 2, "tst.pdf": 1}
    if shutil.which("pdftoppm"):
        r = client.get("/pdfpage", params={"path": str(run / "TST-plain-1.pdf"), "n": 2, "w": 400})
        assert r.status_code == 200 and r.headers["content-type"] == "image/png"
        assert client.get("/pdfpage", params={"path": str(run / "TST-plain-1.pdf"), "n": 0}).status_code == 400
    # the browser's save: a download flag turns the file route into an attachment
    r = client.get("/file", params={"path": str(run / "TST-plain-1.pdf"), "download": "true"})
    assert r.status_code == 200 and 'attachment; filename="TST-plain-1.pdf"' in r.headers["content-disposition"]
    # export, refuse to clobber, force
    r = client.post("/api/sets/TST/pdfs/export", json={"file": "TST-plain-1.pdf"})
    assert r.status_code == 200 and (tmp_path / "desk" / "TST-plain-1.pdf").read_bytes() == (run / "TST-plain-1.pdf").read_bytes()
    assert client.post("/api/sets/TST/pdfs/export", json={"file": "TST-plain-1.pdf"}).status_code == 409
    assert client.post("/api/sets/TST/pdfs/export", json={"file": "TST-plain-1.pdf", "force": True}).status_code == 200
    assert client.post("/api/sets/TST/pdfs/export", json={"file": "../../sets/tst.json"}).status_code == 400
    # delete: only a listed name
    assert client.delete("/api/sets/TST/pdfs/nope.pdf").status_code == 400
    assert client.delete("/api/sets/TST/pdfs/TST-plain-1.pdf").status_code == 200
    assert [p["file"] for p in client.get("/api/sets/TST/pdfs").json()["pdfs"]] == ["tst.pdf"]


def test_describe_job_needs_a_describer_then_writes_the_subject(client, art, monkeypatch):
    """The describe job: refused with the reason while no describer is set up; with one, the
    worker reads the crop, writes the subject into the set file, and reports it as an item."""
    import time

    from mint.describe import Describer
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    client.post("/api/sets", json={"code": "TST", "name": "t", "names": ["Alpha", "Beta"], "style": "look"})
    info = client.get("/api/workspace").json()["describer"]
    assert info["kind"] == "claude" and not info["ready"] and "ANTHROPIC_API_KEY" in info["hint"]
    r = client.post("/api/jobs", json={"kind": "describe", "set": "TST", "names": ["Alpha"]})
    assert r.status_code == 400 and "ANTHROPIC_API_KEY" in r.json()["detail"]

    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    client.app.state.S._describer = (0.0, None)  # the readiness check is cached for 30 s: ask again
    monkeypatch.setattr(Describer, "_ask", lambda self, data, mime_type, text:
                        '{"description": "a fixture on a plinth", "subject": "a bronze fixture on a plinth, humming"}')
    ws = client.ws
    ws.art.mkdir(exist_ok=True)
    for i in (1, 2):
        (ws.art / f"{i:08d}-0000-0000-0000-000000000000.jpg").write_bytes(open(art, "rb").read())
    client.put("/api/sets/TST/cards/Beta", json={"subject": "by hand"})
    r = client.post("/api/jobs", json={"kind": "describe", "set": "TST", "names": ["Alpha", "Beta"], "force": False})
    assert r.status_code == 200, r.text
    assert r.json()["title"] == "describe 2 card(s)" and r.json()["params"]["generate"] is False
    jid = r.json()["id"]
    for _ in range(100):
        j = next(x for x in client.get("/api/jobs").json() if x["id"] == jid)
        if j["state"] in ("done", "failed", "cancelled"):
            break
        time.sleep(0.05)
    assert j["state"] == "done", j
    st = sets.load(ws.sets / "tst.json")
    assert st.cards["Alpha"].subject == "a bronze fixture on a plinth, humming" and st.cards["Beta"].subject == "by hand"
    assert [it["kind"] for it in j["items"]] == ["subject"] and j["items"][0]["name"] == "Alpha"
    c = client.get("/api/sets/TST/cards/Alpha").json()
    assert c["described"]["description"] == "a fixture on a plinth" and c["entry"]["subject"].startswith("a bronze")
    # with generate, the job is a "new cards" one in the look
    r = client.post("/api/jobs", json={"kind": "describe", "set": "TST", "names": ["Alpha"], "generate": True})
    assert r.status_code == 200 and r.json()["title"] == "new cards: 1 card(s) as look"
    client.put("/api/sets/TST/style", json={})
    assert client.post("/api/jobs", json={"kind": "describe", "set": "TST", "generate": True}).status_code == 400
    body = {"kind": "describe", "set": "TST", "generate": True, "template": "look"}
    assert client.post("/api/jobs", json=body).status_code == 200

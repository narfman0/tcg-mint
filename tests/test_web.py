"""The workbench's set, card and style-template CRUD, over the API with a tiny card file."""
import json
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mint import frame, scryfall, sets, workspace
from mint.manifest import Manifest, frame_hash
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
    # a new set queues a crops job; Scryfall is a stub that "downloads" a tiny JPEG (or the failure set here)
    fetched, fail = [], []

    def fetch(url, dest, timeout=300):
        if fail:
            raise OSError(fail[0])
        fetched.append(url)
        from PIL import Image
        Path(dest).parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (8, 6), (200, 100, 50)).save(dest, "JPEG")
        return dest
    monkeypatch.setattr(scryfall, "fetch", fetch)
    c = TestClient(create_app(ws))
    c.ws = ws
    c.fetched, c.fail = fetched, fail
    c.settle = lambda: settle(c)
    return c


def settle(client, timeout=5):
    """Wait until no job is queued or running."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if all(j["state"] in ("done", "failed", "cancelled") for j in client.get("/api/jobs").json()):
            return
        time.sleep(0.02)
    raise AssertionError("jobs still running")


def test_a_new_set_fetches_its_crops_and_the_board_knows_which_are_missing(client):
    r = client.post("/api/sets", json={"code": "TST", "name": "t", "names": ["Alpha", "Beta"]})
    assert r.status_code == 200
    client.settle()
    jobs = client.get("/api/jobs").json()
    assert [j["kind"] for j in jobs] == ["crops"] and jobs[0]["state"] == "done", (jobs[0]["error"], jobs[0]["log"])
    assert jobs[0]["title"] == "fetch 2 crop(s) for TST" and jobs[0]["params"]["origin"] == "new set"
    assert [i["name"] for i in jobs[0]["items"]] == ["Alpha", "Beta"] and jobs[0]["items"][0]["key"] == "crop"
    assert len(client.fetched) == 2
    d = client.get("/api/sets/TST").json()
    assert all(c["crop"] for c in d["cards_detail"])
    # every crop on disk: nothing to queue
    assert client.post("/api/jobs", json={"kind": "crops", "set": "TST"}).status_code == 400
    # cards added queue their own; a card whose fetch fails is named and the rest still land
    client.fail.append("no route to Scryfall")
    r = client.post("/api/sets/TST/cards", json={"names": ["Gamma", "Delta"]})
    assert r.status_code == 200 and r.json()["added"] == 2
    client.settle()
    j = client.get("/api/jobs").json()[0]
    assert j["kind"] == "crops" and j["state"] == "failed" and "2 of 2 crop(s)" in j["error"] and "Gamma" in j["error"]
    client.fail.clear()
    r = client.post("/api/jobs", json={"kind": "crops", "set": "TST", "names": ["Alpha", "Gamma", "Delta"]})
    assert r.status_code == 200 and r.json()["params"]["names"] == ["Gamma", "Delta"]  # Alpha has one
    client.settle()
    assert all(c["crop"] for c in client.get("/api/sets/TST").json()["cards_detail"])


def test_one_thumbnail_asked_for_twice_at_once(client, art):
    """The printing picker shows the default printing twice (its own tile and the listed one); both
    thumbnails land whole, neither request 500s over the other's temp file."""
    from PIL import Image

    from mint.web.thumbs import thumbnail
    ws = client.ws
    src = ws.home / "big.png"
    Image.open(art).resize((2000, 1400)).save(src)
    outs, errors = [], []

    def one():
        try:
            outs.append(thumbnail(ws, str(src), 320))
        except Exception as e:  # noqa: BLE001
            errors.append(e)
    ts = [threading.Thread(target=one) for _ in range(6)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert not errors and len(set(outs)) == 1 and outs[0].exists()
    assert Image.open(outs[0]).size[0] == 320 and not list(outs[0].parent.glob("*.part*"))


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

    # replace: the css goes when none is sent
    r = client.put("/api/styles/mine", json={"style": {"prompt": "p2"}})
    assert r.status_code == 200 and json.loads((client.ws.styles / "mine.json").read_text()) == {"name": "mine", "prompt": "p2"}
    assert not (client.ws.styles / "mine.css").exists()

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


def test_animate_job_and_the_card_page_show_clips(client, art):
    """The animate job takes the row's knobs over the set's block and the image to start from; the
    card page lists a clip's videos beside its poster and the recipe the block names now."""
    from mint.art import Art
    client.post("/api/sets", json={"code": "TST", "name": "t", "names": ["Alpha"], "style": "look"})
    ws = client.ws
    card = json.loads(ws.cards_file.read_text().splitlines()[0])
    cache = Art(ws.art)
    crop = cache.crop(card, fetch=False)
    crop.parent.mkdir(parents=True, exist_ok=True)
    crop.write_bytes(open(art, "rb").read())
    r = client.get("/api/workspace").json()
    assert "ready" in r["comfy"]["wan"] and r["loops"] == ["pingpong", "crossfade", "none"]
    r = client.get("/api/sets/TST").json()
    assert r["motion_knobs"]["length"] == 49 and "motion" not in r  # the defaults; no block in the file
    r = client.put("/api/sets/TST/cards/Alpha", json={"motion": "the dog's ears twitch"})
    assert r.status_code == 200 and r.json()["motion_recipe"]["prompt"] == "the dog's ears twitch"
    assert r.json()["motion_recipe"]["base"] == "crop" and len(r.json()["motion_hash"]) == 8

    r = client.post("/api/jobs", json={"kind": "animate", "set": "TST", "names": ["Alpha"], "base": "crop", "takes": 2,
                                       "motion": {"loop": "none", "length": 81}})
    assert r.status_code == 200, r.text
    assert r.json()["title"] == "animate 1 card(s) x 2 takes" and "81-frame" in r.json()["params"]["what"]
    bad = {"kind": "animate", "set": "TST", "names": ["Alpha"], "motion": {"length": 50}}
    assert client.post("/api/jobs", json=bad).status_code == 400

    v = cache.new_variant(card, "motion", "motion", {"length": 49, "loop": "pingpong", "base": "crop"}, "crop", "abcdef12")
    v.path.parent.mkdir(parents=True, exist_ok=True)
    v.path.write_bytes(b"png")
    v.path.with_suffix(".webm").write_bytes(b"webm")
    cache.record(v)
    c = client.get("/api/sets/TST/cards/Alpha").json()
    m = next(x for x in c["variants"] if x["kind"] == "motion")
    assert m["videos"] == [str(v.path.with_suffix(".webm"))]
    assert client.delete("/api/sets/TST/cards/Alpha/variants/abcdef12").status_code == 200
    assert not v.path.with_suffix(".webm").exists()


def test_img_revalidates_so_a_rewritten_file_shows(client, art):
    """A crop refetched, a clip remade: an image can be written over in place under the same name, so
    /img must not let the browser keep a thumbnail for an hour. The thumbnail's key is the ETag, a
    match is a 304, a rewritten file is new."""
    import os
    import shutil

    from PIL import Image
    p = client.ws.home / "out" / "render.png"
    p.parent.mkdir()
    shutil.copy(art, p)
    r = client.get("/img", params={"path": str(p), "w": 160})
    assert r.status_code == 200 and r.headers["cache-control"] == "no-cache" and r.headers["etag"]
    again = client.get("/img", params={"path": str(p), "w": 160}, headers={"If-None-Match": r.headers["etag"]})
    assert again.status_code == 304 and again.headers["etag"] == r.headers["etag"]
    Image.new("RGB", (284, 200), "white").save(p)  # re-rendered: new bytes, a later mtime
    os.utime(p, (p.stat().st_atime, p.stat().st_mtime + 5))
    fresh = client.get("/img", params={"path": str(p), "w": 160}, headers={"If-None-Match": r.headers["etag"]})
    assert fresh.status_code == 200 and fresh.headers["etag"] != r.headers["etag"]


def test_design_on_the_set_and_the_card(client):
    client.post("/api/sets", json={"code": "tst", "name": "Test", "names": ["Alpha", "Beta"]})
    assert "fullart" in client.get("/api/workspace").json()["designs"]
    r = client.put("/api/sets/TST/design", json={"design": "extended"})
    assert r.status_code == 200 and r.json()["design"] == "extended"
    assert client.put("/api/sets/TST/design", json={"design": "showcase"}).status_code == 400
    r = client.put("/api/sets/TST/cards/Alpha", json={"design": "fullart"})
    assert r.status_code == 200 and r.json()["entry"]["design"] == "fullart" and r.json()["design"] == "fullart"
    assert client.get("/api/sets/TST/cards/Beta").json()["design"] == "extended"
    assert client.put("/api/sets/TST/cards/Beta", json={"design": "showcase"}).status_code == 400
    r = client.put("/api/sets/TST/design", json={"design": None})
    assert r.status_code == 200 and "design" not in r.json()
    assert client.get("/api/sets/TST/cards/Beta").json()["design"] == "m15"
    ps = client.get("/api/sets/TST/cards/Alpha/printings").json()
    assert ps and ps[0]["design"] == "m15"


def render_entry(m, out, fn, *, card="Alpha", design="m15", at="2026-01-01T00:00:00+00:00", fhash="", styled=False,
                 number=1):
    """A render on disk and in the manifest, without driving Chromium. The file is a real image at
    the render's proportions, so an export can crop and resample it."""
    from PIL import Image
    m.entries[fn] = {"card": card, "number": number, "theme": "wizards", "set": "TST", "styled": styled,
                     "design": design, "back": False, "sizes": {"text": 8.0},
                     "source": {"kind": "crop", "path": "", "hash": None, "label": None},
                     "shrunk": False, "frame": fhash, "dpi": 1200, "rendered_at": at}
    Image.new("RGB", (272, 372), (30, 60, 110)).save(out / fn)


def test_every_render_is_kept_under_the_card_and_one_can_be_pinned(client):
    """Renders behave like the art: each one that differs is its own file listed under the card, and
    the card can be pinned to the one it prints as -- which is then never stale, whatever is rendered after."""
    client.post("/api/sets", json={"code": "TST", "name": "t", "names": ["Alpha"]})
    client.settle()
    out = client.ws.home / "out" / "tst"
    out.mkdir(parents=True)
    st = sets.load(client.ws.sets / "tst.json")
    fh = frame_hash(st.css, frame.frame_css(st.frame))
    m = Manifest(out)
    old, new = "TST-001_Alpha-aaaaaaaa.png", "TST-001_Alpha-bbbbbbbb.png"
    render_entry(m, out, old, design="m15", at="2026-01-01T00:00:00+00:00", fhash="00000000")
    render_entry(m, out, new, design="retro", at="2026-02-01T00:00:00+00:00", fhash=fh)
    m.save()

    c = client.get("/api/sets/TST/cards/Alpha").json()
    assert [r["file"] for r in c["renders"]["all"]] == [new, old]          # newest first, both kept
    assert [r["design"] for r in c["renders"]["all"]] == ["retro", "m15"]  # what tells them apart
    assert c["renders"]["plain"]["file"] == new and c["renders"]["all"][1]["stale"] == "the frame changed"

    r = client.put("/api/sets/TST/cards/Alpha", json={"render": old})
    assert r.status_code == 200
    plain = r.json()["renders"]["plain"]
    assert plain["file"] == old and plain["pinned"] and plain["stale"] is None  # pinned: it prints as it is
    assert json.loads((client.ws.sets / "tst.json").read_text())["cards"]["Alpha"]["render"] == old
    assert client.put("/api/sets/TST/cards/Alpha", json={"render": "nope.png"}).status_code == 404

    d = client.delete(f"/api/sets/TST/renders/{old}").json()
    assert d["renders"]["plain"]["file"] == new and "render" not in d["entry"]  # the pin went with it
    assert not (out / old).exists()


def test_a_pinned_render_that_is_gone_is_said_so(client):
    client.post("/api/sets", json={"code": "TST", "name": "t", "names": ["Alpha"]})
    client.settle()
    out = client.ws.home / "out" / "tst"
    out.mkdir(parents=True)
    m = Manifest(out)
    render_entry(m, out, "TST-001_Alpha-aaaaaaaa.png")
    m.save()
    client.put("/api/sets/TST/cards/Alpha", json={"render": "TST-001_Alpha-aaaaaaaa.png"})
    (out / "TST-001_Alpha-aaaaaaaa.png").unlink()  # deleted from under it
    c = client.get("/api/sets/TST/cards/Alpha").json()
    assert c["renders"]["pin_gone"] == "TST-001_Alpha-aaaaaaaa.png" and "plain" not in c["renders"]


def test_the_page_and_the_workspace_files_are_revalidated_not_held(client):
    """app.js and a full-size file must come back with no-cache, so a changed one shows on the next
    load instead of after a hard refresh."""
    assert client.get("/static/app.js").headers["cache-control"] == "no-cache"
    p = client.ws.home / "out" / "x.png"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"png")
    r = client.get("/file", params={"path": str(p)})
    assert r.status_code == 200 and r.headers["cache-control"] == "no-cache" and r.headers["etag"]


def test_the_board_exports_a_set_for_mpc_autofill(client):
    """The export job writes out/<set>/mpc/: a card image at MPC's size per card, and the cards.xml
    its desktop tool reads, with every path resolving from inside the folder."""
    import xml.etree.ElementTree as ET

    from PIL import Image
    client.post("/api/sets", json={"code": "TST", "name": "t", "names": ["Alpha", "Beta"]})
    client.settle()
    st = sets.load(client.ws.sets / "tst.json")
    fh = frame_hash(st.css, frame.frame_css(st.frame))
    out = client.ws.home / "out" / "tst"
    out.mkdir(parents=True)
    m = Manifest(out)
    render_entry(m, out, "TST-001_Alpha-aaaaaaaa.png", card="Alpha", number=1, fhash=fh)
    render_entry(m, out, "TST-002_Beta-bbbbbbbb.png", card="Beta", number=2, fhash=fh)
    m.save()

    assert client.get("/api/workspace").json()["mpc"]["max_dpi"] == 800
    r = client.post("/api/jobs", json={"kind": "export", "set": "TST", "dpi": 300, "back": "none"})
    assert r.status_code == 200
    client.settle()
    job = [j for j in client.get("/api/jobs").json() if j["kind"] == "export"][0]
    assert job["state"] == "done", (job["error"], job["log"])

    mpc = out / "mpc"
    root = ET.fromstring((mpc / "cards.xml").read_text())
    assert root.find("details").findtext("quantity") == "2"
    ids = [c.findtext("id") for c in root.find("fronts").findall("card")]
    assert ids == ["images/001 Alpha.png", "images/002 Beta.png"]
    for rel in ids:
        assert (mpc / rel).is_file()
    with Image.open(mpc / ids[0]) as im:
        assert im.size == (816, 1110)   # 2.72 x 3.70in at 300 DPI
    assert client.post("/api/jobs", json={"kind": "export", "set": "TST", "stock": "(S99) Glitter"}).status_code == 400


def test_the_cleanup_page_lists_what_could_go_and_removes_only_what_is_picked(client):
    """It reads by default and never selects for you; a POST takes ids and nothing else."""
    client.post("/api/sets", json={"code": "TST", "name": "t", "names": ["Alpha"]})
    client.settle()
    st = sets.load(client.ws.sets / "tst.json")
    fh = frame_hash(st.css, frame.frame_css(st.frame))
    out = client.ws.home / "out" / "tst"
    out.mkdir(parents=True)
    m = Manifest(out)
    render_entry(m, out, "TST-001_Alpha-new.png", at="2026-09-20T00:00:00+00:00", fhash=fh)
    render_entry(m, out, "TST-001_Alpha-old.png", at="2020-01-01T00:00:00+00:00", fhash=fh)
    m.save()

    r = client.get("/api/cleanup", params={"keep_days": 3}).json()
    assert r["count"] == 1 and r["bytes"] > 0
    block = r["groups"][0]
    assert block["key"] == "render-superseded" and block["why"] and block["count"] == 1
    item = block["items"][0]
    assert item["what"] == "TST-001_Alpha-old.png" and item["bytes"] > 0 and item["age_days"] > 1000
    assert item["set"] == "TST" and item["card"] == "Alpha"
    assert (out / "TST-001_Alpha-old.png").exists()   # listing removed nothing

    assert client.post("/api/cleanup", json={"ids": "nope"}).status_code == 400
    assert client.get("/api/cleanup", params={"keep_days": -1}).status_code == 400
    # a long enough keep window offers nothing at all
    assert client.get("/api/cleanup", params={"keep_days": 100000}).json()["count"] == 0

    done = client.post("/api/cleanup", json={"ids": [item["id"]], "keep_days": 3}).json()
    assert done["removed"] == 1 and done["bytes"] == item["bytes"] and done["missed"] == []
    assert not (out / "TST-001_Alpha-old.png").exists() and (out / "TST-001_Alpha-new.png").exists()
    assert client.get("/api/cleanup", params={"keep_days": 3}).json()["count"] == 0
    # an id that is no longer a candidate comes back under `missed`
    again = client.post("/api/cleanup", json={"ids": [item["id"]], "keep_days": 3}).json()
    assert again["removed"] == 0 and again["missed"] == [item["id"]]

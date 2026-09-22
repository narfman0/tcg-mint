"""The workbench in a real browser: the pages draw, a tile opens its card, the viewer steps,
the frame knobs save, and a render job round-trips through the queue to a file on disk.
Needs Playwright's Chromium (the `render` marker) and uvicorn (the [web] extra)."""
import json
import socket
import threading
import time

import pytest

from tests.conftest import synthetic_card

pytest.importorskip("playwright")
uvicorn = pytest.importorskip("uvicorn")
pytestmark = pytest.mark.render


@pytest.fixture
def served(tmp_path, monkeypatch):
    from PIL import Image

    from mint import workspace
    from mint.web.server import create_app
    monkeypatch.setenv("MINT_HOME", str(tmp_path))
    monkeypatch.delenv("MINT_CARDS", raising=False)
    monkeypatch.setattr(workspace, "_default", None)
    ws = workspace.default()
    ws.sets.mkdir()
    ws.styles.mkdir()
    cards = [synthetic_card(name=n, collector_number=str(i), illustration_id=f"{i:08d}-0000-0000-0000-000000000000")
             for i, n in enumerate(["Alpha", "Beta"], 1)]
    ws.cards_file.write_text("".join(json.dumps(c) + "\n" for c in cards))
    ws.art.mkdir()
    for c in cards:  # a crop for each, so tiles have pictures and a render needs no network
        Image.new("RGB", (284, 200), (40, 90, 160)).save(ws.art / (c["illustration_id"] + ".jpg"))
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(create_app(ws), host="127.0.0.1", port=port, log_level="warning"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    for _ in range(100):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
            break
        except OSError:
            time.sleep(0.05)
    yield f"http://127.0.0.1:{port}", ws
    server.should_exit = True
    t.join(5)


def until(pred, seconds=10):
    """Poll a predicate; True once it holds, False when the time is up."""
    end = time.time() + seconds
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.1)
    return pred()


def test_pages_tiles_viewer_knobs_and_a_render_job(served):
    from playwright.sync_api import sync_playwright
    url, ws = served
    errors = []
    with sync_playwright() as p:
        b = p.chromium.launch(channel="chromium")
        pg = b.new_page(viewport={"width": 1200, "height": 800})
        pg.on("pageerror", lambda e: errors.append(str(e)))
        r = pg.request.post(url + "/api/sets", data={"code": "TST", "name": "Test", "names": ["Alpha", "Beta"]})
        assert r.ok, r.text()

        pg.goto(url + "/#/")
        pg.wait_for_selector(".setcard")
        assert "TST" in pg.locator(".setcard").first.inner_text()

        pg.goto(url + "/#/set/TST")
        pg.wait_for_selector(".tile")
        assert pg.locator(".tile").count() == 2
        pg.locator(".tile").first.click()
        pg.wait_for_selector(".cardhead h1")
        assert pg.url.endswith("#/set/TST/card/Alpha") and "Alpha" in pg.locator(".cardhead h1").inner_text()

        pg.goto(url + "/#/set/TST/view/Alpha")
        pg.wait_for_selector("#viewer:not([hidden]) .vbottom")
        assert "1 / 2" in pg.locator("#viewer .vbottom").inner_text()
        pg.keyboard.press("ArrowRight")
        pg.wait_for_function("document.querySelector('#viewer .vbottom').innerText.includes('2 / 2')")

        pg.goto(url + "/#/set/TST/frame")
        pg.wait_for_selector("[data-fk=watermark]")
        s = pg.locator("[data-fk=watermark]")
        s.fill("0.5")
        s.dispatch_event("change")
        assert until(lambda: json.loads((ws.sets / "tst.json").read_text()).get("frame") == {"watermark": 0.5})
        pg.wait_for_selector("#toast div")  # the save's own redraw has happened before the page moves on

        pg.goto(url + "/#/set/TST/card/Alpha")
        pg.wait_for_selector("[data-cjob=render-plain]")
        pg.select_option("#dpi", "300")
        pg.locator("[data-cjob=render-plain]").click()
        pg.wait_for_selector("#toast div")
        finished = lambda: [j for j in pg.request.get(url + "/api/jobs").json() if j["state"] in ("done", "failed", "cancelled")]  # noqa: E731
        assert until(lambda: bool(finished()), 90)
        job = finished()[0]
        assert job["state"] == "done" and not job.get("error"), job
        # the file is named for what came out: TST-001_Alpha-<eight hex>.png
        made = [f.name for f in (ws.home / "out" / "tst").glob("TST-001_Alpha-????????.png")]
        assert made

        # it lands under the card as its own column, and pinning it writes the card's entry
        pg.wait_for_selector(".renders .col")
        pg.locator(".renders .col [data-act=pin-render]").first.click()
        assert until(lambda: json.loads((ws.sets / "tst.json").read_text())["cards"]["Alpha"].get("render") == made[0])
        pg.wait_for_selector(".renders .col [data-act=unpin-render]")

        pg.goto(url + "/#/jobs")
        pg.wait_for_selector(".job")
        assert "render" in pg.locator(".job").first.inner_text()
        b.close()
    assert not errors

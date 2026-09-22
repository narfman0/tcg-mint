"""One real Chromium render at low DPI: the frame still comes out the right size, and a second
render of the same card lands beside the first only when it came out different."""
import json

import pytest
from PIL import Image

from mint import frame, render, sets, workspace
from mint.manifest import Manifest
from tests.conftest import synthetic_card
from tests.test_frame import NoSymbols

pytest.importorskip("playwright")


@pytest.mark.render
def test_render_produces_a_card(tmp_path, art):
    from mint.browser import Browser
    html = frame.build_html(synthetic_card(), symbols=NoSymbols(), art_url="file://" + art)
    out = tmp_path / "card.png"
    with Browser(150) as b:
        sizes = b.render(html, out)
    im = Image.open(out)
    assert im.size == (408, 558)  # 2.72 x 3.72 in at 150 DPI
    assert sizes["text"] > 0 and sizes["name"] > 0


@pytest.mark.render
def test_a_render_is_named_for_what_came_out(tmp_path, monkeypatch):
    """The eight hex on the end are the PNG's own digest: the same card in the same frame twice is
    one file, and a card rendered in another design is a second file beside it, not over it."""
    monkeypatch.setenv("MINT_HOME", str(tmp_path))
    monkeypatch.delenv("MINT_CARDS", raising=False)
    monkeypatch.setattr(workspace, "_default", None)
    ws = workspace.default()
    ws.sets.mkdir()
    ws.art.mkdir()
    card = synthetic_card(name="Alpha", illustration_id="11111111-0000-0000-0000-000000000000")
    ws.cards_file.write_text(json.dumps(card) + "\n")
    Image.new("RGB", (284, 200), (40, 90, 160)).save(ws.art / (card["illustration_id"] + ".jpg"))
    st = sets.from_dict({"code": "TST", "name": "t", "cards": {"Alpha": {"number": 1}}})
    sets.save(ws.sets / "tst.json", st)
    out = tmp_path / "out" / "tst"

    for _ in range(2):
        render.render_cards(ws, ["Alpha"], set_path=ws.sets / "tst.json", dpi=150, out_dir=str(out))
    assert len(Manifest(out).entries) == 1, list(Manifest(out).entries)

    st.cards["Alpha"].design = "fullart"
    sets.save(ws.sets / "tst.json", st)
    render.render_cards(ws, ["Alpha"], set_path=ws.sets / "tst.json", dpi=150, out_dir=str(out))
    entries = Manifest(out).entries
    assert len(entries) == 2 and {e["design"] for e in entries.values()} == {"m15", "fullart"}
    assert all(fn.startswith("TST-001_Alpha-") for fn in entries), list(entries)
    assert not list(out.glob(".*.part.png"))  # nothing half-written left behind

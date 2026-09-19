"""One real Chromium render at low DPI: the frame still comes out the right size."""
import pytest
from PIL import Image

from mint import render
from tests.conftest import synthetic_card

pytest.importorskip("playwright")


@pytest.mark.render
def test_render_produces_a_card(tmp_path, art):
    card = synthetic_card()
    html = render.build_html(card, "wizards", {}, 1, "TST", 1, {"art": art}, None)
    from playwright.sync_api import sync_playwright
    out = tmp_path / "card.png"
    with sync_playwright() as p:
        b, page = render.browser(p, 150)
        sizes = render.render(page, html, str(out))
        b.close()
    im = Image.open(out)
    assert im.size == (408, 558)  # 2.72 x 3.72 in at 150 DPI
    assert sizes["text"] > 0 and sizes["name"] > 0

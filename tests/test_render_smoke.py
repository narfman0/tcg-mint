"""One real Chromium render at low DPI: the frame still comes out the right size."""
import pytest
from PIL import Image

from mint import frame
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

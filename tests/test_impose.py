"""The imposition page: card positions and cut marks, from the CARD/PAPER constants."""
import re

import pytest

from mint import impose

IMG = re.compile(r'<img src="file://(.*?)" style="left:(.*?)in;top:(.*?)in;width:(.*?)in;height:(.*?)in">')


def test_page_html_places_nine_cards_on_letter():
    paths = [f"/renders/{i:03d}.png" for i in range(9)]
    bleed = 0.04
    html = impose.page_html(paths, "letter", bleed)
    cw, ch = impose.CARD[0] + 2 * bleed, impose.CARD[1] + 2 * bleed
    pw, ph = impose.PAPER["letter"]
    x0, y0 = (pw - 3 * cw) / 2, (ph - 3 * ch) / 2
    imgs = IMG.findall(html)
    assert [p for p, *_ in imgs] == paths
    for k, (_, left, top, w, h) in enumerate(imgs):
        assert float(left) == pytest.approx(x0 + (k % 3) * cw)
        assert float(top) == pytest.approx(y0 + (k // 3) * ch)
        assert (float(w), float(h)) == (pytest.approx(cw), pytest.approx(ch))
    assert f'<div class="page" style="width:{pw}in;height:{ph}in">' in html
    # six cut lines per axis (four grid lines, the inner two doubled by the bleed), each drawn
    # as a tick in both margins and one green line across the block; the marks come after
    # the images so they paint on top of the bleed
    assert html.count('<i class="v"') == 12 and html.count('<i class="h"') == 12
    assert html.count('<i class="v g"') == 6 and html.count('<i class="h g"') == 6
    assert html.rindex("<img") < html.index("<i ")
    # the first vertical cut sits on the 2.5in grid line: bleed in from the image edge, ticked
    # above the top row and lined from the top of the block to its bottom
    x = x0 + bleed
    assert f'<i class="v" style="left:{x}in;top:{y0 - impose.MARK}in;height:{impose.MARK}in"></i>' in html
    assert f'<i class="v g" style="left:{x}in;top:{y0}in;height:{3 * ch}in"></i>' in html
    # the two lines between columns are 2*bleed apart, and a horizontal line spans all three columns
    assert f'left:{x0 + cw - bleed}in' in html and f'left:{x0 + cw + bleed}in' in html
    assert f'<i class="h g" style="top:{y0 + bleed}in;left:{x0}in;width:{3 * cw}in"></i>' in html


def test_page_html_fewer_cards_and_a4():
    # two cards in the top row: lines for two columns and one row, each only as long as the cards
    html = impose.page_html(["/a.png", "/b.png"], "a4", 0.0)
    cw, ch = impose.CARD
    pw, ph = impose.PAPER["a4"]
    x0, y0 = (pw - 3 * cw) / 2, (ph - 3 * ch) / 2
    assert len(IMG.findall(html)) == 2 and html.count("<i ") == 18
    assert html.count('<i class="v g"') == 4 and html.count('<i class="h g"') == 2
    assert f'<i class="v g" style="left:{x0 + cw}in;top:{y0}in;height:{ch}in"></i>' in html
    assert f'<i class="h g" style="top:{y0}in;left:{x0}in;width:{2 * cw}in"></i>' in html
    assert f'<i class="h" style="top:{y0}in;left:{x0 + 2 * cw}in;width:{impose.MARK}in"></i>' in html


def test_page_html_rejects_bleed_that_does_not_fit():
    with pytest.raises(SystemExit, match="do not fit on letter"):
        impose.page_html(["/a.png"] * 9, "letter", 0.2)

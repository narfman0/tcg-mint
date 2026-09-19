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
    # four grid lines per axis, two marks each end, minus the outer edges' outside-facing pair
    assert html.count('<i class="v"') == 12 and html.count('<i class="h"') == 12
    # the first vertical mark sits on the 2.5in grid line: bleed in from the image edge, above the top row
    assert f'<i class="v" style="left:{x0 + bleed}in;top:{y0 - 0.18 - 0.02}in;height:0.18in"></i>' in html


def test_page_html_fewer_cards_and_a4():
    html = impose.page_html(["/a.png", "/b.png"], "a4", 0.0)
    assert len(IMG.findall(html)) == 2 and html.count("<i ") == 24


def test_page_html_rejects_bleed_that_does_not_fit():
    with pytest.raises(SystemExit, match="do not fit on letter"):
        impose.page_html(["/a.png"] * 9, "letter", 0.2)

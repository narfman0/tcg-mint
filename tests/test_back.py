"""mint back: the common card back, and the per-set backs that make a union order sortable."""
import pytest

from mint import back, sets, workspace
from mint.errors import MintError, SetError


def test_a_set_without_a_block_prints_the_common_back():
    """The default Back is the BLS back as it has always been drawn: the mountain, in its own
    colours, not recoloured off the palette."""
    html = back.build_html(workspace.default())
    assert "$" not in html                       # every placeholder was substituted
    assert ">BLASTED<" in html and ">STUDIOS<" in html
    assert "#ffd27a" in html and "url(#rock)" in html   # the mountain, untouched
    assert html == back.build_html(workspace.default(), sets.Back())


def test_a_set_with_a_symbol_prints_it_instead_of_the_mountain():
    ws = workspace.default()
    html = back.build_html(ws, sets.Back(word="SLIVERS", sub="THE HIVE", symbol="lgn",
                                         oval=["#cfe8d8", "#8fbfa4", "#4c7d63", "#2a4a39"], ink="#10201a"))
    assert ">SLIVERS<" in html and ">THE HIVE<" in html
    assert "url(#rock)" not in html              # the mountain is gone
    assert 'fill="#10201a"' in html              # the symbol takes the set's ink
    assert "#cfe8d8" in html                     # and the glow behind it comes off the oval palette
    # the trim is derived, so a green back keeps no brown from the one it was copied from
    assert "rgba(207,232,216," in html and "#6d4a26" not in html


def test_a_symbol_nobody_has_is_an_error_not_a_silent_mountain():
    """A back that quietly fell back to the common one is a back you would notice after ordering."""
    ws = workspace.default()
    with pytest.raises(MintError, match="no symbol file"):
        back.build_html(ws, sets.Back(symbol="nowhere/sliver.svg"))
    with pytest.raises(MintError, match="no expansion symbol"):
        back.build_html(ws, sets.Back(symbol="zzzz"))


def test_the_block_is_checked_when_the_set_loads():
    ok = sets.from_dict({"code": "X", "back": {"symbol": "lgn", "word": "SLIVERS"}})
    assert ok.back.symbol == "lgn" and ok.back.tag == "TCG · MINT"
    assert sets.from_dict({"code": "X"}).back is None      # no block, and the common back is printed
    for bad, why in (({"paper": ["#fff"] * 4}, "paper must be 4 hex colours"),
                     ({"oval": ["#112233"] * 3}, "oval must be 4 hex colours"),
                     ({"dots": ["#112233"] * 4}, "dots must be 5 hex colours"),
                     ({"ink": "black"}, "ink must be a hex colour"),
                     ({"word": "A HIVE OF SLIVERS AND THEN SOME"}, "the back has room for 14"),
                     ({"symbol": 3}, "symbol should be str"),
                     ({"wordmark": "x"}, "unknown key")):
        with pytest.raises(SetError, match=why):
            sets.from_dict({"code": "X", "back": bad})


def test_the_block_round_trips_without_its_defaults():
    """Only what the file changed is written back, as the style and frame blocks do."""
    st = sets.from_dict({"code": "X", "back": {"symbol": "lgn", "word": "SLIVERS"}})
    assert st.to_dict()["back"] == {"symbol": "lgn", "word": "SLIVERS"}
    assert sets.from_dict(st.to_dict()).back == st.back

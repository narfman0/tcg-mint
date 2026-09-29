"""mint export: MPC Autofill's geometry, its order file, and a real set through the whole thing."""
import json
import xml.etree.ElementTree as ET

import pytest
from PIL import Image

from mint import export, sets, workspace
from mint.errors import MintError
from tests.conftest import synthetic_card


def test_the_card_image_is_the_size_mpc_autofill_measures(tmp_path):
    """MPC Autofill's desktop tool reads a card's resolution off its height alone:
    img_dpi = 10 * round(height * 300 / 1110). An export has to come out at the DPI it asked for."""
    src = tmp_path / "render.png"
    Image.new("RGB", (816, 1116), (10, 20, 30)).save(src)  # a 2.72x3.72in render at 300 DPI
    for dpi, size in ((800, (2176, 2960)), (600, (1632, 2220)), (300, (816, 1110))):
        out = tmp_path / f"{dpi}.png"
        assert export.mpc_image(src, out, dpi) == size
        with Image.open(out) as im:
            assert im.size == size
            assert 10 * round(im.height * 300 / 1110 / 10) == dpi


def test_a_render_is_trimmed_not_squashed(tmp_path):
    """The 0.02in comes off the top and bottom as bleed: a row that was 1% down the card is still
    1% down the card afterwards, which a scale-to-fit would not manage."""
    src = tmp_path / "render.png"
    im = Image.new("RGB", (272, 372), "black")
    for y in range(186, 372):  # the bottom half white: the seam is exactly at the middle
        for x in range(272):
            im.putpixel((x, y), (255, 255, 255))
    im.save(src)
    out = tmp_path / "mpc.png"
    export.mpc_image(src, out, 300)
    with Image.open(out) as got:
        assert got.width == 816 and got.height == 1110
        assert got.getpixel((408, 100)) == (0, 0, 0)          # still black above the seam
        assert got.getpixel((408, 1000)) == (255, 255, 255)   # still white below it
        mid = next(y for y in range(got.height) if got.getpixel((408, y))[0] > 127)
        assert abs(mid - got.height / 2) <= 2                 # the seam stayed in the middle


def test_the_art_window_is_covered_not_stretched(tmp_path):
    """The window is `cover`: it keeps the picture's aspect and crops the excess, so nothing is ever
    squashed. What can go wrong is pixels, and this is the arithmetic that says so -- a Scryfall crop
    is 2.7x short of the M15 window at 800 DPI, and the 4x ESRGAN pass `mint upscale` makes has
    pixels to spare for every design."""
    from mint import frame

    def headroom(size, design, dpi=800):
        src = tmp_path / f"{design}-{size[0]}.png"
        if not src.exists():
            Image.new("RGB", size, "grey").save(src)
        entry = {"source": {"path": str(src)}, "design": design}
        return export.art_headroom(entry, dpi)[0]

    crop, enhanced = (626, 457), (626 * 4, 457 * 4)   # Scryfall's art_crop, and it after mint upscale
    assert round(headroom(crop, "m15"), 1) == 2.7    # the raw crop: ~300 DPI on the card
    assert round(headroom(enhanced, "m15"), 2) == 0.67  # enhanced: half again what the window needs
    # every design the enhanced crop is the right shape for is covered outright
    for design in ("m15", "extended", "borderless", "modern", "retro"):
        assert headroom(enhanced, design) < 1.0, design
    # a restyle at the block's default is short on its own and ample once enhanced
    assert round(headroom((1248, 912), "m15"), 2) == 1.35
    assert headroom((1248 * 4, 912 * 4), "m15") < 1.0
    # the window's aspect and the defaults agree to within a percent: `cover` crops next to nothing
    assert abs(crop[0] / crop[1] / frame.art_aspect("m15") - 1) < 0.01
    assert abs(1248 / 912 / frame.art_aspect("m15") - 1) < 0.01
    # art that cannot be measured is not a warning
    assert export.art_headroom({"source": {"path": "/no/such.png"}, "design": "m15"}, 800) is None


def test_brackets_and_file_names():
    assert [export.bracket(n) for n in (1, 18, 19, 90, 235, 612, 700)] == [18, 18, 36, 90, 396, 612, 612]
    assert export.safe("Ajani, Nacatl Pariah // Ajani, Deathfang") == "Ajani Nacatl Pariah Ajani Deathfang"
    assert export.safe("Borrowing 100,000 Arrows") == "Borrowing 100 000 Arrows"
    assert export.safe("Kongming, \"Sleeping Dragon\"") == "Kongming Sleeping Dragon"
    assert export.safe("???") == "card"


def test_the_order_file_is_what_the_desktop_tool_reads():
    """<order> with a <details> block, a <card> per slot naming a local file, and a <cardback>
    for every slot without a back of its own -- the schema mpc-autofill's desktop tool parses."""
    xml = export.order_xml([(0, "images/001 Alpha.png", "Alpha"), (1, "images/002 Beta.png", "Beta")],
                           [(1, "images/002b Gamma.png", "Gamma")], "images/back.png")
    root = ET.fromstring(xml)
    d = root.find("details")
    assert d.findtext("quantity") == "2" and d.findtext("bracket") == "18"
    assert d.findtext("stock") == export.DEFAULT_STOCK and d.findtext("foil") == "false"
    fronts = root.find("fronts").findall("card")
    assert [c.findtext("slots") for c in fronts] == ["0", "1"]
    assert [c.findtext("sourceType") for c in fronts] == ["Local File", "Local File"]
    assert fronts[0].findtext("id") == "images/001 Alpha.png" and fronts[0].findtext("name") == "001 Alpha.png"
    assert fronts[0].findtext("query") == "alpha"
    assert [c.findtext("slots") for c in root.find("backs").findall("card")] == ["1"]
    assert root.findtext("cardback") == "images/back.png"
    # a set with no double-faced card has no <backs> at all; the cardback fills every slot
    assert ET.fromstring(export.order_xml([(0, "a.png", "A")], [], "b.png")).find("backs") is None


def test_dpi_past_mpcs_maximum_is_refused(tmp_path, monkeypatch):
    monkeypatch.setenv("MINT_HOME", str(tmp_path))
    monkeypatch.setattr(workspace, "_default", None)
    st = sets.from_dict({"code": "TST", "cards": {}})
    with pytest.raises(MintError, match="past MPC's 800"):
        export.export(workspace.default(), st, [], tmp_path / "mpc", dpi=1200)
    with pytest.raises(MintError, match="stock is one of"):
        export.export(workspace.default(), st, [], tmp_path / "mpc", stock="(S99) Glitter")


@pytest.fixture
def ws(tmp_path, monkeypatch):
    monkeypatch.setenv("MINT_HOME", str(tmp_path))
    monkeypatch.delenv("MINT_CARDS", raising=False)
    monkeypatch.setattr(workspace, "_default", None)
    w = workspace.default()
    w.sets.mkdir()
    w.art.mkdir()
    cards = [synthetic_card(name=n, collector_number=str(i), illustration_id=f"{i:08d}-0000-0000-0000-000000000000")
             for i, n in enumerate(["Alpha", "Beta, the Second"], 1)]
    w.cards_file.write_text("".join(json.dumps(c) + "\n" for c in cards))
    for c in cards:
        Image.new("RGB", (284, 200), (40, 90, 160)).save(w.art / (c["illustration_id"] + ".jpg"))
    return w


@pytest.mark.render
def test_a_set_exports_as_a_folder_mpc_autofill_can_run_in(ws):
    st = sets.from_dict({"code": "TST", "name": "t",
                         "cards": {"Alpha": {"number": 1}, "Beta, the Second": {"number": 2}}})
    sets.save(ws.sets / "tst.json", st)
    st = sets.load(ws.sets / "tst.json")
    out = ws.home / "mpc"
    r = export.export(ws, st, st.names(), out, dpi=300, card_back="none", log=lambda m: None)

    assert r["fronts"] == 2 and r["rendered"] == ["Alpha", "Beta, the Second"]
    assert sorted(p.name for p in (out / "images").iterdir()) == ["001 Alpha.png", "002 Beta the Second.png"]
    root = ET.fromstring((out / "cards.xml").read_text())
    ids = [c.findtext("id") for c in root.find("fronts").findall("card")]
    assert ids == ["images/001 Alpha.png", "images/002 Beta the Second.png"]
    for rel in ids:  # every path in the order file resolves from the folder: the tool can run here
        assert (out / rel).is_file()
    with Image.open(out / "images" / "001 Alpha.png") as im:
        assert im.size == (816, 1110)
    assert "MPC Autofill" in (out / "README.txt").read_text()

    # a second export renders nothing: the renders are there and none has gone stale
    again = export.export(ws, st, st.names(), out, dpi=300, card_back="none", log=lambda m: None)
    assert again["rendered"] == []


def test_a_render_below_the_export_is_as_good_as_missing():
    """A vector frame should never be blown up: a 300 DPI proof cannot serve an 800 DPI order.
    A pin is the card's own choice and is honoured, with a warning instead."""
    assert export.under_dpi({"dpi": 300}, 800) is True
    assert export.under_dpi({"dpi": 1200}, 800) is False
    assert export.under_dpi({"dpi": 800}, 800) is False
    assert export.under_dpi({"dpi": None}, 800) is False   # a render from before the manifest said


@pytest.mark.render
def test_a_proof_sized_render_is_made_again_for_the_order(ws):
    st = sets.from_dict({"code": "TST", "name": "t", "cards": {"Alpha": {"number": 1}}})
    sets.save(ws.sets / "tst.json", st)
    st = sets.load(ws.sets / "tst.json")
    out_dir = ws.home / "out" / "tst"
    from mint import render
    render.render_cards(ws, ["Alpha"], set_path=st.path, dpi=300, out_dir=str(out_dir))  # a proof
    r = export.export(ws, st, ["Alpha"], ws.home / "mpc", dpi=800, card_back="none", log=lambda m: None)
    assert r["rendered"] == ["Alpha"]  # the 300 DPI one would have been blown up, so it was made again
    from mint.manifest import Manifest
    assert sorted(e["dpi"] for e in Manifest(out_dir).entries.values()) == [300, 1200]


@pytest.mark.render
def test_nothing_to_export_says_so(ws):
    st = sets.from_dict({"code": "TST", "name": "t", "cards": {"Alpha": {"number": 1}}})
    sets.save(ws.sets / "tst.json", st)
    st = sets.load(ws.sets / "tst.json")
    with pytest.raises(MintError, match="no plain render to export"):
        export.export(ws, st, ["Alpha"], ws.home / "mpc", render_missing=False, card_back="none")


@pytest.mark.render
def test_a_double_faced_card_prints_its_own_back(ws):
    """A transform card's back is rendered behind it at the same slot, instead of the common back."""
    dfc = synthetic_card(name="Delver Fixture // Aberrant Fixture", layout="transform", card_faces=[
        dict(name="Delver Fixture", type_line="Creature — Fixture", mana_cost="{U}", oracle_text="Flying",
             power="1", toughness="1", colors=["U"], artist="Nobody",
             illustration_id="aaaaaaaa-0000-0000-0000-000000000000", image_uris={"art_crop": "x"}),
        dict(name="Aberrant Fixture", type_line="Creature — Fixture", mana_cost="", oracle_text="Flying",
             power="3", toughness="2", colors=["U"], artist="Nobody",
             illustration_id="bbbbbbbb-0000-0000-0000-000000000000", image_uris={"art_crop": "x"}),
    ])
    dfc.pop("image_uris"), dfc.pop("illustration_id")  # a real double-faced card keeps art per face
    ws.cards_file.write_text(json.dumps(dfc) + "\n")
    for iid in ("aaaaaaaa-0000-0000-0000-000000000000", "bbbbbbbb-0000-0000-0000-000000000000"):
        Image.new("RGB", (284, 200), (40, 90, 160)).save(ws.art / (iid + ".jpg"))
    st = sets.from_dict({"code": "TST", "name": "t", "cards": {"Delver Fixture": {"number": 1}}})
    sets.save(ws.sets / "tst.json", st)
    st = sets.load(ws.sets / "tst.json")

    out = ws.home / "mpc"
    r = export.export(ws, st, st.names(), out, dpi=300, card_back="none", log=lambda m: None)
    assert r["fronts"] == 1 and r["backs"] == 1
    root = ET.fromstring((out / "cards.xml").read_text())
    front = root.find("fronts").find("card")
    back = root.find("backs").find("card")
    assert front.findtext("slots") == back.findtext("slots") == "0"   # the back goes behind its front
    assert back.findtext("id") == "images/001b Aberrant Fixture.png"
    assert (out / back.findtext("id")).is_file()


def test_an_image_many_slots_share_is_named_once():
    """<slots> is a comma-separated set to the desktop tool, so a back behind a whole set is one
    <card> with every slot on it -- not one upload per card that happens to be identical."""
    groups = export.group_slots([(0, "images/back SLV.png", "SLV back"), (1, "images/001b Aberrant.png", "Aberrant"),
                                 (2, "images/back SLV.png", "SLV back")])
    assert groups == [([0, 2], "images/back SLV.png", "SLV back"),
                      ([1], "images/001b Aberrant.png", "Aberrant")]
    xml = ET.fromstring(export.order_xml([(i, f"images/{i}.png", "x") for i in range(3)],
                                         [(0, "b.png", "B"), (2, "b.png", "B")], "back.png"))
    assert [c.findtext("slots") for c in xml.find("backs").findall("card")] == ["0,2"]


@pytest.mark.render
def test_a_union_order_prints_each_sets_own_back(ws):
    """Three decks in one batch: each set's cards carry that set's back, so the piles can be told
    apart afterwards. More than one image under <backs> is what puts MakePlayingCards into its
    different-backs mode, and that is all the order file has to say."""
    slv = sets.from_dict({"code": "SLV", "name": "s", "back": {"word": "SLIVERS", "symbol": "lgn"},
                          "cards": {"Alpha": {"number": 1}}})
    gsh = sets.from_dict({"code": "GSH", "name": "g", "back": {"word": "DINOS", "paper": ["#c2a25c"] * 4},
                          "cards": {"Alpha": {"number": 1}, "Beta, the Second": {"number": 2}}})
    plain = sets.from_dict({"code": "PLN", "name": "p", "cards": {"Beta, the Second": {"number": 9}}})
    for st in (slv, gsh, plain):
        sets.save(ws.sets / f"{st.code.lower()}.json", st)
    parts = [(sets.load(ws.sets / f"{st.code.lower()}.json"), st.names()) for st in (slv, gsh, plain)]

    out = ws.home / "mpc"
    r = export.export_union(ws, parts, out, dpi=300, log=lambda m: None)
    assert r["fronts"] == 4 and r["sets"] == ["SLV", "GSH", "PLN"]

    # a card two decks both play is two slots and prints twice: its copies want different backs
    # each image is named with its set's code: every set numbers from 001, so Alpha would otherwise
    # be written twice to the same path and one deck would get the other's card
    assert sorted(p.name for p in (out / "images").iterdir()) == [
        "GSH 001 Alpha.png", "GSH 002 Beta the Second.png", "PLN 009 Beta the Second.png",
        "SLV 001 Alpha.png", "back GSH.png", "back SLV.png", "back.png"]

    root = ET.fromstring((out / "cards.xml").read_text())
    assert root.find("details").findtext("quantity") == "4"
    assert root.find("details").findtext("bracket") == "18"
    backs = {c.findtext("id"): c.findtext("slots") for c in root.find("backs").findall("card")}
    assert backs == {"images/back SLV.png": "0", "images/back GSH.png": "1,2"}
    assert root.findtext("cardback") == "images/back.png"   # PLN has no block: slot 3 falls through
    for rel in backs | {root.findtext("cardback"): ""}:
        assert (out / rel).is_file()
    assert "different-backs mode" in (out / "README.txt").read_text()


@pytest.mark.render
def test_a_double_faced_card_keeps_its_own_back_in_a_union(ws):
    """The set's back is the fallback for its slots, not an override: a transform card still
    prints its own reverse."""
    dfc = synthetic_card(name="Delver Fixture // Aberrant Fixture", layout="transform", card_faces=[
        dict(name="Delver Fixture", type_line="Creature — Fixture", mana_cost="{U}", oracle_text="Flying",
             power="1", toughness="1", colors=["U"], artist="Nobody",
             illustration_id="aaaaaaaa-0000-0000-0000-000000000000", image_uris={"art_crop": "x"}),
        dict(name="Aberrant Fixture", type_line="Creature — Fixture", mana_cost="", oracle_text="Flying",
             power="3", toughness="2", colors=["U"], artist="Nobody",
             illustration_id="bbbbbbbb-0000-0000-0000-000000000000", image_uris={"art_crop": "x"}),
    ])
    dfc.pop("image_uris"), dfc.pop("illustration_id")
    ws.cards_file.write_text("\n".join(json.dumps(c) for c in [dfc, synthetic_card(
        name="Alpha", collector_number="1", illustration_id="00000001-0000-0000-0000-000000000000")]) + "\n")
    for iid in ("aaaaaaaa-0000-0000-0000-000000000000", "bbbbbbbb-0000-0000-0000-000000000000",
                "00000001-0000-0000-0000-000000000000"):
        Image.new("RGB", (284, 200), (40, 90, 160)).save(ws.art / (iid + ".jpg"))
    st = sets.from_dict({"code": "TST", "name": "t", "back": {"word": "TEST"},
                         "cards": {"Delver Fixture": {"number": 1}, "Alpha": {"number": 2}}})
    sets.save(ws.sets / "tst.json", st)
    st = sets.load(ws.sets / "tst.json")

    out = ws.home / "mpc"
    export.export_union(ws, [(st, st.names())], out, dpi=300, card_back="none", log=lambda m: None)
    backs = {c.findtext("id"): c.findtext("slots")
             for c in ET.fromstring((out / "cards.xml").read_text()).find("backs").findall("card")}
    assert backs == {"images/001b Aberrant Fixture.png": "0", "images/back TST.png": "1"}


def test_a_set_cannot_be_in_one_order_twice(ws):
    st = sets.from_dict({"code": "TST", "cards": {}})
    with pytest.raises(MintError, match="in the order twice"):
        export.export_union(ws, [(st, []), (st, [])], ws.home / "mpc")
    with pytest.raises(MintError, match="name at least one set"):
        export.export_union(ws, [], ws.home / "mpc")


@pytest.mark.render
def test_an_order_exports_its_counts_as_slots(ws):
    """Two copies of a card are two slots sharing one image -- <slots> is a set to the desktop
    tool -- and a card counted 0 is not in the order at all."""
    from mint import orders
    st = sets.from_dict({"code": "TST", "name": "t", "back": {"word": "TEST"},
                         "cards": {"Alpha": {"number": 1}, "Beta, the Second": {"number": 2}}})
    sets.save(ws.sets / "tst.json", st)
    o = orders.from_dict({"name": "october", "dpi": 300,
                          "sets": [{"code": "TST", "cards": {"Alpha": 3, "Beta, the Second": 0}}]})
    orders.save(ws.orders / "october.json", o)

    parts = o.parts(orders.loaded_sets(ws, o))
    assert parts[0][1] == ["Alpha", "Alpha", "Alpha"]
    out = ws.home / "mpc"
    r = export.export_union(ws, parts, out, dpi=300, card_back="none", log=lambda m: None)
    assert r["fronts"] == 3
    # three slots, one file: a second copy of a card is another slot, not another image
    assert sorted(p.name for p in (out / "images").iterdir()) == ["001 Alpha.png", "back TST.png"]
    root = ET.fromstring((out / "cards.xml").read_text())
    fronts = root.find("fronts").findall("card")
    assert len(fronts) == 1 and fronts[0].findtext("slots") == "0,1,2"
    assert root.find("details").findtext("quantity") == "3"
    assert [c.findtext("slots") for c in root.find("backs").findall("card")] == ["0,1,2"]

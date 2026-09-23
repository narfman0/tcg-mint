"""Pure functions of the frame: no browser, no network, no card file."""
import base64
import json
import re

from mint import frame
from tests.conftest import synthetic_card


class NoSymbols:
    """Stands in for frame.Symbols; the synthetic card has no mana symbols so it is never asked."""
    def data_uri(self, sym):
        raise AssertionError(f"unexpected symbol lookup {sym}")


def test_frame_picks_colour():
    assert frame.frame_for(synthetic_card(colors=["G"])) == frame.FRAMES["G"]
    assert frame.frame_for(synthetic_card(colors=["U", "R"])) == frame.FRAMES["gold"]
    assert frame.frame_for(synthetic_card(colors=[], type_line="Artifact")) == frame.FRAMES["artifact"]
    assert frame.frame_for(synthetic_card(colors=[], type_line="Land")) == frame.FRAMES["land"]
    assert frame.frame_for(synthetic_card(colors=[], type_line="Creature — Eldrazi")) == frame.FRAMES["C"]


def test_render_text_marks_reminder_and_flavor(card):
    html = frame.render_text(card, NoSymbols())
    assert '<span class="reminder">(Reminder text goes here.)</span>' in html
    assert '<p class="flavor">A <span class="upright">fixture</span> speaks.</p>' in html
    assert html.count("<p") == 3


def test_render_text_flavor_override(card):
    html = frame.render_text(card, NoSymbols(), flavor="Mine.")
    assert '<p class="flavor">Mine.</p>' in html
    assert "fixture" not in html


def test_esc():
    assert frame.esc("a < b & c > d") == "a &lt; b &amp; c &gt; d"


def test_font_link_is_empty_when_all_local():
    assert frame.font_link(["Beleren", "MPlantin"]) == ""
    assert frame.font_link(["Almendra", "Liberation Serif"]) == ""
    link = frame.font_link(["Beleren", "Cinzel", "EB Garamond", "Cinzel"])
    assert "fonts.googleapis.com" in link and "Beleren" not in link and link.count("Cinzel") == 1


def test_wizards_theme_never_links_google_fonts(card, art):
    title, body = frame.THEMES["wizards"]
    assert set(title + body) <= frame.LOCAL_FAMILIES
    html = frame.build_html(card, symbols=NoSymbols(), art_url="file://" + art, fonts_css=frame.local_fonts("/nowhere"))
    assert "fonts.googleapis.com" not in html and "Almendra-Bold.ttf" in html
    assert "fonts.googleapis.com" in frame.build_html(card, symbols=NoSymbols(), art_url="file://" + art, theme="cinzel")


def test_font_files_parse_names(tmp_path):
    for fn in ["Beleren-Bold.ttf", "Mplantin.ttf", "Mplantin-Italic.ttf", "Matrix-Bold.ttf", "notes.txt",
               "Almendra-Bold.ttf", "LiberationSerif-Regular.ttf", "LiberationSerif-Italic.ttf", "Tinos-Italic.ttf"]:
        (tmp_path / fn).write_bytes(b"")
    got = {(f, w, s) for f, w, s, _ in frame.font_files(tmp_path)}
    assert got == {("Beleren", 700, "normal"), ("MPlantin", 400, "normal"), ("MPlantin", 400, "italic"),
                   ("Matrix Bold", 700, "normal"), ("Almendra", 700, "normal"),
                   ("Liberation Serif", 400, "normal"), ("Liberation Serif", 400, "italic"), ("Tinos", 400, "italic")}


def test_font_files_keeps_multi_word_families_apart(tmp_path):
    """A face whose family is several words is its own family: filing "Beleren Small Caps" under
    Beleren would let a small-caps face stand in for the title face at weight 400."""
    for fn in ["Beleren-Bold.ttf", "Beleren Small Caps.ttf", "JaceBeleren-Bold.ttf",
               "MPlantin.ttf", "MPlantin-Bold.ttf", "MPlantin-Italic.ttf", "Montserrat-SemiBold.otf"]:
        (tmp_path / fn).write_bytes(b"")
    got = {(f, w, s) for f, w, s, _ in frame.font_files(tmp_path)}
    assert got == {("Beleren", 700, "normal"), ("Beleren Small Caps", 700, "normal"),
                   ("JaceBeleren", 700, "normal"), ("MPlantin", 400, "normal"),
                   ("MPlantin", 700, "normal"), ("MPlantin", 400, "italic"),
                   ("Montserrat", 700, "normal")}
    assert {"Beleren Small Caps", "JaceBeleren"} <= frame.LOCAL_FAMILIES  # never asked of Google


def test_packaged_fonts_are_present_with_licenses():
    faces = {(f, w, s): fn for f, w, s, fn in frame.font_files(frame.FONTS)}
    assert set(faces) == {("Almendra", 700, "normal"), ("Liberation Serif", 400, "normal"),
                          ("Liberation Serif", 400, "italic"), ("Montserrat", 700, "normal")}
    assert all(fn.stat().st_size > 10_000 and fn.read_bytes()[:4] in (b"\x00\x01\x00\x00", b"OTTO") for fn in faces.values())
    assert {f for f, *_ in faces} == set(frame.PACKAGED_FAMILIES) <= frame.LOCAL_FAMILIES
    assert all((frame.FONTS / n).exists() for n in ("Almendra-OFL.txt", "LiberationSerif-LICENSE.txt", "Montserrat-OFL.txt"))
    assert sum(fn.stat().st_size for fn in frame.FONTS.iterdir()) < 1_500_000


def test_local_fonts_workspace_first_then_packaged(tmp_path):
    (tmp_path / "Beleren-Bold.ttf").write_bytes(b"")
    (tmp_path / "Almendra-Bold.ttf").write_bytes(b"")
    rules = frame.local_fonts(tmp_path).split("\n")
    fams = [re.search(r"font-family: '(.*?)'", r).group(1) for r in rules]
    assert fams == ["Almendra", "Beleren", "Liberation Serif", "Liberation Serif", "Montserrat"]
    assert f"file://{tmp_path}/Almendra-Bold.ttf" in rules[0]  # yours, not the packaged one
    assert all(str(frame.FONTS) in r for r in rules[2:])
    assert "format('truetype'); font-weight: 400; font-style: italic;" in "\n".join(rules[2:])
    assert frame.local_fonts(tmp_path / "missing").count("@font-face") == 4


class FakeSymbols:
    """frame.Symbols without Scryfall: {T} -> data:sym/T."""
    def data_uri(self, sym):
        return "data:sym/" + sym.strip("{}")


def test_render_text_symbols_and_nowrap():
    html = frame.render_text(synthetic_card(type_line="Land — Fixture", oracle_text="{T}: Add {G}{G}.", flavor_text=None),
                             FakeSymbols())
    assert html == ('<p><span class="nowrap"><img class="sym" src="data:sym/T">:</span> Add '
                    '<span class="nowrap"><img class="sym" src="data:sym/G"><img class="sym" src="data:sym/G">.</span></p>')


def test_render_text_basic_land_gets_the_big_symbol():
    text = "({T}: Add {G}.)"
    basic = synthetic_card(type_line="Basic Land — Forest", oracle_text=text)
    assert frame.render_text(basic, FakeSymbols()) == '<p class="big-sym"><span class="pip"><img src="data:sym/G"></span></p>'
    # the same line on a non-basic land is ordinary reminder text
    html = frame.render_text(synthetic_card(type_line="Land — Fixture", oracle_text=text, flavor_text=None), FakeSymbols())
    assert html.startswith('<p><span class="reminder">(<span class="nowrap"><img class="sym" src="data:sym/T">:</span>')
    assert "big-sym" not in html


def test_render_text_reminder_inside_a_line_with_symbols():
    card = synthetic_card(oracle_text="Equip {2} ({2}: Fasten this to a creature you control.)", flavor_text=None)
    html = frame.render_text(card, FakeSymbols())
    assert html == ('<p>Equip <span class="nowrap"><img class="sym" src="data:sym/2"></span> '
                    '<span class="reminder">(<span class="nowrap"><img class="sym" src="data:sym/2">:</span> '
                    'Fasten this to a creature you control.)</span></p>')


def test_render_text_flavor_only():
    html = frame.render_text(synthetic_card(oracle_text="", flavor_text="Just *this*."), FakeSymbols())
    assert html == '<p class="flavor">Just <span class="upright">this</span>.</p>'
    assert frame.render_text(synthetic_card(oracle_text=None, flavor_text=None), FakeSymbols()) == ""


def test_render_text_escapes_markup():
    html = frame.render_text(synthetic_card(oracle_text="<b> & {T}", flavor_text="a < b"), FakeSymbols())
    assert "&lt;b&gt; &amp; " in html and '<p class="flavor">a &lt; b</p>' in html


def test_build_html_substitutes_everything(card, art):
    html = frame.build_html(card, symbols=NoSymbols(), art_url="file://" + art, set_size=12, maker="me", year="2026")
    assert "${" not in html and "$name" not in html
    assert "Test Subject" in html and "001/12 R" in html and "TST • EN" in html and "2/3" in html
    assert "2026 · me" in html


def test_footer_carries_the_printed_card_through(art):
    """The collector line is the original printing's: its number, its set, its language; an unknown
    set size prints '?', and a non-numeric number is left as it is."""
    card = synthetic_card(set="rvr", collector_number="40", lang="de")
    html = frame.build_html(card, symbols=NoSymbols(), art_url="file://" + art, maker="me", year="2026")
    assert "040/? R" in html and "RVR • DE" in html
    assert frame.collector_number(synthetic_card(collector_number="A1")) == "A1"
    assert frame.collector_number(synthetic_card(collector_number="12★")) == "12★"


ICON = '<svg version="1.0" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 800"><path d="M0 0h800v800H0z"/></svg>'


def test_set_symbol_is_the_icon_when_we_have_it():
    burst = frame.set_symbol("rare")
    assert "<polygon" in burst and 'viewBox="0 0 24 24"' in burst
    real = frame.set_symbol("rare", ICON)
    assert "<polygon" not in real and 'viewBox="0 0 800 800"' in real
    assert '<path fill="url(#g)" stroke="#000"' in real and frame.RARITY["rare"][1] in real
    assert "<polygon" in frame.set_symbol("rare", None)
    # the watermark is the same shape in flat black
    mark = base64.b64decode(frame.watermark_uri(ICON).split(",", 1)[1]).decode()
    assert "M0 0h800v800H0z" in mark and "url(#g)" not in mark


# Modern Horizons 2's icon, as Scryfall draws it: a 17-by-11 box, the path already filled black
MH2 = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 17 11">'
       '<path d="M7.245 4.52c-.08.315-.116.587-.109.815z" fill="#000" fill-rule="nonzero"/></svg>')


def test_set_symbol_edge_scales_with_the_icon_box():
    # the edge is a fraction of the rendered symbol, whatever units the icon was drawn in: a fixed
    # 14-unit stroke covered MH2's 17-unit icon in black
    assert 'stroke-width="14"' in frame.set_symbol("rare", ICON)
    mh2 = frame.set_symbol("rare", MH2)
    assert 'stroke-width="0.2975"' in mh2 and 'viewBox="0 0 17 11"' in mh2
    assert frame._edge_width("0 0 1600 1600") == 28 and frame._edge_width("0 0 100 76") == 1.75
    assert frame._edge_width("garbage") == 14
    # the icon's own fill goes, so the gradient is the only one on the path; fill-rule stays
    path = mh2[mh2.index("<path"):]
    assert path.count(' fill="') == 1 and 'fill="url(#g)"' in path and 'fill-rule="nonzero"' in path


def test_sets_cache_reads_from_disk_and_degrades_offline(tmp_path, monkeypatch):
    asked = []

    def unplugged(url, dest, timeout=300):
        asked.append(url)
        raise OSError("no network")
    monkeypatch.setattr(frame.scryfall, "fetch", unplugged)
    (tmp_path / "sets.json").write_text(json.dumps({"data": [
        {"code": "blb", "card_count": 398, "icon_svg_uri": "https://svgs.invalid/blb.svg"},
        {"code": "rvr", "card_count": 531, "icon_svg_uri": "https://svgs.invalid/rvr.svg"},
        {"code": "uma", "card_count": 254, "printed_size": 254},
        {"code": "h2r", "card_count": 16},
    ]}))
    # MTGJSON knows the main set's size where Scryfall's printed_size is missing; 0 means it doesn't
    (tmp_path / "setlist.json").write_text(json.dumps({"data": [
        {"code": "RVR", "baseSetSize": 291, "totalSetSize": 531}, {"code": "H2R", "baseSetSize": 0, "totalSetSize": 16}]}))
    (tmp_path / "sets").mkdir()
    (tmp_path / "sets" / "rvr.svg").write_text(ICON)
    s = frame.Sets(tmp_path)
    assert s.size("rvr") == 291 and s.size("uma") == 254 and s.size("h2r") == 16 and s.size("blb") == 398
    assert s.size("tst") is None and not asked
    assert s.icon("rvr") == ICON and s.icon("tst") is None
    assert s.icon("blb") is None and s.offline and asked == ["https://svgs.invalid/blb.svg"]
    assert s.icon("blb") is None and len(asked) == 1  # a failed fetch is not retried
    assert s.size("rvr") == 291  # what is on disk still answers
    bare = frame.Sets(tmp_path / "nowhere")  # no list at all: one attempt, then nothing known
    assert bare.size("blb") is None and bare.icon("blb") is None and len(asked) == 2


def test_ability_words_are_italic():
    assert frame.ability_word("Landfall — Whenever a land enters, draw.") == \
        '<span class="ability">Landfall</span> — Whenever a land enters, draw.'
    assert frame.ability_word("Choose one — Do a thing.") == "Choose one — Do a thing."
    council = frame.ability_word("Will of the council — Starting with you.")
    assert council.startswith('<span class="ability">Will of the council</span>')
    html = frame.render_text(synthetic_card(oracle_text="Threshold — Get big."), NoSymbols())
    assert '<p><span class="ability">Threshold</span> — Get big.</p>' in html


def test_faces():
    from mint.cards import faces, front_face
    assert [f["face_index"] for f in faces(synthetic_card())] == [0]
    dfc = {"name": "A // B", "layout": "transform", "set": "x", "collector_number": "1",
           "card_faces": [{"object": "card_face", "name": "A", "illustration_id": "a", "image_uris": {}},
                          {"object": "card_face", "name": "B", "illustration_id": "b", "image_uris": {}}]}
    for record in (dfc, front_face(dfc)):  # raw, or already flattened by Cards.find
        fs = faces(record)
        assert [(f["name"], f["illustration_id"], f["face_index"], f["full_name"]) for f in fs] == \
            [("A", "a", 0, "A // B"), ("B", "b", 1, "A // B")]
    split = {"name": "A // B", "layout": "split", "image_uris": {}, "card_faces": [{"name": "A"}, {"name": "B"}]}
    assert len(faces(split)) == 1


def test_frame_knobs_reach_the_page_as_custom_properties(card, art):
    from mint import sets
    assert frame.frame_css() == frame.frame_css(sets.Frame())
    assert "--watermark: 0.3;" in frame.frame_css({"watermark": 0.3})
    html = frame.build_html({**card, "rarity": "common"}, symbols=NoSymbols(), art_url="file://" + art,
                            frame_vars=frame.frame_css({"art_bevel": 0}))
    assert "--art-bevel: 0;" in html and 'class="stamp ' not in html      # a common: no foil stamp
    rare = frame.build_html({**card, "rarity": "mythic"}, symbols=NoSymbols(), art_url="file://" + art)
    assert 'class="stamp oval"' in rare and "--rarity-hi: #f7a23c" in rare and "--art-bevel: 1.0;" in rare


def test_mono_colour_lands_take_their_colours_pinline():
    """A land making one colour of mana (a basic, Boseiju) keeps the land band but its pinline and crown are
    the colour's, and its bar and box a greyed tint of the colour's; other lands stay plain."""
    forest = synthetic_card(colors=[], type_line="Basic Land — Forest", produced_mana=["G"])
    assert frame.land_tint(forest) == "G"
    assert frame.land_tint(synthetic_card(colors=[], type_line="Land", produced_mana=["W", "U", "B", "R", "G"])) is None
    assert frame.land_tint(synthetic_card(colors=[], type_line="Land", produced_mana=["C"])) is None
    assert frame.land_tint(synthetic_card(colors=["G"], type_line="Creature — Elf")) is None
    assert frame.mix("#000000", "#ffffff", 0.5) == "#808080"


def test_two_colour_frames():
    """A dual land, a fetch land and an all-hybrid spell take the two-colour frame, left to right the short way
    round the wheel; a three-colour land, a fetch for any basic, a gold spell and a mono land stay as they were."""
    land = dict(colors=[], type_line="Land")
    assert frame.frame_pair(synthetic_card(**land, produced_mana=["G", "U"])) == ("G", "U")
    assert frame.frame_pair(synthetic_card(**land, produced_mana=["B", "U"])) == ("U", "B")
    assert frame.frame_pair(synthetic_card(**land, produced_mana=["B", "W"])) == ("W", "B")
    assert frame.frame_pair(synthetic_card(**land, produced_mana=["R", "W"])) == ("R", "W")
    assert frame.frame_pair(synthetic_card(**land, produced_mana=["B", "G", "U"])) is None
    assert frame.frame_pair(synthetic_card(**land, produced_mana=["G"])) is None
    fetch = ("{T}, Pay 1 life, Sacrifice this land: Search your library for a Swamp or Forest card, "
             "put it onto the battlefield, then shuffle.")
    assert frame.frame_pair(synthetic_card(**land, oracle_text=fetch)) == ("B", "G")
    assert frame.frame_pair(synthetic_card(**land, oracle_text=fetch.replace("a Swamp or Forest", "a basic land"))) is None
    assert frame.frame_pair(synthetic_card(**land, oracle_text=fetch.replace("Swamp or Forest", "Forest or Forest"))) is None
    assert frame.frame_pair(synthetic_card(colors=["G", "W"], mana_cost="{1}{G/W}{G/W}")) == ("G", "W")
    assert frame.frame_pair(synthetic_card(colors=["B", "G"], mana_cost="{B/G}")) == ("B", "G")
    assert frame.frame_pair(synthetic_card(colors=["R", "W"], mana_cost="{R/W}{R}")) is None   # a plain pip: gold
    assert frame.frame_pair(synthetic_card(colors=["U", "R"], mana_cost="{U}{R}")) is None
    assert frame.frame_pair(synthetic_card(colors=["G"], mana_cost="{G/U}")) is None            # one colour
    assert frame.frame_pair(synthetic_card(colors=["B", "G", "U"], mana_cost="{B/G}{G/U}")) is None


def test_two_colour_frames_in_the_page(art):
    dual = synthetic_card(colors=[], type_line="Land", produced_mana=["G", "U"], power=None)
    html = frame.build_html(dual, symbols=NoSymbols(), art_url="file://" + art)
    assert 'class="card normal stamped stamp-oval pair design-m15 rarity-rare kind-land"' in html
    assert f"--pinline: {frame.FRAMES['G'][5]}" in html and f"--pinline-b: {frame.FRAMES['U'][5]}" in html
    assert f"--box: {frame.DUAL_BOX['G']}" in html and f"--box-b: {frame.DUAL_BOX['U']}" in html
    assert f"--bar: {frame.PAIR_BAR}" in html
    assert f"--frame: {frame.FRAMES['land'][0]}" in html and f"--frame-b: {frame.FRAMES['land'][0]}" in html
    class DotSymbols:
        def data_uri(self, sym):
            return "data:,"
    hybrid = synthetic_card(colors=["G", "W"], mana_cost="{G/W}")
    html = frame.build_html(hybrid, symbols=DotSymbols(), art_url="file://" + art)
    assert 'class="card normal stamped stamp-oval pair hybrid design-m15 rarity-rare kind-gold"' in html
    assert f"--frame: {frame.FRAMES['G'][0]}" in html and f"--frame-b: {frame.FRAMES['W'][0]}" in html
    assert f"--box: {frame.FRAMES['G'][4]}" in html and f"--box-b: {frame.FRAMES['W'][4]}" in html
    assert html.count("data:image/svg+xml;base64,") >= 2  # the two textures
    plain = frame.build_html(synthetic_card(), symbols=NoSymbols(), art_url="file://" + art)
    assert " pair " not in plain and " pair design" not in plain and f"--frame-b: {frame.FRAMES['U'][0]}" in plain


def test_designs_follow_the_printing_and_size_the_generation():
    assert frame.printed_design(synthetic_card()) == "m15"
    assert frame.printed_design(synthetic_card(frame_effects=["extendedart", "legendary"])) == "extended"
    assert frame.printed_design(synthetic_card(border_color="borderless")) == "borderless"
    # full art outranks borderless (a full-art card is usually borderless too), and both outrank extended art
    everything = synthetic_card(full_art=True, border_color="borderless", frame_effects=["extendedart"])
    assert frame.printed_design(everything) == "fullart"
    assert frame.printed_design(synthetic_card(textless=True, full_art=True)) == "textless"
    assert frame.printed_design(synthetic_card(frame="1997")) == "retro"
    assert frame.printed_design(synthetic_card(frame="1993")) == "retro"
    assert frame.printed_design(synthetic_card(frame="2003")) == "modern"
    assert frame.printed_design(synthetic_card(frame="2003", full_art=True)) == "fullart"  # the markers outrank the era
    for d in frame.DESIGNS:
        w, h = frame.generation_size(d, 1248 * 912)
        assert w % 32 == 0 and h % 32 == 0
        assert abs(w / h / frame.art_aspect(d) - 1) < 0.08
        assert abs(w * h / (1248 * 912) - 1) < 0.1
    assert frame.generation_size("fullart", 1248 * 912)[0] < frame.generation_size("fullart", 1248 * 912)[1]  # portrait
    assert frame.design_css("m15") == "" and "full art" in frame.design_css("fullart")


def test_build_html_carries_the_design(card, art):
    html = frame.build_html(card, symbols=NoSymbols(), art_url="file://" + art, design="fullart")
    assert "design-fullart" in html and "full art" in html
    import pytest
    with pytest.raises(ValueError):
        frame.build_html(card, symbols=NoSymbols(), art_url="file://" + art, design="showcase")


def test_stamp_follows_the_printing(card, art):
    assert frame.stamp_kind(synthetic_card(rarity="rare")) == "oval"  # no field: the M15 rare's oval
    assert frame.stamp_kind(synthetic_card(rarity="common")) is None
    assert frame.stamp_kind(synthetic_card(rarity="common", security_stamp="triangle")) == "triangle"
    assert frame.stamp_kind(synthetic_card(rarity="rare", security_stamp="arena")) is None
    assert frame.stamp_kind(synthetic_card(rarity="uncommon", security_stamp="acorn")) == "acorn"
    assert frame.stamp_kind(synthetic_card(rarity="rare", security_stamp="heart")) == "oval"
    page = lambda **o: frame.build_html(synthetic_card(**o), symbols=NoSymbols(), art_url="file://" + art)
    html = page(rarity="common", security_stamp="triangle")
    assert "stamped stamp-triangle" in html and '<div class="stamp triangle"></div>' in html
    html = page(rarity="uncommon", security_stamp="acorn")
    assert '<div class="stamp acorn"><img src="data:image/svg+xml;base64,' in html
    html = frame.build_html(synthetic_card(rarity="common"), symbols=NoSymbols(), art_url="file://" + art)
    assert '<div class="card normal design-m15 rarity-common kind-U">' in html and 'class="stamp ' not in html
    html = frame.build_html(synthetic_card(rarity="rare", layout="split", security_stamp="oval",
                                           card_faces=[dict(name="A", type_line="Instant", mana_cost="", oracle_text="x"),
                                                       dict(name="B", type_line="Instant", mana_cost="", oracle_text="y")]),
                            symbols=NoSymbols(), art_url="file://" + art)
    assert '<div class="card split design-m15 rarity-rare kind-U">' in html  # sideways cards carry none

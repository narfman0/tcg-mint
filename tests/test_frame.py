"""Pure functions of the frame: no browser, no network, no card file."""
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
    assert "fonts.googleapis.com" in frame.font_link(["Beleren", "Almendra"])


def test_font_files_parse_names(tmp_path):
    for fn in ["Beleren-Bold.ttf", "Mplantin.ttf", "Mplantin-Italic.ttf", "Matrix-Bold.ttf", "notes.txt"]:
        (tmp_path / fn).write_bytes(b"")
    got = {(f, w, s) for f, w, s, _ in frame.font_files(tmp_path)}
    assert got == {("Beleren", 700, "normal"), ("MPlantin", 400, "normal"), ("MPlantin", 400, "italic"),
                   ("Matrix Bold", 700, "normal")}


def test_build_html_substitutes_everything(card, art):
    html = frame.build_html(card, symbols=NoSymbols(), art_url="file://" + art, number=7, set_code="TST", set_size=12,
                            maker="me", maker_code="ME", year="2026")
    assert "${" not in html and "$name" not in html
    assert "Test Subject" in html and "007/12 R" in html and "2/3" in html and "ME · me · 2026" in html

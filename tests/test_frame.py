"""Pure functions of the frame: no browser, no network, no card file."""
from mint import render
from tests.conftest import synthetic_card


def test_frame_picks_colour():
    assert render.frame_for(synthetic_card(colors=["G"])) == render.FRAMES["G"]
    assert render.frame_for(synthetic_card(colors=["U", "R"])) == render.FRAMES["gold"]
    assert render.frame_for(synthetic_card(colors=[], type_line="Artifact")) == render.FRAMES["artifact"]
    assert render.frame_for(synthetic_card(colors=[], type_line="Land")) == render.FRAMES["land"]
    assert render.frame_for(synthetic_card(colors=[], type_line="Creature — Eldrazi")) == render.FRAMES["C"]


def test_render_text_marks_reminder_and_flavor(card):
    html = render.render_text(card, table={})
    assert '<span class="reminder">(Reminder text goes here.)</span>' in html
    assert '<p class="flavor">A <span class="upright">fixture</span> speaks.</p>' in html
    assert html.count("<p") == 3


def test_render_text_flavor_override(card):
    html = render.render_text(card, table={}, flavor="Mine.")
    assert '<p class="flavor">Mine.</p>' in html
    assert "fixture" not in html


def test_esc():
    assert render.esc("a < b & c > d") == "a &lt; b &amp; c &gt; d"


def test_font_link_is_empty_when_all_local():
    assert render.font_link(["Beleren", "MPlantin"]) == ""
    assert "fonts.googleapis.com" in render.font_link(["Beleren", "Almendra"])


def test_build_html_substitutes_everything(card, art):
    html = render.build_html(card, "wizards", {}, 7, "TST", 12, {"art": art}, None)
    assert "${" not in html and "$name" not in html
    assert "Test Subject" in html and "007/12 R" in html and "2/3" in html

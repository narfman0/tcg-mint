"""Decklist parsing and `mint newset`: no card file, no network."""
from mint import newset, sets, workspace

DECK = """\
1 Alpha
2x Beta
1 Alpha
4 Forest
4 Forest

1 Cmdr One
# Sideboard
1 Gamma
"""


def test_read_decklist_commanders_first_and_header_stops(tmp_path):
    fn = tmp_path / "deck.txt"
    fn.write_text(DECK)
    assert newset.read_decklist(fn) == ["Cmdr One", "Alpha", "Beta", "Alpha", "Forest", "Forest"]


def test_read_decklist_without_blank_line_is_just_the_deck(tmp_path):
    fn = tmp_path / "deck.txt"
    fn.write_text("3 Alpha\n1x Beta\nnot a card line\n")
    assert newset.read_decklist(fn) == ["Alpha", "Beta"]


def test_newset_dedupes_numbers_and_updates_in_place(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("MINT_HOME", str(tmp_path))
    monkeypatch.setattr(workspace, "_default", None)
    deck = tmp_path / "deck.txt"
    deck.write_text(DECK)
    out = tmp_path / "sets" / "tst.json"

    newset.main(["--code", "TST", "--name", "Test Set", "--style", "ink", "--out", str(out), str(deck)])
    st = sets.load(out)
    assert list(st.cards) == ["Cmdr One", "Alpha", "Beta", "Forest"]  # duplicates dropped, commander first
    assert [c.number for c in st.cards.values()] == [1, 2, 3, 4]
    assert st.size == 4 and st.code == "TST" and st.style.name == "ink"
    assert "4 cards (4 new)" in capsys.readouterr().out

    # a rerun with an extra card keeps numbers and per-card edits, appends the new one
    st.cards["Alpha"].flavor = "kept"
    sets.save(out, st)
    deck.write_text(DECK.replace("1 Alpha\n2x Beta", "1 Delta\n1 Alpha\n2x Beta"))
    newset.main(["--code", "TST", "--name", "Test Set", "--out", str(out), str(deck)])
    st2 = sets.load(out)
    assert list(st2.cards) == ["Cmdr One", "Alpha", "Beta", "Forest", "Delta"]
    assert st2.cards["Delta"].number == 5 and st2.cards["Alpha"].flavor == "kept" and st2.size == 5
    assert st2.style == st.style  # --style not repeated, the block survives
    assert "5 cards (1 new)" in capsys.readouterr().out


def test_newset_default_out_is_under_the_workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("MINT_HOME", str(tmp_path))
    monkeypatch.setattr(workspace, "_default", None)
    deck = tmp_path / "deck.txt"
    deck.write_text("1 Alpha\n")
    newset.main(["--code", "ABC", "--name", "n", str(deck)])
    assert sets.load(tmp_path / "sets" / "abc.json").names() == ["Alpha"]

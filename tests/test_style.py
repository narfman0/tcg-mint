"""Style templates and private tiers: `mint style`, `mint newset --style/--private`, workspace discovery."""
import json

import pytest

from mint import newset, sets, style, workspace
from mint.errors import SetError


@pytest.fixture
def ws(tmp_path, monkeypatch):
    monkeypatch.setenv("MINT_HOME", str(tmp_path))
    monkeypatch.setattr(workspace, "_default", None)
    return workspace.default()


def make_set(ws, code, private=False, css=None, **style_over):
    st = sets.SetFile(code=code, name=code, style=sets.from_dict(
        {"code": "x", "style": {"name": "look", "prompt": "a look", "cfg": 4, **style_over}}).style)
    d = ws.sets / ws.PRIVATE if private else ws.sets
    sets.save(d / f"{code.lower()}.json", st)
    if css:
        (d / f"{code.lower()}.css").write_text(css)
    return sets.load(d / f"{code.lower()}.json")


def test_set_files_lists_shared_then_private_and_flags_them(ws):
    make_set(ws, "ONE")
    make_set(ws, "TWO", private=True)
    files = ws.set_files()
    assert [p.name for p in files] == ["one.json", "two.json"]
    assert [ws.is_private(p) for p in files] == [False, True]


def test_save_writes_template_and_css_named_after_the_style(ws):
    st = make_set(ws, "NIV", css=".card { color: red }")
    p = style.save(ws, st)
    assert p == ws.styles / "look.json"
    body = json.loads(p.read_text())
    assert body == {"name": "look", "prompt": "a look", "cfg": 4}  # defaults stay out, explicit keys stay in
    assert p.with_suffix(".css").read_text() == ".card { color: red }"
    with pytest.raises(SetError, match="--force"):
        style.save(ws, st)
    assert style.save(ws, st, name="other", private=True) == ws.styles / "private" / "other.json"
    assert [(n, priv) for n, _, priv in style.templates(ws)] == \
        [("other", True), ("look", False), ("neon", False), ("ink", False), ("glass", False)]


def test_save_refuses_to_share_a_private_sets_style_without_force(ws):
    st = make_set(ws, "SECRET", private=True)
    with pytest.raises(SetError, match="private set"):
        style.save(ws, st)
    assert style.save(ws, st, private=True).parent.name == "private"
    assert style.save(ws, st, force=True) == ws.styles / "look.json"


def test_load_prefers_private_template_then_shared_then_builtin(ws):
    got, css = style.load(ws, "glass")
    assert got.name == "glass" and css == ""  # built-in
    (ws.styles).mkdir()
    (ws.styles / "glass.json").write_text(json.dumps({"name": "glass", "prompt": "shared", "seed_rule": "position"}))
    (ws.styles / "glass.css").write_text("/* glass */")
    assert style.load(ws, "glass")[0].prompt == "shared" and style.load(ws, "glass")[1] == "/* glass */"
    (ws.styles / "private").mkdir()
    (ws.styles / "private" / "glass.json").write_text(json.dumps({"name": "glass", "prompt": "mine"}))
    assert style.load(ws, "glass")[0].prompt == "mine"
    with pytest.raises(SetError, match="no style template"):
        style.load(ws, "nope")
    (ws.styles / "bad.json").write_text(json.dumps({"name": "bad", "prompt": "x", "typo": 1}))
    with pytest.raises(SetError, match="unknown key"):
        style.load(ws, "bad")


def test_newset_private_uses_template_and_its_css(ws, tmp_path):
    st = make_set(ws, "NIV", css=".card { color: red }")
    style.save(ws, st)
    deck = tmp_path / "deck.txt"
    deck.write_text("1 Alpha\n")
    newset.main(["--code", "XXX", "--name", "hush", "--style", "look", "--private", str(deck)])
    out = ws.sets / "private" / "xxx.json"
    new = sets.load(out)
    assert new.style.prompt == "a look" and new.style.cfg == 4 and new.css == ".card { color: red }"
    assert ws.is_private(out) and ws.set_files() == [ws.sets / "niv.json", out]
    with pytest.raises(SystemExit, match="no style template"):
        newset.main(["--code", "YYY", "--name", "n", "--style", "nope", str(deck)])


def test_cli_list_save_show(ws, capsys):
    make_set(ws, "NIV")
    style.main(["save", "NIV", "--as", "tpl"])
    assert (ws.styles / "tpl.json").exists()
    style.main(["list"])
    out = capsys.readouterr().out
    assert "tpl" in out and "built-in" in out
    style.main(["show", "tpl"])
    assert json.loads(capsys.readouterr().out)["name"] == "tpl"
    with pytest.raises(SystemExit, match="no set file or set code"):
        style.main(["save", "NOPE"])

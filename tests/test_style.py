"""Style templates: `mint style`, `mint newset --style`, workspace discovery."""
import json

import pytest

from mint import newset, sets, style, workspace
from mint.errors import SetError


@pytest.fixture
def ws(tmp_path, monkeypatch):
    monkeypatch.setenv("MINT_HOME", str(tmp_path))
    monkeypatch.setattr(workspace, "_default", None)
    return workspace.default()


def make_set(ws, code, css=None, **style_over):
    st = sets.SetFile(code=code, name=code, style=sets.from_dict(
        {"code": "x", "style": {"name": "look", "prompt": "a look", "cfg": 4, **style_over}}).style)
    d = ws.sets
    sets.save(d / f"{code.lower()}.json", st)
    if css:
        (d / f"{code.lower()}.css").write_text(css)
    return sets.load(d / f"{code.lower()}.json")


def test_set_files_lists_every_set_by_name(ws):
    make_set(ws, "TWO")
    make_set(ws, "ONE")
    assert [p.name for p in ws.set_files()] == ["one.json", "two.json"]


def test_save_writes_template_and_css_named_after_the_style(ws):
    st = make_set(ws, "NIV", css=".card { color: red }")
    p = style.save(ws, st)
    assert p == ws.styles / "look.json"
    body = json.loads(p.read_text())
    assert body == {"name": "look", "prompt": "a look", "cfg": 4}  # defaults stay out, explicit keys stay in
    assert p.with_suffix(".css").read_text() == ".card { color: red }"
    with pytest.raises(SetError, match="--force"):
        style.save(ws, st)
    assert style.save(ws, st, name="other") == ws.styles / "other.json"
    assert style.save(ws, st, force=True) == ws.styles / "look.json"
    assert [n for n, _ in style.templates(ws)] == ["look", "other", "neon", "ink", "glass"]


def test_load_prefers_a_template_file_over_a_builtin(ws):
    got, css = style.load(ws, "glass")
    assert got.name == "glass" and css == ""  # built-in
    (ws.styles).mkdir()
    (ws.styles / "glass.json").write_text(json.dumps({"name": "glass", "prompt": "shared", "seed_rule": "position"}))
    (ws.styles / "glass.css").write_text("/* glass */")
    assert style.load(ws, "glass")[0].prompt == "shared" and style.load(ws, "glass")[1] == "/* glass */"
    with pytest.raises(SetError, match="no style template"):
        style.load(ws, "nope")
    (ws.styles / "bad.json").write_text(json.dumps({"name": "bad", "prompt": "x", "typo": 1}))
    with pytest.raises(SetError, match="unknown key"):
        style.load(ws, "bad")


def test_newset_uses_template_and_its_css(ws, tmp_path):
    st = make_set(ws, "NIV", css=".card { color: red }")
    style.save(ws, st)
    deck = tmp_path / "deck.txt"
    deck.write_text("1 Alpha\n")
    newset.main(["--code", "XXX", "--name", "hush", "--style", "look", str(deck)])
    out = ws.sets / "xxx.json"
    new = sets.load(out)
    assert new.style.prompt == "a look" and new.style.cfg == 4 and new.css == ".card { color: red }"
    assert ws.set_files() == [ws.sets / "niv.json", out]
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

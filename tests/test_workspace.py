"""Workspace.from_env: mint.toml, the environment, and which wins."""
from mint.workspace import Workspace


def test_from_env_reads_mint_toml(tmp_path, monkeypatch):
    (tmp_path / "mint.toml").write_text(
        'maker = "me"\nmaker_code = "ME"\ncomfy_url = "http://box:1"\nprinter = "P1"\nunrelated = 1\n')
    monkeypatch.setenv("MINT_HOME", str(tmp_path))
    monkeypatch.delenv("MINT_CARDS", raising=False)
    monkeypatch.delenv("COMFY_URL", raising=False)
    ws = Workspace.from_env()
    assert ws.home == tmp_path.resolve()
    assert (ws.maker, ws.maker_code, ws.comfy_url, ws.printer) == ("me", "ME", "http://box:1", "P1")
    assert ws.cards_file == tmp_path.resolve() / "oracle-cards.jsonl"
    assert ws.fonts == ws.home / "fonts" and ws.sets == ws.home / "sets" and ws.path("a", "b") == ws.home / "a" / "b"


def test_comfy_root_is_optional_and_must_exist(tmp_path, monkeypatch):
    monkeypatch.setenv("MINT_HOME", str(tmp_path))
    monkeypatch.delenv("COMFY_ROOT", raising=False)
    assert Workspace.from_env().comfy_path is None  # unset: doctor then says what gets fetched
    (tmp_path / "mint.toml").write_text(f'comfy_root = "{tmp_path / "nowhere"}"\n')
    assert Workspace.from_env().comfy_path is None  # set but absent is the same as unset
    (tmp_path / "ComfyUI").mkdir()
    monkeypatch.setenv("COMFY_ROOT", str(tmp_path / "ComfyUI"))
    assert Workspace.from_env().comfy_path == tmp_path / "ComfyUI"


def test_env_overrides_file_and_locates_cards(tmp_path, monkeypatch):
    (tmp_path / "mint.toml").write_text('comfy_url = "http://box:1"\n')
    monkeypatch.setenv("MINT_HOME", str(tmp_path))
    monkeypatch.setenv("COMFY_URL", "http://other:2")
    monkeypatch.setenv("MINT_CARDS", str(tmp_path / "shared" / "cards.jsonl"))
    ws = Workspace.from_env()
    assert ws.comfy_url == "http://other:2"
    assert ws.cards_file == tmp_path / "shared" / "cards.jsonl"
    assert ws.maker == "narfman0"  # untouched keys keep their defaults


def test_defaults_without_config(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for k in ("MINT_HOME", "MINT_CARDS", "COMFY_URL"):
        monkeypatch.delenv(k, raising=False)
    ws = Workspace.from_env()
    assert ws.home == tmp_path.resolve()
    assert ws == Workspace(tmp_path.resolve(), tmp_path.resolve() / "oracle-cards.jsonl")
    # an explicit home beats MINT_HOME
    monkeypatch.setenv("MINT_HOME", "/nowhere")
    assert Workspace.from_env(tmp_path).home == tmp_path.resolve()

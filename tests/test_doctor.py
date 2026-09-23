"""`mint doctor`: the checks that do not need a server."""
import pytest

from mint import doctor, sets, style, workspace


@pytest.fixture
def ws(tmp_path, monkeypatch):
    monkeypatch.setenv("MINT_HOME", str(tmp_path))
    monkeypatch.delenv("COMFY_ROOT", raising=False)
    monkeypatch.setattr(workspace, "_default", None)
    return workspace.default()


def a_style(**over):
    return sets.from_dict({"code": "x", "style": {"name": "look", "prompt": "a look", **over}}).style


def test_styles_in_use_unpacks_templates(ws):
    """style.templates() yields (name, path). Unpacking it as a triple crashed `mint doctor`
    outright, and nothing caught it because the built-ins alone make the list non-empty."""
    assert style.templates(ws), "the built-ins should always be there"
    got = doctor.styles_in_use(ws)  # must not raise
    assert all(len(pair) == 2 for pair in got)


class Rec:
    def __init__(self):
        self.lines, self.failed = [], 0

    def ok(self, what, detail=""):
        self.lines.append(("ok", what, detail))

    def warn(self, what, detail=""):
        self.lines.append(("warn", what, detail))

    def fail(self, what, detail=""):
        self.failed += 1
        self.lines.append(("fail", what, detail))


def test_aux_ckpts_named_for_the_controls_in_use(ws):
    r = Rec()
    doctor.check_aux(ws, r, [("set A", a_style(control="depth"))])
    assert [w for _, w, _ in r.lines] == ["aux preprocessors"]
    detail = r.lines[0][2]
    assert "depth_anything_v2_vitl.pth" in detail and "sk_model.pth" not in detail


def test_aux_ckpts_include_dwpose_for_repose(ws):
    r = Rec()
    doctor.check_aux(ws, r, [("set A", a_style(control="canny", remix="repose"))])
    assert "dw-ll_ucoco_384_bs5.torchscript.pt" in r.lines[0][2] and "yolox_l.onnx" in r.lines[0][2]


def test_aux_ckpts_silent_when_no_control_needs_one(ws):
    r = Rec()
    doctor.check_aux(ws, r, [("set A", a_style(control="canny"))])
    assert r.lines == []  # core Canny needs no downloaded weights


def test_aux_ckpts_checked_on_disk_when_comfy_root_is_set(ws, tmp_path, monkeypatch):
    root = tmp_path / "ComfyUI"
    got = root / doctor.AUX_DIR / "depth-anything/Depth-Anything-V2-Large"
    got.mkdir(parents=True)
    (got / "depth_anything_v2_vitl.pth").write_bytes(b"")
    monkeypatch.setenv("COMFY_ROOT", str(root))
    monkeypatch.setattr(workspace, "_default", None)
    r = Rec()
    doctor.check_aux(workspace.default(), r, [("set A", a_style(control="depth")), ("set B", a_style(control="lineart"))])
    by_what = {what: (level, detail) for level, what, detail in r.lines}
    assert by_what["aux depth"][0] == "ok"
    assert by_what["aux lineart"][0] == "warn"  # sk_model*.pth are not there
    assert r.failed == 0  # the pack fetches a missing one itself; never a failure

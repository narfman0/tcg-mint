"""Check everything a render or a restyle needs, before a job fails halfway through.

    mint doctor

One line per check: the workspace and its card file, the fonts, a Chromium
launch, ComfyUI and the nodes each remix mode uses, every model file the
sets' styles and the templates name -- checkpoint, ControlNet, upscaler,
LoRAs -- against what that ComfyUI actually has, the Wan files and ffmpeg
that `mint animate` needs when a set has a motion block, and whether the
describer behind `mint describe` could take a call. Exits 1 when something a
job would need is missing; a warning (an old card file, a font substituted)
is reported and not counted.
"""
import datetime as dt
import sys

from . import comfy, describe, fonts, frame, loop, sets, style, wan, workspace
from .errors import MintError

# what each remix mode (restyle.py) asks ComfyUI for, beyond the core nodes
NODES = {
    "core":     ["CheckpointLoaderSimple", "CLIPTextEncode", "KSampler", "VAEEncode", "VAEDecode", "LoadImage", "ImageScale",
                 "Canny"],
    "controls": ["ControlNetLoader", "SetUnionControlNetType", "ControlNetApplyAdvanced"],
    "lineart / depth (controlnet_aux)": ["LineArtPreprocessor", "DepthAnythingV2Preprocessor"],
    "repose (DWPose)": ["DWPreprocessor"],
    "inspire (IP-Adapter plus)": ["IPAdapterUnifiedLoader", "IPAdapterAdvanced"],
    "enhance / ESRGAN": ["UpscaleModelLoader", "ImageUpscaleWithModel"],
}
# the style knobs that name a model file, and the node input that lists what ComfyUI has
MODELS = [("checkpoint", "CheckpointLoaderSimple", "ckpt_name"), ("controlnet", "ControlNetLoader", "control_net_name"),
          ("upscaler", "UpscaleModelLoader", "model_name")]

# The weights comfyui_controlnet_aux fetches for itself on first use, by the control each serves
# (restyle.preprocessor names them). These cannot be checked the way a checkpoint is: the node
# offers every name it knows how to download, present or not, so its options list is always full.
# They are only visible on disk, under the pack's own ckpts/ -- hence workspace.comfy_root.
AUX_CKPTS = {
    "depth":   [("depth-anything/Depth-Anything-V2-Large/depth_anything_v2_vitl.pth", "1.3 GB")],
    "lineart": [("lllyasviel/Annotators/sk_model.pth", "17 MB"), ("lllyasviel/Annotators/sk_model2.pth", "17 MB")],
    "openpose": [("yzd-v/DWPose/yolox_l.onnx", "207 MB"),
                 ("hr16/DWPose-TorchScript-BatchSize5/dw-ll_ucoco_384_bs5.torchscript.pt", "129 MB")],
}
AUX_DIR = "custom_nodes/comfyui_controlnet_aux/ckpts"


class Report:
    def __init__(self):
        self.failed = 0

    def ok(self, what, detail=""):
        print(f"  ok       {what:22} {detail}")

    def warn(self, what, detail=""):
        print(f"  warn     {what:22} {detail}")

    def fail(self, what, detail=""):
        self.failed += 1
        print(f"  MISSING  {what:22} {detail}")


def check_workspace(ws, r):
    r.ok("workspace", f"{ws.home}  (you are {ws.maker} / {ws.maker_code})")
    if not ws.cards_file.exists():
        r.fail("card file", f"{ws.cards_file}: run `mint cards`")
        return
    age = (dt.datetime.now() - dt.datetime.fromtimestamp(ws.cards_file.stat().st_mtime)).days
    size = ws.cards_file.stat().st_size / 1e6
    detail = f"{ws.cards_file.name}, {size:.0f} MB, {age} days old" + (": `mint cards` refreshes it" if age > 60 else "")
    (r.warn if age > 60 else r.ok)("card file", detail)


def check_fonts(ws, r):
    """Per face, not per family: a family present only as its roman still fakes its italic, and
    reporting that as ok is how a missing MPlantin italic hid behind a green check."""
    have, _ = fonts.report(ws.fonts)
    for family, (_, faces) in fonts.WANT.items():
        mine = have.get(family, {})
        gone = [f for f in faces if f not in mine]
        if not gone:
            r.ok("font " + family, fonts.shown(mine))
        elif mine:
            r.warn("font " + family, f"{fonts.shown(mine)}: no {', '.join(fonts.face(*f) for f in gone)}, "
                                     "which the browser fakes from the roman; fonts/README.md says where it is published")
        else:
            r.warn("font " + family, "substituted by the packaged fallback; fonts/README.md says where it is published")


def check_chromium(r):
    try:
        from .browser import Browser
        with Browser(dpi=72):
            pass
        r.ok("chromium", "launches (Playwright, channel chromium)")
    except Exception as e:  # any failure to launch is the finding
        r.fail("chromium", f"{e}".splitlines()[0][:120] + "  -- `playwright install chromium`")


def styles_in_use(ws):
    """[(where, Style)] for every set's style block and every template file."""
    out = []
    for p in ws.set_files():
        try:
            st = sets.load(p)
        except MintError as e:
            out.append((f"{p.name}: {e}", None))
            continue
        if st.style:
            out.append((f"set {st.code}", st.style))
    for name, p in style.templates(ws):  # (name, path); a built-in template has no path
        if p is not None:
            try:
                out.append((f"template {name}", style.load(ws, name)[0]))
            except MintError as e:
                out.append((f"{p.name}: {e}", None))
    return out


def check_comfy(ws, r, styles):
    server = comfy.client(ws)
    if not server.alive():
        if server.refused():
            r.fail("comfyui", f"{ws.comfy_url} refused the request: "
                   + ("the token (COMFY_TOKEN) is not the one it wants" if ws.comfy_token
                      else "it wants a bearer token; set COMFY_TOKEN"))
        else:
            r.fail("comfyui", f"nothing answers at {ws.comfy_url}; start it, or set COMFY_URL")
        return
    r.ok("comfyui", ws.comfy_url)
    have = server.nodes()
    for group, names in NODES.items():
        missing = [n for n in names if n not in have]
        if not missing:
            r.ok("nodes: " + group)
        else:
            say = r.fail if group in ("core", "controls", "enhance / ESRGAN") else r.warn
            say("nodes: " + group, "missing " + ", ".join(missing))
    for knob, node, inp in MODELS:
        avail = server.options(node, inp)
        if avail is None:
            r.warn("models: " + knob, f"{node} not there to ask")
            continue
        wanted = {}
        for where, st in styles:
            if st is not None:
                wanted.setdefault(getattr(st, knob), []).append(where)
        for fn, wheres in sorted(wanted.items()):
            (r.ok if fn in avail else r.fail)(f"{knob} {fn}",
                                              ("" if fn in avail else "not in ComfyUI; wanted by ") + ", ".join(wheres))
    loras = server.options("LoraLoader", "lora_name") or []
    for where, st in styles:
        for lora in (st.loras if st else []):
            have = lora["name"] in loras
            (r.ok if have else r.fail)(f"lora {lora['name']}", "" if have else f"not in ComfyUI; wanted by {where}")


def check_aux(ws, r, styles):
    """The preprocessor weights the node pack fetches for itself. A missing one is a warning, not
    a failure -- the pack downloads it at the moment it is first asked for, which only hurts a
    machine that is offline or in a hurry. Nothing here is checkable over HTTP (see AUX_CKPTS),
    so with no comfy_root set this says what will be fetched rather than whether it is there."""
    controls = set()
    for _, st in styles:
        if st is not None:
            controls.add(st.control)
            if st.remix == "repose":  # repose controls on DWPose whatever the style's own control
                controls.add("openpose")
    wanted = [(c, rel, size) for c in sorted(controls) for rel, size in AUX_CKPTS.get(c, [])]
    if not wanted:
        return
    root = ws.comfy_path
    if root is None:
        names = ", ".join(rel.rsplit("/", 1)[-1] for _, rel, _ in wanted)
        r.warn("aux preprocessors", f"fetched on first use, into {AUX_DIR}/: {names}. "
                                    "Set comfy_root in mint.toml to check them here")
        return
    for control, rel, size in wanted:
        p = root / AUX_DIR / rel
        if p.exists():
            r.ok(f"aux {control}", f"{rel.rsplit('/', 1)[-1]} ({size})")
        else:
            r.warn(f"aux {control}", f"{rel.rsplit('/', 1)[-1]} not in {AUX_DIR}/; "
                                     f"the pack fetches it ({size}) the first time {control} runs")


def motions_in_use(ws):
    """[(where, Motion)] for every set's motion block."""
    out = []
    for p in ws.set_files():
        try:
            st = sets.load(p)
        except MintError:
            continue
        if st.motion:
            out.append((f"set {st.code}", st.motion))
    return out


def check_motion(ws, r, motions):
    """What `mint animate` needs, asked only when a set has a motion block: the Wan nodes, each
    model file the blocks name (with where to fetch a missing one), and ffmpeg."""
    if not motions:
        return
    server = comfy.client(ws)
    if server.alive():
        have = server.nodes()
        missing = [n for n in wan.NODES if n not in have]
        (r.ok if not missing else r.fail)("nodes: animate (Wan)", "missing " + ", ".join(missing) if missing else "")
        for knob, (node, inp, folder) in wan.FILES.items():
            avail = server.options(node, inp)
            if avail is None:
                r.warn("models: " + knob, f"{node} not there to ask")
                continue
            wanted = {}
            for where, m in motions:
                wanted.setdefault(getattr(m, knob), []).append(where)
            for fn, wheres in sorted(wanted.items()):
                if fn in avail:
                    r.ok(f"{knob} {fn}")
                else:
                    r.fail(f"{knob} {fn}", f"not in ComfyUI models/{folder}; wanted by {', '.join(wheres)}; "
                                           f"fetch {wan.url(knob, fn)}")
    (r.ok if loop.have_ffmpeg() else r.fail)("ffmpeg", "" if loop.have_ffmpeg() else "not on PATH; animate encodes with it")


def check_describer(ws, r):
    """Whether `mint describe` could go out: a key for claude, a reachable Ollama otherwise. A
    describer nobody set up is a warning: no render or restyle needs it."""
    try:
        d = describe.Describer.from_workspace(ws)
    except MintError as e:
        r.warn("describer", str(e))
        return
    ok, why = d.ready()
    if not ok:
        r.warn("describer", f"{d.kind}: {why}")
    elif not d.alive():
        r.warn("describer", f"nothing answers at {d.url}; start Ollama, or set ollama_url")
    else:
        r.ok("describer", f"{d.kind} ({d.model})")


def check_sets(r, styles):
    for where, st in styles:
        if st is None:
            r.fail("set file", where)
    n = sum(1 for _, s in styles if s is not None)
    r.ok("styles", f"{n} style block(s) and template(s) parse; themes {', '.join(frame.THEMES)}")


def main(argv=None):
    if argv:
        sys.exit("mint doctor takes no arguments")
    ws = workspace.default()
    r = Report()
    check_workspace(ws, r)
    check_fonts(ws, r)
    styles = styles_in_use(ws)
    check_sets(r, styles)
    check_chromium(r)
    check_comfy(ws, r, styles)
    check_aux(ws, r, styles)
    check_motion(ws, r, motions_in_use(ws))
    check_describer(ws, r)
    print(f"\n{r.failed} thing(s) a job would miss" if r.failed else "\neverything a job needs is here")
    return 1 if r.failed else 0


if __name__ == "__main__":
    sys.exit(main())

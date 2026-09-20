"""Check everything a render or a restyle needs, before a job fails halfway through.

    mint doctor

One line per check: the workspace and its card file, the fonts, a Chromium
launch, ComfyUI and the nodes each remix mode uses, every model file the
sets' styles and the templates name -- checkpoint, ControlNet, upscaler,
LoRAs -- against what that ComfyUI actually has, and whether the describer
behind `mint describe` could take a call. Exits 1 when something a
job would need is missing; a warning (an old card file, a font substituted)
is reported and not counted.
"""
import datetime as dt
import sys

from . import comfy, describe, fonts, frame, sets, style, workspace
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
    have, missing = fonts.report(ws.fonts)
    for family in fonts.WANT:
        if family in have:
            r.ok("font " + family, ", ".join(have[family]))
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
    for name, p, _ in style.templates(ws):
        if p is not None:
            try:
                out.append((f"template {name}", style.load(ws, name)[0]))
            except MintError as e:
                out.append((f"{p.name}: {e}", None))
    return out


def check_comfy(ws, r, styles):
    server = comfy.Comfy(ws.comfy_url)
    if not server.alive():
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
    check_describer(ws, r)
    print(f"\n{r.failed} thing(s) a job would miss" if r.failed else "\neverything a job needs is here")
    return 1 if r.failed else 0


if __name__ == "__main__":
    sys.exit(main())

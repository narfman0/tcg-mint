"""Style templates: a set's art style, saved on its own so other sets can start from it.

    mint style list
    mint style save NIV [--as glass]
    mint style show glass

A template is a bare style block (the `style` object of a set file, see
sets.py) in styles/<name>.json, plus an optional styles/<name>.css holding the
frame rules that go with it, and an optional `frame` key inside the JSON: the
frame's dressing knobs (sets.Frame), so a template brings its whole look. `mint newset --style <name>` seeds a new set from
it; the three built-in recipes (neon, ink, glass) are the fallback when no
template has that name.

`save` takes a set code or a set file; the template is named after the set's
style unless --as says otherwise, and an existing template is only replaced
with --force.
"""
import argparse
import dataclasses
import json
import re
import sys
from pathlib import Path

from . import sets, workspace
from .errors import MintError, SetError


def builtin(name):
    from .newset import STYLES
    return STYLES.get(name)


def find(ws, name):
    """The template file for a name; None when there is none."""
    if name.endswith(".json") and Path(name).exists():
        return Path(name)
    p = ws.styles / f"{name}.json"
    return p if p.exists() else None


def read(ws, name):
    """A template as {"style": Style, "css": str, "frame": Frame | None} from its file or a built-in."""
    p = find(ws, name)
    if p is None:
        d = builtin(name)
        if d is None:
            raise SetError(f"no style template {name!r}: `mint style list` shows what there is")
        return {"style": sets.from_dict({"code": "x", "style": d}).style, "css": "", "frame": None}
    try:
        d = json.loads(p.read_text())
    except json.JSONDecodeError as e:
        raise SetError(f"{p}: not valid JSON ({e})") from None
    if not isinstance(d, dict):
        raise SetError(f"{p}: expected an object")
    frame = d.pop("frame", None)
    st = sets.from_dict({"code": "x", "style": d, **({"frame": frame} if frame is not None else {})}, str(p))
    css_fn = p.with_suffix(".css")
    return {"style": st.style, "css": css_fn.read_text() if css_fn.exists() else "", "frame": st.frame}


def load(ws, name):
    """A (Style, css) pair from a template file or a built-in recipe."""
    t = read(ws, name)
    return t["style"], t["css"]


def templates(ws):
    """[(name, path)] for every template on disk, then the built-ins (path None) not shadowed by one."""
    out = [(p.stem, p) for p in ws.style_files()]
    seen = {n for n, _ in out}
    from .newset import STYLES
    out += [(n, None) for n in STYLES if n not in seen]
    return out


def find_set(ws, ref):
    """A set by path or by code."""
    if Path(ref).exists():
        return sets.load(ref)
    for p in ws.set_files():
        try:
            st = sets.load(p)
        except MintError:
            continue
        if st.code.lower() == ref.lower():
            return st
    raise SetError(f"no set file or set code {ref!r}")


def save(ws, st, name=None, force=False):
    """Write a set's style (and css) as a template; returns the template path."""
    if st.style is None:
        raise SetError(f"{st.path}: this set has no style block to save")
    name = name or st.style.name
    p = ws.styles / f"{name}.json"
    if p.exists() and not force:
        raise SetError(f"{p} exists; --force replaces it")
    return write(ws, name, st.style, st.css, frame=st.frame)


def check_name(name):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", name or ""):
        raise SetError(f"a template name is letters, digits, - and _, not {name!r}")


def write(ws, name, style, css="", frame=None):
    """Write a Style (its css, and its frame knobs when any is off its default) as the template
    `name`. Returns the path."""
    check_name(name)
    p = ws.styles / f"{name}.json"
    ws.styles.mkdir(parents=True, exist_ok=True)
    body = sets._slim(dataclasses.asdict(style), sets.Style, style.explicit)
    body["name"] = name
    if frame is not None and sets._slim(dataclasses.asdict(frame), sets.Frame):
        body["frame"] = sets._slim(dataclasses.asdict(frame), sets.Frame)
    p.write_text(json.dumps(body, indent=2, ensure_ascii=False) + "\n")
    css_fn = p.with_suffix(".css")
    if css:
        css_fn.write_text(css)
    elif css_fn.exists():
        css_fn.unlink()
    return p


def delete(ws, name, path=None):
    """Remove a template file and its css; a built-in has no file and cannot be removed."""
    p = path or find(ws, name)
    if p is None:
        raise SetError(f"no template file for {name!r}" + (" (it is a built-in recipe)" if builtin(name) else ""))
    p.unlink()
    css_fn = p.with_suffix(".css")
    if css_fn.exists():
        css_fn.unlink()
    return p


def main(argv=None):
    ap = argparse.ArgumentParser(prog="mint style", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="every template, and the built-in recipes")
    s = sub.add_parser("save", help="save a set's style block as a template")
    s.add_argument("set", help="a set code (NIV) or a set file")
    s.add_argument("--as", dest="name", help="template name (default: the style's own name)")
    s.add_argument("--force", action="store_true", help="replace an existing template")
    sh = sub.add_parser("show", help="print a template or built-in as JSON")
    sh.add_argument("name")
    a = ap.parse_args(argv)
    ws = workspace.default()
    try:
        if a.cmd == "list":
            for name, p in templates(ws):
                print(f"  {name:12} {'built-in' if p is None else p}")
        elif a.cmd == "save":
            st = find_set(ws, a.set)
            p = save(ws, st, a.name, force=a.force)
            print(f"{p}: style {st.style.name} of {st.code}" + (" (+ css)" if st.css else ""))
        elif a.cmd == "show":
            t = read(ws, a.name)
            body = sets._slim(dataclasses.asdict(t["style"]), sets.Style, t["style"].explicit)
            if t["frame"] is not None:
                body["frame"] = dataclasses.asdict(t["frame"])
            print(json.dumps(body, indent=2))
            if t["css"]:
                print(t["css"], end="")
    except MintError as e:
        raise SystemExit(str(e)) from None


if __name__ == "__main__":
    sys.exit(main())

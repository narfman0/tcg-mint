"""Style templates: a set's art style, saved on its own so other sets can start from it.

    mint style list
    mint style save NIV [--as glass] [--private]
    mint style show glass

A template is a bare style block (the `style` object of a set file, see
sets.py) in styles/<name>.json, plus an optional styles/<name>.css holding the
frame rules that go with it. `mint newset --style <name>` seeds a new set from
it; the three built-in recipes (neon, ink, glass) are the fallback when no
template has that name. Templates in styles/private/ are found the same way
but git never sees them (`--private` writes there; workspace.py explains).

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
    """The template file for a name, private/ first; None when there is none."""
    if name.endswith(".json") and Path(name).exists():
        return Path(name)
    for p in (ws.styles / ws.PRIVATE / f"{name}.json", ws.styles / f"{name}.json"):
        if p.exists():
            return p
    return None


def load(ws, name):
    """A (Style, css) pair from a template file or a built-in recipe."""
    p = find(ws, name)
    if p is None:
        d = builtin(name)
        if d is None:
            raise SetError(f"no style template {name!r}: `mint style list` shows what there is")
        return sets.from_dict({"code": "x", "style": d}).style, ""
    try:
        d = json.loads(p.read_text())
    except json.JSONDecodeError as e:
        raise SetError(f"{p}: not valid JSON ({e})") from None
    style = sets.from_dict({"code": "x", "style": d}, str(p)).style
    css_fn = p.with_suffix(".css")
    return style, css_fn.read_text() if css_fn.exists() else ""


def templates(ws):
    """[(name, path, private)] for every template on disk, then the built-ins not shadowed by one."""
    out = [(p.stem, p, ws.is_private(p)) for p in ws.style_files()]
    seen = {n for n, _, _ in out}
    from .newset import STYLES
    out += [(n, None, False) for n in STYLES if n not in seen]
    return out


def find_set(ws, ref):
    """A set by path or by code, private sets included."""
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


def save(ws, st, name=None, private=False, force=False):
    """Write a set's style (and css) as a template; returns the template path."""
    if st.style is None:
        raise SetError(f"{st.path}: this set has no style block to save")
    name = name or st.style.name
    if not private and ws.is_private(st.path) and not force:
        raise SetError(f"{st.path} is a private set; saving its style to a shared template needs --force "
                       "(or --private to keep it out of git)")
    p = (ws.styles / ws.PRIVATE if private else ws.styles) / f"{name}.json"
    if p.exists() and not force:
        raise SetError(f"{p} exists; --force replaces it")
    return write(ws, name, st.style, st.css, private=private)


def check_name(name):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", name or ""):
        raise SetError(f"a template name is letters, digits, - and _, not {name!r}")


def write(ws, name, style, css="", private=False):
    """Write a Style (and its css) as the template `name` in the shared or the private tier,
    removing a copy in the other tier so the name lives in one place. Returns the path."""
    check_name(name)
    d = ws.styles / ws.PRIVATE if private else ws.styles
    p = d / f"{name}.json"
    d.mkdir(parents=True, exist_ok=True)
    body = sets._slim(dataclasses.asdict(style), sets.Style, style.explicit)
    body["name"] = name
    p.write_text(json.dumps(body, indent=2, ensure_ascii=False) + "\n")
    css_fn = p.with_suffix(".css")
    if css:
        css_fn.write_text(css)
    elif css_fn.exists():
        css_fn.unlink()
    other = (ws.styles if private else ws.styles / ws.PRIVATE) / f"{name}.json"
    if other.exists():
        delete(ws, name, other)
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
    s.add_argument("--private", action="store_true", help="write to styles/private/, which git ignores")
    s.add_argument("--force", action="store_true", help="replace an existing template")
    sh = sub.add_parser("show", help="print a template or built-in as JSON")
    sh.add_argument("name")
    a = ap.parse_args(argv)
    ws = workspace.default()
    try:
        if a.cmd == "list":
            seen = set()
            for name, p, private in templates(ws):
                where = "built-in" if p is None else str(p) + (" (private)" if private else "")
                if name in seen:
                    where += "  -- shadowed by the one above"
                seen.add(name)
                print(f"  {name:12} {where}")
        elif a.cmd == "save":
            st = find_set(ws, a.set)
            p = save(ws, st, a.name, private=a.private, force=a.force)
            print(f"{p}: style {st.style.name} of {st.code}" + (" (+ css)" if st.css else ""))
        elif a.cmd == "show":
            style, css = load(ws, a.name)
            print(json.dumps(sets._slim(dataclasses.asdict(style), sets.Style, style.explicit), indent=2))
            if css:
                print(css, end="")
    except MintError as e:
        raise SystemExit(str(e)) from None


if __name__ == "__main__":
    sys.exit(main())

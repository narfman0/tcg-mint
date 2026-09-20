"""Export a set as a static, read-only gallery: the workbench's Sets and Compare
views with the data and thumbnails baked in, for sharing a look at a set.

    mint gallery --set sets/mer.json [--out out/mer/gallery] [--width 640]

Writes index.html (the workbench page with a snapshot of the set inlined and
its actions disabled), the app's CSS and JS, and thumbnails of every image
the views show. Full-resolution files are not copied -- a set's variants run
to gigabytes -- so "open" in the gallery shows the largest thumbnail.
"""
import argparse
import json
import shutil
import sys
from pathlib import Path

from . import PKG, sets, workspace
from .errors import MintError
from .web import thumbs

STATIC = PKG / "web" / "static"


def export(ws, set_path, out, width=640):
    from .web.server import State, set_detail, style_fields
    st = sets.load(set_path)
    S = State(ws)
    detail = set_detail(S, st)
    out = Path(out)
    (out / "thumbs").mkdir(parents=True, exist_ok=True)
    paths = set()

    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if k in ("path", "crop") and isinstance(v, str) and v.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
                    paths.add(v)
                else:
                    walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(detail)
    index = {}
    for p in sorted(paths):
        for w in (320, 640, 1280):
            if w > width and w != 320:
                continue
            try:
                t = thumbs.thumbnail(ws, p, w)
            except (MintError, OSError):
                continue
            name = f"{t.stem}.jpg"
            shutil.copyfile(t, out / "thumbs" / name)
            index[f"{p}|{w}"] = "thumbs/" + name
    snapshot = {"workspace": {"home": str(ws.home), "maker": ws.maker, "maker_code": ws.maker_code,
                              "comfy": {"url": ws.comfy_url, "alive": False}, "cards": {"path": "", "count": 0},
                              "sets": [{"code": st.code, "name": st.name, "path": str(st.path), "size": st.size,
                                        "cards": len(st.cards), "style": st.style.name if st.style else None}],
                              "themes": [], "controls": list(sets.CONTROLS), "style_fields": style_fields(),
                              "current_job": None},
                "set": detail, "thumbs": index, "width": width}
    html = (STATIC / "index.html").read_text()
    html = html.replace('<script src="/static/app.js"></script>',
                        f"<script>window.MINT_STATIC = {json.dumps(snapshot)};</script>\n<script src=\"app.js\"></script>")
    html = html.replace('href="/static/app.css"', 'href="app.css"')
    # a static page installs nothing: drop the manifest and icon links, which would point at the server
    html = "\n".join(line for line in html.split("\n") if "manifest.webmanifest" not in line and "apple-touch-icon" not in line)
    (out / "index.html").write_text(html)
    shutil.copyfile(STATIC / "app.css", out / "app.css")
    shutil.copyfile(STATIC / "app.js", out / "app.js")
    return out, len(index)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="mint gallery", description=__doc__.split("\n\n")[0])
    ap.add_argument("--set", required=True)
    ap.add_argument("--out", help="directory (default out/<code>/gallery)")
    ap.add_argument("--width", type=int, default=640, help="largest thumbnail width (default 640)")
    a = ap.parse_args(argv)
    ws = workspace.default()
    try:
        st = sets.load(a.set)
        out = a.out or str(ws.home / "out" / st.code.lower() / "gallery")
        out, n = export(ws, a.set, out, a.width)
    except MintError as e:
        sys.exit(str(e))
    print(f"{out}/index.html: {len(st.cards)} cards, {n} thumbnails")


if __name__ == "__main__":
    main()

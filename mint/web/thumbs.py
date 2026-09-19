"""Thumbnails for the page: a 1200 DPI render is ~30 MB, an upscale bigger.

/img?path=...&w=600 resamples with Pillow and caches under .cache/thumbs/,
keyed on the file's path, size and mtime, so a regenerated variant gets a
fresh thumbnail. Only files inside the workspace are served.
"""
import hashlib
import os
from pathlib import Path

from PIL import Image

from ..errors import MintError

WIDTHS = (160, 320, 640, 1280)


def inside(ws, path):
    """The absolute path if it lies inside the workspace, else a MintError."""
    p = Path(path)
    if not p.is_absolute():
        p = ws.home / p
    p = p.resolve()
    home = ws.home.resolve()
    if home != p and home not in p.parents:
        raise MintError(f"not inside the workspace: {path}")
    return p


def thumbnail(ws, path, width):
    src = inside(ws, path)
    if not src.exists():
        raise MintError(f"no such file: {path}")
    width = min(WIDTHS, key=lambda w: (w < width, abs(w - width)))  # snap up to a standard size
    st = src.stat()
    key = hashlib.sha1(f"{src}|{st.st_size}|{int(st.st_mtime)}|{width}".encode()).hexdigest()[:16]
    out = ws.cache / "thumbs" / f"{key}.jpg"
    if out.exists():
        return out
    out.parent.mkdir(parents=True, exist_ok=True)
    im = Image.open(src)
    if im.format == "JPEG":
        im.draft("RGB", (width, width))  # decode at a reduced size straight away
    im = im.convert("RGB")
    im.thumbnail((width, width * 2), Image.LANCZOS)
    tmp = out.with_suffix(".part.jpg")
    im.save(tmp, "JPEG", quality=86, optimize=True)
    os.replace(tmp, out)
    return out

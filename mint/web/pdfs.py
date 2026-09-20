"""The PDFs a set has, for the workbench's pdf page.

A set's PDFs are the print runs under out/<set>/print/ and the one `mint impose` writes
to out/<set>.pdf. The page shows each page of one as an image -- pdftoppm renders it,
cached under .cache/pdfpages/ keyed on the file's path, size and mtime like the
thumbnails -- and offers the file itself: open in the browser's own viewer, download,
or *export*: a copy into the workspace's export_dir (the Desktop unless mint.toml says
otherwise), for another PDF app to print from.
"""
import hashlib
import os
import shutil
import subprocess
from pathlib import Path

from ..errors import MintError
from .thumbs import inside

WIDTHS = (400, 800, 1600)


def pdfs(ws, st, out_dir):
    """[{file, path, size, mtime, pages, origin}] for a set, newest first."""
    found = [(p, "print run") for p in (out_dir / "print").glob("*.pdf")]
    cli = ws.home / "out" / f"{st.code.lower()}.pdf"
    if cli.is_file():
        found.append((cli, "mint impose"))
    out = []
    for p, origin in found:
        s = p.stat()
        out.append({"file": p.name, "path": str(p), "size": s.st_size, "mtime": s.st_mtime,
                    "pages": page_count(p), "origin": origin})
    return sorted(out, key=lambda d: d["mtime"], reverse=True)


def find(ws, st, out_dir, file):
    """The listed PDF called `file`, or a MintError: names come from the list, never from a path."""
    for d in pdfs(ws, st, out_dir):
        if d["file"] == file:
            return Path(d["path"])
    raise MintError(f"{st.code} has no PDF {file}")


def page_count(path):
    """How many pages, from pdfinfo; None when poppler is not installed."""
    if not shutil.which("pdfinfo"):
        return None
    try:
        out = subprocess.run(["pdfinfo", str(path)], capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    for line in out.splitlines():
        if line.startswith("Pages:"):
            return int(line.split()[1])
    return None


def page_image(ws, path, n, width):
    """Page `n` (1-based) of the PDF at `path` as a PNG `width` pixels wide, cached."""
    src = inside(ws, path)
    if not src.is_file():
        raise MintError(f"no such file: {path}")
    if not shutil.which("pdftoppm"):
        raise MintError("pdftoppm is not installed (poppler-utils); open the PDF in the browser instead")
    width = min(WIDTHS, key=lambda w: (w < width, abs(w - width)))
    st = src.stat()
    key = hashlib.sha1(f"{src}|{st.st_size}|{int(st.st_mtime)}|{n}|{width}".encode()).hexdigest()[:16]
    out = ws.cache / "pdfpages" / f"{key}.png"
    if out.exists():
        return out
    out.parent.mkdir(parents=True, exist_ok=True)
    prefix = out.with_suffix("")  # pdftoppm -singlefile writes <prefix>.png
    r = subprocess.run(["pdftoppm", "-png", "-singlefile", "-f", str(n), "-l", str(n), "-scale-to", str(width),
                        str(src), str(prefix)], capture_output=True, text=True, timeout=120)
    if r.returncode or not out.exists():
        raise MintError(f"pdftoppm could not render page {n}: {r.stderr.strip() or 'no output'}")
    return out


def export(ws, src, force=False):
    """Copy a PDF into the export directory; an existing file there stays unless `force`.
    Returns the destination path."""
    dest_dir = ws.export_path
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise MintError(f"cannot create the export directory {dest_dir}: {e}") from None
    dest = dest_dir / src.name
    if dest.exists() and not force:
        raise FileExistsError(str(dest))
    tmp = dest.with_suffix(".pdf.part")
    shutil.copy2(src, tmp)
    os.replace(tmp, dest)
    return dest

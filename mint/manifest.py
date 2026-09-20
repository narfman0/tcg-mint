"""What a render was made from.

`mint render` writes out/<dir>/manifest.json beside its PNGs: for each file,
the card, its number and theme, the art it used (kind, path, variant hash),
the shrink-to-fit sizes, warnings, and a hash of the template plus set CSS.
Everything downstream -- the gallery, the workbench, regression diffs --
reads this instead of guessing from filenames.
"""
import datetime as dt
import hashlib
import json
import os
from pathlib import Path

from . import PKG


def frame_hash(set_css="", frame_vars=""):
    """Identifies the frame rules a render used: the template, the set's frame knobs and its CSS."""
    h = hashlib.sha1((PKG / "template.html").read_bytes())
    h.update(frame_vars.encode())
    h.update(set_css.encode())
    return h.hexdigest()[:8]


class Manifest:
    NAME = "manifest.json"

    def __init__(self, directory):
        self.path = Path(directory) / self.NAME
        self.data = {"entries": {}}
        if self.path.exists():
            try:
                self.data = json.loads(self.path.read_text())
            except json.JSONDecodeError:
                pass
        self.data.setdefault("entries", {})

    @property
    def entries(self):
        return self.data["entries"]

    def add(self, rendered, *, set_code=None, styled=False, fhash="", dpi=None):
        src = rendered.source
        self.entries[os.path.basename(rendered.out)] = {
            "card": rendered.name, "number": rendered.number, "theme": rendered.theme,
            "set": set_code, "styled": styled,
            "source": {"kind": src.kind, "path": str(src.path), "hash": src.hash,
                       "label": src.variant.label if src.variant else None},
            "art_filter": rendered.art_filter, "sizes": rendered.sizes, "warnings": rendered.warnings,
            "shrunk": rendered.shrunk, "frame": fhash, "dpi": dpi,
            "rendered_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        }

    def remove(self, filename):
        """Drop a render: the file beside the manifest and its entry."""
        self.entries.pop(filename, None)
        p = self.path.parent / filename
        if p.exists():
            p.unlink()

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.part")
        tmp.write_text(json.dumps(self.data, indent=1))
        os.replace(tmp, self.path)

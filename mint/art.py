"""Every image in the art cache, and which one a card should use.

Images are keyed by Scryfall's illustration_id, so the same art shared between
printings is fetched and processed once:

    art/<id>.jpg                         Scryfall's art crop (~626x457), fetched on demand
    art/scan_<id>.png                    Scryfall's full-card scan, for `mint calibrate` and cuts
    art/cut_<design>_<id>.png            that scan cut down to the picture a printing of `design` shows
    art/<id>/<label>-<hash>.png + .json  a *variant*: something ComfyUI made from another image
    art/<id>/described.json              what a describer read in the card's base image (describe.py)

A variant's sidecar records what it is: its kind (`restyle`, `enhance` or
`motion`), the recipe that made it, and the image it started from (`base`:
"crop" or another variant's hash). The hash is the recipe's (sets.recipe_hash),
so a changed knob is a new file next to the old one, never a silent overwrite
-- and every variant that exists can be compared in the workbench.

A `motion` variant (animate.py) is a clip of the art: its .png is the poster,
the loop's first frame, so everything that reads variants keeps working on a
still; the videos sit beside it with the same stem (`Variant.videos`) and go
with it when it is deleted. A poster is never a card's styled art.

`resolve()` answers "which file does this card render with, and why": an
override from the set file; else the variant matching the wanted style hash
(or an enhance of it, if one was made); else the newest enhance of the card's
base picture; else that picture itself.

That base picture is Scryfall's crop -- except for a card whose frame design
carries more art than the M15 window and whose *printing* is of that design
(a textless promo rendered textless). Scryfall's art_crop is the M15 window
whatever the printing is, so for those the picture is cut out of the full-card
scan instead (`cut`, frame.SCAN_CUT); its base name is "cut:<design>", so an
enhance or a restyle made from it records what it really started from.
"""
import dataclasses
import datetime as dt
import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from . import frame, scryfall
from .errors import MintError

HASH = re.compile(r"^[0-9a-f]{8}$")
# "cut", or "cut:<design>": the design's picture cut out of the printing's own scan rather than Scryfall's
# art_crop. A base may say either -- bare `cut` means whichever design the card renders in.
CUT_BASE = re.compile(r"^cut(?::([a-z0-9]+))?$")
VIDEO = (".webm", ".gif", ".apng", ".mp4")  # what may sit beside a motion variant's poster
DESCRIBED = "described.json"  # not a variant: the describer's reading of the card's base image


@dataclass
class Variant:
    label: str          # the style name, "enhance", or the motion block's name
    hash: str
    kind: str           # restyle | enhance | motion
    path: Path
    base: str           # "crop" or the hash of the variant this was made from
    recipe: dict
    illustration_id: str
    card: str = ""
    created: str = ""

    @property
    def sidecar(self):
        return self.path.with_suffix(".json")

    @property
    def videos(self):
        """The clips beside a motion variant's poster, sorted; empty for the other kinds."""
        if self.kind != "motion":
            return []
        return sorted(p for p in self.path.parent.glob(self.path.stem + ".*") if p.suffix in VIDEO)

    def to_dict(self):
        d = dataclasses.asdict(self)
        d["path"] = self.path.name
        return d


@dataclass
class ArtSource:
    path: Path
    kind: str                     # override | styled | enhance | cut | crop
    variant: Variant | None = None
    label: str = ""               # what a source that is not a variant is of: a cut's design
    art_hash: str | None = None   # the hash of a source that is not a variant; the variant's wins

    @property
    def url(self):
        return "file://" + str(Path(self.path).resolve())

    @property
    def hash(self):
        return self.variant.hash if self.variant else self.art_hash

    def describe(self):
        if self.variant:
            return f"{self.kind} {self.variant.label}-{self.variant.hash}"
        return f"{self.kind} {self.label}" if self.label else self.kind


def is_cut(base):
    """Whether a base names a scan cut rather than the crop, a variant hash or a restyle label."""
    return bool(base) and bool(CUT_BASE.match(base))


def cut_base(design):
    """The base name a cut is recorded under, so a recipe says which design's rectangle it started from."""
    return f"cut:{design}"


def cut_hash(design):
    """Eight hex characters naming the picture `cut` makes for a design. The rectangle is in it, so a
    render made from an earlier measurement of it goes stale when the measurement moves."""
    return hashlib.sha1(f"cut:{design}:{frame.scan_cut(design)}".encode()).hexdigest()[:8]


class Art:
    def __init__(self, directory):
        self.dir = Path(directory)

    # --- Scryfall's images ------------------------------------------------
    def crop(self, card, fetch=True):
        fn = self.dir / (card["illustration_id"] + ".jpg")
        if fetch and not fn.exists():
            scryfall.fetch(card["image_uris"]["art_crop"], fn)
        return fn

    def scan(self, card, fetch=True):
        fn = self.dir / ("scan_" + card["illustration_id"] + ".png")
        if fetch and not fn.exists():
            scryfall.fetch(card["image_uris"]["png"], fn)
        return fn

    def cut(self, card, design, fetch=True):
        """This design's picture cut out of the card's full-card scan, cached as art/cut_<design>_<id>.png.
        Returns the path the way `crop` does -- cut on first sight when `fetch`, the path either way -- or
        None when the design has no cut rectangle (frame.SCAN_CUT)."""
        rect = frame.scan_cut(design)
        if not rect:
            return None
        fn = self.dir / f"cut_{design}_{card['illustration_id']}.png"
        if fn.exists() or not fetch:
            return fn
        with Image.open(self.scan(card)) as im:
            # the scan is the bare card, 250 units wide, at calibrate.py's px-per-unit -- the one every
            # design's rectangle was measured in. A design that reaches into the bleed is clamped to the
            # scan: the printing simply has no picture out there.
            ppu = im.width / 250
            x, y, w, h = rect
            box = (max(0, round(x * ppu)), max(0, round(y * ppu)),
                   min(im.width, round((x + w) * ppu)), min(im.height, round((y + h) * ppu)))
            out = im.convert("RGB").crop(box)
        fn.parent.mkdir(parents=True, exist_ok=True)
        tmp = fn.with_name(fn.name + ".part")
        out.save(tmp, "PNG")
        os.replace(tmp, fn)
        return fn

    def cut_for(self, card, design):
        """The design this card's picture should be cut from its scan for, or None (frame.cut_design)."""
        return frame.cut_design(card, design)

    # --- variants -----------------------------------------------------------
    def variant_dir(self, card):
        return self.dir / card["illustration_id"]

    def variant_path(self, card, label, hash):
        return self.variant_dir(card) / f"{label}-{hash}.png"

    def variants(self, card):
        """Every variant of this card's art, newest first."""
        d = self.variant_dir(card)
        if not d.is_dir():
            return []
        out = []
        for sc in d.glob("*.json"):
            if sc.name == DESCRIBED:
                continue
            try:
                v = self._read(sc)
            except (json.JSONDecodeError, KeyError, TypeError):
                continue
            if v.path.exists():
                out.append(v)
        return sorted(out, key=lambda v: v.created, reverse=True)

    def _read(self, sidecar):
        d = json.loads(sidecar.read_text())
        d["path"] = sidecar.with_suffix(".png")
        return Variant(**d)

    def variant(self, card, hash):
        for v in self.variants(card):
            if v.hash == hash:
                return v
        return None

    def latest(self, card, label):
        """This card's newest restyle variant with a label, or None."""
        return next((v for v in self.variants(card) if v.kind == "restyle" and v.label == label), None)

    def delete(self, variant):
        """Remove a variant's image, sidecar and any clips beside it; other variants made from it
        keep their files."""
        for p in (variant.path, variant.sidecar, *variant.videos):
            if p.exists():
                p.unlink()

    def new_variant(self, card, label, kind, recipe, base, hash):
        """A Variant record for an image about to be made; write the file to .path, then record()."""
        return Variant(label, hash, kind, self.variant_path(card, label, hash), base, recipe,
                       card["illustration_id"], card["name"], dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"))

    def record(self, variant):
        variant.path.parent.mkdir(parents=True, exist_ok=True)
        variant.sidecar.write_text(json.dumps(variant.to_dict(), indent=1))
        return variant

    # --- descriptions -------------------------------------------------------
    def described(self, card):
        """The describer's newest reading of this card's base image ({description, subject, model,
        base, created}), or None. One record per illustration: a new reading replaces the old."""
        fn = self.variant_dir(card) / DESCRIBED
        if not fn.exists():
            return None
        try:
            return json.loads(fn.read_text())
        except json.JSONDecodeError:
            return None

    def describe(self, card, record):
        """Write a describer's reading beside the card's images; returns it with `created` set."""
        d = dict(record, card=card["name"], created=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"))
        self.variant_dir(card).mkdir(parents=True, exist_ok=True)
        (self.variant_dir(card) / DESCRIBED).write_text(json.dumps(d, indent=1))
        return d

    def enhanced(self, card, of="crop"):
        """The newest enhance variant made from `of` ("crop", "cut:<design>" or a variant hash), or None."""
        return next((v for v in self.variants(card) if v.kind == "enhance" and v.base == of), None)

    def base_path(self, card, base="crop", design=None):
        """The file a base (or pose) reference points at: the crop, a scan cut ("cut:<design>", or
        "cut" with `design` to say which), one of the card's variants by hash, or -- for a pose taken
        from anywhere -- a path to an image file."""
        if not base or base == "crop":
            return self.crop(card)
        if is_cut(base):
            named = CUT_BASE.match(base).group(1) or design
            if not named:
                raise MintError(f"{card['name']}: a 'cut' base needs the design -- spell it 'cut:textless'")
            p = self.cut(card, named)
            if p is None:
                raise MintError(f"{card['name']}: the {named} design has no scan cut measured "
                                f"(frame.SCAN_CUT); its picture is Scryfall's crop")
            return p
        if "/" in base or base.endswith((".png", ".jpg", ".jpeg", ".webp")):
            p = Path(base)
            if not p.is_file():
                raise MintError(f"{card['name']}: no image file {base}")
            return p
        v = self.variant(card, base)
        if not v:
            have = ", ".join(f"{x.label}-{x.hash}" for x in self.variants(card)) or "none"
            what = f"no {base!r} variant yet -- restyle that first" if not HASH.match(base) else f"no variant {base!r}"
            raise MintError(f"{card['name']}: {what} to start from (have {have})")
        return v.path

    # --- the decision ---------------------------------------------------------
    def resolve(self, card, override=None, style_hash=None, enhance=True, design=None, fetch=True):
        """The picture this card renders with. `design` is the frame design it renders in (sets.design_of):
        one whose own printings carry more art than Scryfall's crop takes its base from the scan instead.
        `fetch=False` answers without going to Scryfall -- the path may not be on disk yet, which is what
        the stale check and `check` want, since the answer is the same either way."""
        if override:
            return ArtSource(Path(override), "override")
        if style_hash:
            v = self.variant(card, style_hash)
            if v:
                e = self.enhanced(card, v.hash) if enhance else None
                return ArtSource(e.path, "styled", e) if e else ArtSource(v.path, "styled", v)
        cut = self.cut_for(card, design)
        if enhance:
            e = self.enhanced(card, cut_base(cut) if cut else "crop")
            if e:
                return ArtSource(e.path, "enhance", e)
        if cut:
            return ArtSource(self.cut(card, cut, fetch=fetch), "cut", label=cut, art_hash=cut_hash(cut))
        return ArtSource(self.crop(card, fetch=fetch), "crop")

"""Every image in the art cache, and which one a card should use.

Images are keyed by Scryfall's illustration_id, so the same art shared between
printings is fetched and processed once:

    art/<id>.jpg              Scryfall's art crop (~626x457), fetched on demand
    art/scan_<id>.png         Scryfall's full-card scan, for `mint calibrate`
    art/<id>.x4.png           `mint upscale`: 4x ESRGAN of the crop
    art/<id>.<style>.png      `mint restyle`: the set's style applied

`resolve()` answers "which file does this card render with, and why": an
override from the set file, else the styled image if one is asked for and
exists, else the upscale if it exists, else the crop.
"""
from dataclasses import dataclass
from pathlib import Path

from . import scryfall


@dataclass
class ArtSource:
    path: Path
    kind: str  # override | styled | upscale | crop

    @property
    def url(self):
        return "file://" + str(Path(self.path).resolve())


class Art:
    def __init__(self, directory):
        self.dir = Path(directory)

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

    def upscaled(self, card):
        return self.dir / (card["illustration_id"] + ".x4.png")

    def styled(self, card, style_name):
        return self.dir / f"{card['illustration_id']}.{style_name}.png"

    def resolve(self, card, override=None, style_name=None, upscale=True):
        if override:
            return ArtSource(Path(override), "override")
        if style_name:
            p = self.styled(card, style_name)
            if p.exists():
                return ArtSource(p, "styled")
        if upscale:
            p = self.upscaled(card)
            if p.exists():
                return ArtSource(p, "upscale")
        return ArtSource(self.crop(card), "crop")

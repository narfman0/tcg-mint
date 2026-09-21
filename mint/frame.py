"""The card frame: Scryfall record in, HTML out.

Layout is HTML/CSS (template.html) rendered by headless Chromium, so text
wrapping, italic reminder text and inline mana symbols come for free and the
frame is vector down to the last pixel. Everything here is pure: no browser,
no card file, and no network except the mana and expansion symbols and the
set lists behind the collector line, fetched into symbols/ once (Symbols, Sets)
and inlined as data URIs.

Fonts: drop Wizards' faces into fonts/ (Beleren-Bold.ttf, Mplantin.ttf,
Matrix-Bold.ttf ...) and the "wizards" theme picks them up by filename. The
closest open faces -- Almendra Bold for titles, Liberation Serif for rules
text, both OFL -- ship in the package (mint/fonts/), so the "wizards" theme
renders the same everywhere, offline, with no Google Fonts request. The other
themes still link Google Fonts.
"""
import base64
import json
import math
import re
import string
from pathlib import Path

from . import PKG, scryfall

# Font stacks: (title, body). Local families first, then Google Fonts fallbacks.
# The "wizards" stack is Beleren (M15 title face) -> Matrix Bold (the 2003-2014
# title face) -> Almendra (packaged); MPlantin (rules text) -> Liberation Serif
# (packaged; Times, which descends from Plantin). Every face in it is local.
THEMES = {
    "wizards":   (["Beleren", "Matrix Bold", "Almendra"], ["MPlantin", "Liberation Serif"]),
    "cinzel":    (["Cinzel"], ["EB Garamond"]),
    "cormorant": (["Cormorant SC"], ["Crimson Pro"]),
    "alegreya":  (["Alegreya SC"], ["Alegreya"]),
    "fell":      (["IM Fell English SC"], ["IM Fell English"]),
    "marcellus": (["Marcellus"], ["Libre Baskerville"]),
    "spectral":  (["Spectral SC"], ["Spectral"]),
}
# the open fallbacks that ship with the package (mint/fonts/), by family
FONTS = PKG / "fonts"
# the collector line's face: the real cards use a proprietary geometric sans (Relay); Montserrat is the open stand-in
PACKAGED_FAMILIES = {"Almendra": "title fallback", "Liberation Serif": "rules text fallback", "Montserrat": "collector line"}
LOCAL_FAMILIES = {"Beleren", "Matrix Bold", "MPlantin", *PACKAGED_FAMILIES}  # never ask Google for these

# M15 frame palette: (frame, frame-dark, bar, bar-edge, text box, pinline). Red and land sit a little off
# their scans' medians so that under their textures the band's median lands on the scan's. The frame, bar, text box and
# pinline -- the flat band of colour inside the textured frame that outlines every element and fills the
# gaps between them -- are medians sampled off Scryfall scans of recent printings (one per kind), the
# dark edge derived from the frame.
FRAMES = {
    "W": ("#d9d1ac", "#938e74", "#f1f1e8", "#8b8160", "#f2f3ea", "#f3f1eb"),
    "U": ("#3ca5da", "#287094", "#b2d4e6", "#34527a", "#dbeaf3", "#0077b0"),
    "B": ("#1d231c", "#13170f", "#b0a9a9", "#3a3637", "#e6e5ea", "#32322d"),
    "R": ("#a63a27", "#70271a", "#edc9c0", "#7b3d2c", "#f5e2e4", "#cc432b"),
    "G": ("#578265", "#3b5844", "#b8cdc3", "#2f5a3b", "#d3e5da", "#0f724a"),
    "gold": ("#c7b56d", "#877b4a", "#d0bf84", "#7d6530", "#f2ecd5", "#e9d37c"),
    "artifact": ("#91afbc", "#62777f", "#cedadf", "#5d6a70", "#cfdbdf", "#d8e1de"),
    "land": ("#bd9f86", "#806c5b", "#d3b978", "#6b5a42", "#f2edd5", "#e4d575"),
    "C": ("#e2dad6", "#9a9591", "#bcb3ae", "#767b71", "#b3afad", "#cfd0ce"),
}

# The two-colour frame (frame_pair): the pinline and text box run the left colour into the right, the bars
# a flat neutral grey whatever the pair. A dual land keeps the land band and takes these text-box tints, deeper
# than a mono land's grey (land_tint) -- medians off the RVR shocks and MH2 fetches, each colour from two or
# three scans; a hybrid spell's text box is the colour's own. The bar is the median of ten scans (#d1cac5 on
# RVR, #dbcfd3 on MH2, #d9d4d2 on UMA).
PAIR_BAR = "#d3cbc7"
DUAL_BOX = {"W": "#f5e4ba", "U": "#b2cde8", "B": "#aba2a3", "R": "#eb9f83", "G": "#bdd6c2"}
BASIC_TYPES = {"Plains": "W", "Island": "U", "Swamp": "B", "Mountain": "R", "Forest": "G"}

# set symbol fill by rarity: (edge colour, highlight colour)
RARITY = {
    "common": ("#000000", "#000000"),
    "uncommon": ("#6e7a82", "#dfe6ea"),
    "rare": ("#8a6a1c", "#f2dc8c"),
    "mythic": ("#9c2a10", "#f7a23c"),
}

# paper grain: a tiled fractal-noise SVG as grey around mid, overlaid (mix-blend-mode) on the flat fills so it
# textures without darkening them -- a black-only grain cost the bars and text box 6% of their brightness
NOISE = base64.b64encode(
    b"<svg xmlns='http://www.w3.org/2000/svg' width='160' height='160'>"
    b"<filter id='n'><feTurbulence type='fractalNoise' baseFrequency='.35' numOctaves='3' stitchTiles='stitch'/>"
    b"<feColorMatrix values='.33 .33 .33 0 0  .33 .33 .33 0 0  .33 .33 .33 0 0  0 0 0 0 .34'/></filter>"
    b"<rect width='100%' height='100%' filter='url(#n)'/></svg>"
).decode()
NOISE_URI = "data:image/svg+xml;base64," + NOISE

# The frame's texture: on a real M15 card the coloured band between the border and the boxes is a
# painted tile, one per colour and the same on every card of that colour -- marbled parchment on
# white, wet glass on blue, fissured stone on black, crackle on red, a cell network on green,
# brushed metal on artifacts and gold, sand on lands, grain on colorless. Ours are fractal noise
# shaped per kind into a tile of white highlights and black shadows (each with its own alpha), laid
# over the flat colour, so the palette above still sets the hue and the --frame-texture knob fades
# it. A fixed seed per kind keeps the same crack in the same place on every card, as the real tiles
# do. The tile is 256 SVG px drawn at 128 CSS px: a base frequency of 0.1 makes features about
# 5/100 in wide, the scale of the real veins and cells.
#   kind: (base frequency "x y", octaves, seed, shaping, highlight colour, shadow colour)
#   shaping (mode, width, gain, slope): "veins" = contour lines of the noise, `width` wide, light
#   (gain > 0) or dark (gain < 0), over a mottle of contrast `slope`; "tone" = the noise itself.
#   One octave gives smooth closed contours (cells, pebbles); more give the wandering veins of
#   marble and fissured stone. The colours are the medians of the lightest and darkest tenth of
#   each scan's band, so the tile keeps the frame's saturation instead of greying it.
TEXTURES = {
    "W":        ("0.09", 3, 3, ("veins", 0.07, 0.5, 0.5), "#e9e4c2", "#c9c099"),
    "U":        ("0.3 0.03", 2, 5, ("tone", 0, 0, 1.2), "#83d3f2", "#1679b9"),
    "B":        ("0.11", 2, 7, ("veins", 0.04, 0.7, 0.5), "#869591", "#040603"),
    "R":        ("0.25", 1, 11, ("veins", 0.06, 0.6, 0.5), "#e7a998", "#94271a"),
    "G":        ("0.22", 2, 13, ("veins", 0.04, 0.3, 0.9), "#98bda3", "#3b6748"),
    "gold":     ("0.25", 2, 17, ("tone", 0, 0, 0.7), "#f2e89d", "#7a6a42"),
    "artifact": ("0.22", 2, 19, ("tone", 0, 0, 1.2), "#c1dde8", "#4e6c78"),
    "land":     ("0.12", 2, 23, ("tone", 0, 0, 0.9), "#f9ecd4", "#46372a"),
    "C":        ("0.05", 1, 29, ("veins", 0.06, -0.45, 0.25), "#f5efe8", "#433446"),
}


def _shape(mode, width, gain, slope, steps=64):
    """feComponentTransfer table values: the noise (0-1, centred on .5) to the tile's tone,
    .5 = the flat colour untouched, 1 = full highlight, 0 = full shadow."""
    out = []
    for i in range(steps):
        x = i / (steps - 1)
        v = 0.5 + slope * (x - 0.5)
        if mode == "veins":  # the vein sits above the noise's median, so most of the band keeps the flat colour
            v += gain * math.exp(-((x - 0.62) / width) ** 2)
        out.append(f"{min(1, max(0, v)):.3f}")
    return " ".join(out)


def texture_uri(kind):
    """The frame texture tile for a frame kind, as an SVG data URI: a white layer whose alpha is
    the tone above .5 and a black layer whose alpha is the tone below it."""
    freq, octaves, seed, shaping, hi, lo = TEXTURES[kind]
    table = _shape(*shaping)
    def rgb(hexcol):
        return tuple(f"{int(hexcol[i:i + 2], 16) / 255:.3f}" for i in (1, 3, 5))
    def layer(name, rgb, alpha_row):
        return (f"<filter id='{name}' x='0' y='0' width='100%' height='100%' color-interpolation-filters='sRGB'>"
                f"<feTurbulence type='fractalNoise' baseFrequency='{freq}' numOctaves='{octaves}' seed='{seed}'"
                f" stitchTiles='stitch'/>"
                f"<feColorMatrix type='matrix' values='.33 .33 .33 0 0  .33 .33 .33 0 0  .33 .33 .33 0 0  0 0 0 0 1'/>"
                # fractalNoise only spans about .38-.61: stretch it to 0-1 about .5 before shaping
                f"<feComponentTransfer><feFuncR type='linear' slope='5' intercept='-2'/></feComponentTransfer>"
                f"<feComponentTransfer><feFuncR type='table' tableValues='{table}'/></feComponentTransfer>"
                f"<feColorMatrix type='matrix' values='0 0 0 0 {rgb[0]}  0 0 0 0 {rgb[1]}  0 0 0 0 {rgb[2]}  {alpha_row}'/>"
                f"</filter>")
    svg = ("<svg xmlns='http://www.w3.org/2000/svg' width='256' height='256'>"
           + layer("hi", rgb(hi), "2 0 0 0 -1") + layer("lo", rgb(lo), "-2 0 0 0 1")
           + "<rect width='100%' height='100%' filter='url(#lo)'/><rect width='100%' height='100%' filter='url(#hi)'/></svg>")
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()


# rules text starts at 12.6px and fit() shrinks it; below this it is hard to read in print
TEXT_FLOOR = 8.0


# --- mana symbols ---------------------------------------------------------
class Symbols:
    """Scryfall's symbol SVGs, cached in symbols/ and inlined as data URIs."""

    def __init__(self, directory):
        self.dir = Path(directory)
        self._table = None

    def table(self):
        if self._table is None:
            self.dir.mkdir(parents=True, exist_ok=True)
            idx = self.dir / "symbology.json"
            if not idx.exists():
                scryfall.fetch(scryfall.API + "/symbology", idx)
            self._table = {s["symbol"]: s["svg_uri"] for s in json.loads(idx.read_text())["data"]}
        return self._table

    def path(self, sym):
        fn = self.dir / (re.sub(r"[^A-Za-z0-9]", "_", sym) + ".svg")
        if not fn.exists():
            scryfall.fetch(self.table()[sym], fn)
        return fn

    # the fetched SVGs fill the red and blue discs duller than the printed cards; the scans say #F4A98C / #B4DEF7
    DISC = {b"#E49977": b"#F4A98C", b"#C1D7E9": b"#B4DEF7"}

    def data_uri(self, sym):
        svg = self.path(sym).read_bytes()
        for a, b in self.DISC.items():
            svg = re.sub(re.escape(a), b, svg, flags=re.I)
        return "data:image/svg+xml;base64," + base64.b64encode(svg).decode()


# --- sets ------------------------------------------------------------------
class Sets:
    """Scryfall's set list and expansion symbols, cached beside the mana symbols: symbols/sets.json
    is the whole list in one request, symbols/sets/<code>.svg each icon as it is first needed.
    Offline, what is not cached comes back None (the footer prints '?', the typebar the burst)
    rather than failing a render whose art is already on disk.

    The size a card prints after the slash is the main set's, not the count with every variant
    sheet; Scryfall's `printed_size` has it for a few sets, MTGJSON's `baseSetSize` (one more list,
    symbols/setlist.json) for nearly all, and `card_count` is the last resort."""

    MTGJSON = "https://mtgjson.com/api/v5/SetList.json"

    def __init__(self, directory):
        self.dir = Path(directory)
        self._table = None
        self._base = None
        self.offline = False

    def _fetch(self, url, dest):
        if self.offline:
            return False
        try:
            scryfall.fetch(url, dest)
        except OSError:
            self.offline = True
        return not self.offline

    def table(self):
        if self._table is None:
            self.dir.mkdir(parents=True, exist_ok=True)
            idx = self.dir / "sets.json"
            if not idx.exists() and not self._fetch(scryfall.API + "/sets", idx):
                return {}
            self._table = {s["code"]: s for s in json.loads(idx.read_text())["data"]}
        return self._table

    def base_sizes(self):
        """MTGJSON's baseSetSize by lower-case set code; empty when the list is not to be had."""
        if self._base is None:
            self.dir.mkdir(parents=True, exist_ok=True)
            fn = self.dir / "setlist.json"
            if not fn.exists() and not self._fetch(self.MTGJSON, fn):
                return {}
            self._base = {s["code"].lower(): s.get("baseSetSize") or 0 for s in json.loads(fn.read_text())["data"]}
        return self._base

    def size(self, code):
        """What the card prints after the slash, or None for a set nobody lists."""
        s = self.table().get(code) or {}
        return s.get("printed_size") or self.base_sizes().get(code) or s.get("card_count") or None

    def icon(self, code):
        """The set's expansion symbol as SVG text, or None for a set without one."""
        s = self.table().get(code)
        if not s or not s.get("icon_svg_uri"):
            return None
        fn = self.dir / "sets" / f"{code}.svg"
        if not fn.exists() and not self._fetch(s["icon_svg_uri"], fn):
            return None
        return fn.read_text()


# --- fonts ----------------------------------------------------------------
def font_files(fonts_dir):
    """(family, weight, style, path) for every font file in fonts/, keyed off
    the filename: Beleren-Bold.ttf -> Beleren 700; Mplantin-Italic.ttf -> MPlantin italic."""
    known = {"beleren": "Beleren", "matrix": "Matrix Bold", "mplantin": "MPlantin",
             "almendra": "Almendra", "liberationserif": "Liberation Serif", "tinos": "Tinos", "montserrat": "Montserrat"}
    out = []
    fonts_dir = Path(fonts_dir)
    if not fonts_dir.is_dir():
        return out
    for fn in sorted(fonts_dir.iterdir()):
        if fn.suffix.lower() not in (".ttf", ".otf", ".woff", ".woff2"):
            continue
        stem = fn.stem
        base = re.split(r"[-_ ]", stem)[0].lower()
        family = known.get(base, stem.split("-")[0])
        weight = 700 if re.search(r"bold", stem, re.I) or family == "Matrix Bold" else 400
        style = "italic" if re.search(r"italic", stem, re.I) else "normal"
        out.append((family, weight, style, fn))
    return out


def local_fonts(fonts_dir):
    """@font-face rules for whatever is in fonts/, then for the packaged fallbacks.
    A family the workspace provides is not repeated from the package, so your
    copy of a face always wins over ours."""
    fmt = {".ttf": "truetype", ".otf": "opentype", ".woff": "woff", ".woff2": "woff2"}
    faces = font_files(fonts_dir)
    mine = {family for family, _, _, _ in faces}
    faces += [f for f in font_files(FONTS) if f[0] not in mine]
    return "\n".join(
        f"@font-face {{ font-family: '{family}'; src: url('file://{fn}') format('{fmt[fn.suffix.lower()]}'); "
        f"font-weight: {weight}; font-style: {style}; }}"
        for family, weight, style, fn in faces)


def font_link(families):
    web = [f for f in families if f not in LOCAL_FAMILIES]
    fams = "&".join("family=" + f.replace(" ", "+") + ":ital,wght@0,300;0,400;0,700;1,400" for f in dict.fromkeys(web))
    # no stylesheet at all when every face is local: the render then makes no network request
    return f'<link rel="stylesheet" href="https://fonts.googleapis.com/css2?{fams}&display=swap">' if fams else ""


def stack(families):
    return ", ".join(f"'{f}'" for f in families) + ", serif"


# --- pieces ---------------------------------------------------------------
def frame_kind(card):
    """Which frame a card gets: its colour, gold, artifact, land or C (colorless), the keys of FRAMES."""
    t = card["type_line"]
    cols = card.get("colors") or []
    if "Land" in t and not cols:
        return "land"
    if len(cols) > 1:
        return "gold"
    if not cols:
        return "artifact" if "Artifact" in t else "C"
    return cols[0]


def frame_for(card):
    return FRAMES[frame_kind(card)]


def land_tint(card):
    """A land that makes one colour of mana (a basic, Boseiju, Shizo) keeps the land band but takes that
    colour's pinline and crown and a greyed tint of its bar and box: the colour, else None."""
    if frame_kind(card) != "land":
        return None
    made = [c for c in (card.get("produced_mana") or []) if c in "WUBRG"]
    return made[0] if len(made) == 1 else None


def frame_pair(card):
    """The two colours of a card that takes the two-colour frame, left then right, else None: a land that makes
    exactly two colours (a dual), a fetch land that finds two basic types, or a spell whose every coloured pip
    is hybrid. Left to right runs the short way round the colour wheel, as the guilds are named (WU, UB ... GW
    allied; WB, UR, BG, RW, GU enemy): Breeding Pool is green into blue, Watery Grave blue into black."""
    kind = frame_kind(card)
    if kind == "land":
        made = {c for c in (card.get("produced_mana") or []) if c in "WUBRG"}
        if len(made) != 2:
            m = re.search(r"search your library for an? (\w+) or (\w+) card", card.get("oracle_text") or "", re.I)
            if not m or any(w not in BASIC_TYPES for w in m.groups()):
                return None
            made = {BASIC_TYPES[w] for w in m.groups()}
            if len(made) != 2:
                return None
    elif kind == "gold":
        made = set(card["colors"])
        pips = re.findall(r"\{([^}]*)\}", card.get("mana_cost") or "")
        coloured = [p for p in pips if any(c in p for c in "WUBRG")]
        if len(made) != 2 or not coloured or any("/" not in p for p in coloured):
            return None
    else:
        return None
    a, b = sorted(made, key="WUBRG".index)
    return (a, b) if ("WUBRG".index(b) - "WUBRG".index(a)) % 5 <= 2 else (b, a)


def mix(a, b, t):
    """The hex colour t of the way from a to b."""
    ca = [int(a[i:i + 2], 16) for i in (1, 3, 5)]
    cb = [int(b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(ca, cb))


# The legendary crown's top edge, traced off a scan (Kykar, CMM) at 1/100 in steps from x = 9: the tips curl
# down at the ends, the side peaks rise to 9, the centre to 7, and the valleys sit on the bar's top edge (15).
CROWN_X0 = 9
CROWN = [
    18.5, 16.3, 14.5, 13.1, 11.8, 10.9, 10.7, 11.0, 11.5, 12.1, 12.7, 13.1, 13.4, 13.8, 14.1, 14.3, 14.5, 14.7, 14.9,
    15.0, 15.1, 15.1, 15.1, 15.2, 15.3, 15.4, 15.4, 15.4, 15.4, 15.4, 15.3, 14.6, 13.5, 12.2, 11.1, 10.2, 9.4, 9.2,
    9.4, 10.0, 10.5, 10.9, 11.3, 11.6, 12.1, 12.4, 12.8, 13.1, 13.3, 13.5, 13.8, 14.0, 14.2, 14.3, 14.5, 14.7, 14.8,
    14.9, 15.0, 15.1, 15.1, 15.1, 15.2, 15.2, 15.2, 15.1, 15.1, 15.1, 15.1, 15.0, 14.9, 14.7, 14.5, 14.3, 14.2, 14.0,
    13.8, 13.5, 13.3, 13.1, 12.9, 12.7, 12.4, 12.1, 11.7, 11.5, 11.3, 11.1, 10.7, 10.4, 10.1, 10.0, 10.3, 11.0, 11.5,
    11.6, 11.3, 10.8, 10.4, 10.1, 9.7, 9.4, 9.1, 8.8, 8.6, 8.4, 8.2, 8.0, 7.8, 7.6, 7.5, 7.4, 7.3, 7.1, 7.0, 7.0, 7.0,
    7.0, 7.1, 7.3, 7.4, 7.4, 7.5, 7.6, 7.8, 8.0, 8.2, 8.4, 8.6, 8.8, 9.1, 9.4, 9.7, 10.1, 10.4, 10.7, 11.2, 11.6,
    11.5, 10.7, 9.9, 9.7, 10.1, 10.4, 10.6, 10.8, 11.1, 11.4, 11.7, 12.1, 12.3, 12.5, 12.8, 13.0, 13.2, 13.4, 13.7,
    13.9, 14.0, 14.2, 14.3, 14.5, 14.7, 14.8, 14.9, 15.0, 15.1, 15.1, 15.1, 15.1, 15.1, 15.1, 15.1, 15.1, 15.1, 15.0,
    14.9, 14.8, 14.7, 14.5, 14.3, 14.2, 14.0, 13.8, 13.4, 13.1, 12.8, 12.4, 12.1, 11.7, 11.3, 10.8, 10.4, 10.0, 9.4,
    9.3, 9.6, 10.5, 11.5, 12.8, 14.1, 15.0, 15.4, 15.4, 15.4, 15.4, 15.4, 15.4, 15.3, 15.2, 15.1, 15.1, 15.0, 14.9,
    14.8, 14.7, 14.4, 14.2, 14.0, 13.7, 13.2, 12.8, 12.3, 11.8, 11.3, 10.7, 10.6, 11.2, 12.4, 13.8, 15.2, 17.0, 19.1,
]


# ... and its left side, (y, x) down from where the top edge meets it: the tip bulges out to 8 beside the bar's
# top, notches in to 10 at the bar's middle, flares to 7 below the bar and tucks back in under the art. The
# right side mirrors it about the card's centre (125).
CROWN_SIDE = [
    (10.5, 14.1), (11.0, 13.8), (11.5, 13.1), (12.0, 12.8), (12.5, 12.4), (13.0, 12.1), (13.5, 11.4), (14.0, 11.4),
    (14.5, 10.7), (15.0, 10.7), (15.5, 10.4), (16.0, 10.1), (16.5, 9.7), (17.0, 9.4), (17.5, 9.1), (18.0, 9.1),
    (18.5, 8.7), (19.0, 8.7), (19.5, 8.4), (20.0, 8.4), (20.5, 8.1), (21.0, 8.1), (21.5, 8.1), (22.0, 8.1), (22.5,
    8.1), (23.0, 8.1), (23.5, 8.4), (24.0, 8.4), (24.5, 8.7), (25.0, 8.7), (25.5, 9.1), (26.0, 9.4), (26.5, 9.4),
    (27.0, 9.7), (27.5, 10.1), (28.0, 10.1), (28.5, 9.7), (29.0, 9.7), (29.5, 9.4), (30.0, 8.1), (30.5, 7.7), (31.0,
    7.4), (31.5, 7.0), (32.0, 7.4), (32.5, 7.4), (33.0, 7.7), (33.5, 7.7), (34.0, 8.1), (34.5, 8.1), (35.0, 8.1),
    (35.5, 8.4), (36.0, 8.7), (36.5, 8.7), (37.0, 9.1), (37.5, 9.1), (38.0, 9.4), (38.5, 9.4), (39.0, 9.7), (39.5,
    10.1), (40.0, 10.4), (40.5, 10.4), (41.0, 11.1), (41.5, 11.1), (42.0, 11.7)
]


def crown_paths():
    """(fill, outline) CSS path() strings for the crown badge, in card units from the card's top-left: up the
    left side, along the traced top edge, down the mirrored right side, closed under the art; the outline is
    the same shape pushed out 1.3."""
    # below the bar the badge narrows into a flat tongue beside the art, x 13.5-16.6, down to 58 (the traced side
    # profile's last points had followed the tongue's shadow, not the tongue); the outline layer is that shadow, out
    # to 10.8, and the shape closes under the bar at the art's line
    foot = [(41.5, 11.5), (43.0, 13.0), (45.0, 13.5), (58.0, 13.5)]
    side = [(y, x) for y, x in CROWN_SIDE if y <= 40.5]

    def path(o, foot_o):
        top = [(CROWN_X0 + i, y - o) for i, y in enumerate(CROWN) if 14 <= CROWN_X0 + i <= 236]
        left = [(x - foot_o, y) for y, x in reversed(foot)] + [(x - o, y) for y, x in reversed(side)]
        right = [(250 - x + o, y) for y, x in side] + [(250 - x + foot_o, y) for y, x in foot]
        pts = left + top + right
        body = " ".join(f"L{x:.1f} {y:.1f}" for x, y in pts)
        return f"M{pts[0][0]:.1f} {pts[0][1]:.1f} {body} L233.4 58 L233.4 38.7 L16.6 38.7 L16.6 58 Z"
    return path(0, 0), path(1.3, 2.7)


def pt_plate(text):
    """The P/T plate: an inline SVG under the number. Traced off the scans: 41.7 x 20 with bowed ends, raised off
    the card, its rim a wall sloping 2.6 down into a flat face. Lit from the upper right: the wall ring is drawn
    four times, clipped to the four mitred wedges, so the top and right walls are dark along their whole length
    and the bottom and left walls light, each fading a little toward the face; a thin highlight along the outer
    top and right edges. Wider for a long number (10/10); the CSS sizes the box to match."""
    w = max(41.7, 6.6 * len(text) + 12)
    h, rx, dx, dy = 20.0, 3.4, 2.6, 2.4
    def shape(x0, y0, x1, y1, r):
        cy = (y0 + y1) / 2
        return (f"M{x0 + r:.1f} {y0:.1f} L{x1 - r:.1f} {y0:.1f} A{r:.1f} {cy - y0:.1f} 0 0 1 {x1 - r:.1f} {y1:.1f} "
                f"L{x0 + r:.1f} {y1:.1f} A{r:.1f} {cy - y0:.1f} 0 0 1 {x0 + r:.1f} {y0:.1f} Z")
    outer, face = shape(0, 0, w, h, rx), shape(dx, dy, w - dx, h - dy, rx - 1.2)
    ring = f"{outer} {face}"
    # the wedges, mitred from where the outer arc starts to where the face's arc starts (so the end walls take the
    # whole bowed end, not a straight-sided slice), and each wall's shade: (points, colour, opacity outer, at the face)
    a, b = rx, dx + rx - 1.2   # x of the outer arc's start and of the face arc's start, from either end
    walls = [
        (f"{a},0 {w - a},0 {w - b},{dy} {b},{dy}", "#000", .5, .32),
        (f"{w - a},0 {w},0 {w},{h} {w - a},{h} {w - b},{h - dy} {w - b},{dy}", "#000", .38, .22),
        (f"{a},{h} {w - a},{h} {w - b},{h - dy} {b},{h - dy}", "#fff", .5, .85),
        (f"{a},0 0,0 0,{h} {a},{h} {b},{h - dy} {b},{dy}", "#fff", .3, .55),
    ]
    defs, paths = [], []
    for i, (pts, col, o_out, o_in) in enumerate(walls):
        vert = i in (0, 2)
        x1, y1, x2, y2 = ("0", "0", "0", "1") if vert else ("0", "0", "1", "0")
        if i == 2:  # the bottom wall: its outer edge is at the bottom
            y1, y2 = "1", "0"
        if i == 1:  # the right wall: its outer edge is at the right
            x1, x2 = "1", "0"
        defs.append(f'<linearGradient id="w{i}" x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}">'
                    f'<stop offset="0" stop-color="{col}" stop-opacity="{o_out}"/>'
                    f'<stop offset="1" stop-color="{col}" stop-opacity="{o_in}"/></linearGradient>'
                    f'<clipPath id="c{i}"><polygon points="{pts}"/></clipPath>')
        paths.append(f'<path d="{ring}" fill-rule="evenodd" fill="url(#w{i})" clip-path="url(#c{i})"/>')
    svg = (f'<svg class="plate" viewBox="0 0 {w:.1f} {h:.1f}" width="{w:.1f}" height="{h:.1f}" style="width:{w:.1f}px">'
           f'<defs>{"".join(defs)}<linearGradient id="pte" x1="1" y1="0" x2="0" y2="1">'
           f'<stop offset="0" stop-color="#fff" stop-opacity=".7"/><stop offset=".5" stop-color="#fff" stop-opacity="0"/>'
           f'<stop offset="1" stop-color="#000" stop-opacity=".45"/></linearGradient></defs>'
           f'<path d="{outer}" fill="var(--plate)"/>{"".join(paths)}'
           f'<path d="{outer}" fill="none" stroke="url(#pte)" stroke-width=".9"/>'
           f'<path d="{face}" fill="var(--face)"/>'
           f'<path d="{face}" fill="none" stroke="#000" stroke-opacity=".22" stroke-width=".4"/>'
           f'</svg>')
    return f'<div class="pt" style="width:{w:.1f}px">{svg}<span>{esc(text)}</span></div>'


def crown_html():
    """The crown's two layers: the black outline under the gold fill, each clipped to its traced path."""
    fill, outline = crown_paths()
    return (f'<div class="crown-o" style="clip-path: path(\'{outline}\')"></div>'
            f'<div class="crown" style="clip-path: path(\'{fill}\')"></div>')


def _burst():
    """The set symbol's outline: an eight-point burst -- 'blasted' -- as SVG polygon points."""
    pts = []
    for i in range(16):
        r = 11 if i % 2 == 0 else 5.2
        a = math.pi * i / 8 - math.pi / 2
        pts.append(f"{12 + r * math.cos(a):.2f},{12 + r * math.sin(a):.2f}")
    return " ".join(pts)


def _icon_parts(icon_svg):
    """(viewBox, inner markup) of a Scryfall set icon: black paths in an 800-unit box."""
    m = re.search(r'viewBox="([^"]+)"', icon_svg)
    inner = re.sub(r"^.*?<svg[^>]*>|</svg>\s*$", "", icon_svg, flags=re.S)
    return (m.group(1) if m else "0 0 800 800"), inner


def set_symbol(rarity, icon_svg=None):
    """The expansion symbol filled by rarity: the set's own icon when we have it (Sets.icon),
    the burst -- 'blasted' -- when we don't."""
    edge, hi = RARITY.get(rarity, RARITY["common"])
    grad = (f'<defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{edge}"/>'
            f'<stop offset=".5" stop-color="{hi}"/><stop offset="1" stop-color="{edge}"/></linearGradient></defs>')
    if icon_svg:  # the icon's paths take the gradient and a thin black edge, as the printed symbol has
        box, inner = _icon_parts(icon_svg)
        inner = re.sub(r"<path\b", '<path fill="url(#g)" stroke="#000" stroke-width="14" paint-order="stroke"', inner)
        return f'<svg class="setsym" viewBox="{box}">{grad}{inner}</svg>'
    return (f'<svg class="setsym" viewBox="0 0 24 24">{grad}'
            f'<polygon points="{_burst()}" fill="url(#g)" stroke="#000" stroke-width="1"/></svg>')


def watermark_uri(icon_svg=None):
    """The symbol in flat black, as a data URI: the text box's watermark, faded by the knob."""
    if icon_svg:
        box, inner = _icon_parts(icon_svg)
    else:
        box, inner = "0 0 24 24", f'<polygon points="{_burst()}" fill="#000"/>'
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{box}">{inner}</svg>'
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()


def frame_css(knobs=None):
    """The frame's dressing knobs (a sets.Frame, a dict of some of them, or None for the defaults)
    as CSS custom properties on :root, ahead of the set's css so that can still override any."""
    import dataclasses

    from . import sets
    d = dataclasses.asdict(knobs) if dataclasses.is_dataclass(knobs) else {**dataclasses.asdict(sets.Frame()), **(knobs or {})}
    return ":root { " + " ".join(f"--{k.replace('_', '-')}: {v};" for k, v in d.items()) + " }"


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def smart(s):
    """Scryfall's straight quotes as the cards print them: ' -> ’, and " -> “ opening after a space, a bracket
    or a dash (or at the start), ” otherwise."""
    s = s.replace("'", "\u2019")
    opening = lambda m: (m.group(1) or "") + ("\u201c" if m.group(1) is not None else "\u201d")  # noqa: E731
    return re.sub(r'(^|[\s(\u2014\u2013-])"|"', opening, s)


# ability words: italic on the printed card, followed by an em dash (CR 207.2c)
ABILITY_WORDS = {
    "adamant", "addendum", "alliance", "battalion", "bloodrush", "celebration", "channel", "chroma", "cohort",
    "constellation", "converge", "corrupted", "council's dilemma", "coven", "delirium", "descend 4", "descend 8",
    "domain", "eerie", "eminence", "enrage", "fateful hour", "fathomless descent", "ferocious", "flurry", "formidable",
    "grandeur", "hellbent", "heroic", "imprint", "inspired", "join forces", "kinship", "landfall", "lieutenant",
    "magecraft", "max speed", "metalcraft", "morbid", "pack tactics", "paradox", "parley", "radiance", "raid", "rally",
    "renew", "revolt", "secret council", "spell mastery", "strive", "survival", "sweep", "tempting offer", "threshold",
    "undergrowth", "valiant", "void", "will of the council", "will of the planeswalkers",
}
ABILITY_WORD_RE = re.compile(r"^([A-Z][A-Za-z' 0-9]{2,30}?) — ")


def ability_word(p):
    """Wrap a leading ability word ("Landfall — ...") in an italic span."""
    m = ABILITY_WORD_RE.match(p)
    if m and m.group(1).lower() in ABILITY_WORDS:
        return f'<span class="ability">{m.group(1)}</span> — ' + p[m.end():]
    return p


ROMAN = r"(?:I|II|III|IV|V|VI|VII|VIII)"
CHAPTER_RE = re.compile(rf"^({ROMAN}(?:, {ROMAN})*) — ")
LOYALTY_RE = re.compile(r"^([+−\-]\d+|0): ")
LEVEL_RE = re.compile(r"^(\{[^}]+\})+: Level (\d+)$")


def layout_of(card):
    """Which frame a record wants: planeswalker, saga, class, adventure, split, battle, or normal.
    Transform and modal faces come through as normal (the back face is its own record) with their
    double-faced markers; a battle is a transform front that is a Battle."""
    t = card.get("type_line") or ""
    layout = card.get("layout") or "normal"
    if layout == "split":
        return "split"
    if layout == "adventure" and card.get("card_faces"):
        return "adventure"
    if "Planeswalker" in t and card.get("loyalty") is not None:
        return "planeswalker"
    if "Battle" in t and card.get("defense") is not None:
        return "battle"
    if "Saga" in t:
        return "saga"
    if "Class" in t and "Level" in (card.get("oracle_text") or ""):
        return "class"
    return "normal"


def render_text(card, symbols, flavor=None, layout="normal"):
    def syms(s):
        return re.sub(r"\{[^}]+\}", lambda m: f'<img class="sym" src="{symbols.data_uri(m.group(0))}">', esc(s))
    text = card.get("oracle_text") or ""
    # a basic land shows one big mana symbol instead of its "({T}: Add {G}.)" line
    m = re.fullmatch(r"\(\{T\}: Add (\{[WUBRGC]\})\.\)", text.strip())
    if card["type_line"].startswith("Basic") and m:
        return f'<p class="big-sym"><span class="pip"><img src="{symbols.data_uri(m.group(1))}"></span></p>'
    paras = []
    if layout == "planeswalker":  # each loyalty ability a row with its cost in a badge; static ones plain
        for p in text.split("\n") if text else []:
            m = LOYALTY_RE.match(p)
            if m:
                cost = m.group(1).replace("-", "−")
                kind = "up" if cost.startswith("+") else "down" if cost.startswith("−") else "zero"
                paras.append(f'<p class="loyal"><span class="lcost {kind}">{cost}</span><span>{syms(p[m.end():])}</span></p>')
            else:
                paras.append(f'<p class="static">{syms(ability_word(p))}</p>')
        return "".join(paras)
    if layout == "saga":  # the reminder line, then a row per chapter with its numerals in a badge
        for p in text.split("\n") if text else []:
            m = CHAPTER_RE.match(p)
            if m:
                nums = "".join(f"<b>{n}</b>" for n in m.group(1).split(", "))
                paras.append(f'<p class="chapter"><span class="numeral">{nums}</span><span>{syms(p[m.end():])}</span></p>')
            elif p.startswith("("):
                paras.append(f'<p class="reminder">{syms(p)}</p>')
            else:
                paras.append(f"<p>{syms(p)}</p>")
        return "".join(paras)
    if layout == "class":  # a band per level header, its cost as symbols; the abilities under each
        for p in text.split("\n") if text else []:
            m = LEVEL_RE.match(p)
            if m:
                cost = p[:p.index(":")]
                paras.append(f'<p class="level"><span>{syms(cost)}</span><b>Level {m.group(2)}</b></p>')
            elif p.startswith("("):
                paras.append(f'<p class="reminder">{syms(p)}</p>')
            else:
                paras.append(f"<p>{syms(ability_word(p))}</p>")
        return "".join(paras)
    for p in text.split("\n") if text else []:  # a vanilla card has no rules paragraph, only its flavor
        p = ability_word(syms(smart(p)))
        p = re.sub(r"\(([^)]*)\)", r'<span class="reminder">(\1)</span>', p)
        # a run of symbols plus any trailing punctuation wraps as one unit
        p = re.sub(r'((?:<img class="sym"[^>]*>)+[.,;:]?)', r'<span class="nowrap">\1</span>', p)
        paras.append(f"<p>{p}</p>")
    flavor = card.get("flavor_text") if flavor is None else flavor
    if flavor:
        # Scryfall marks the non-italic spans of flavor text (card names, emphasis) with *...*
        f = re.sub(r"\*([^*]+)\*", r'<span class="upright">\1</span>', esc(smart(flavor)))
        paras.append(f'<p class="flavor">{f.replace(chr(10), "<br>")}</p>')
    return "\n".join(paras)


# the paintbrush before the artist's name: a tip and a handle, in the line's colour
BRUSH = ('<svg class="brush" viewBox="0 0 20 12">'
         '<path d="M0 4.6 L5.5 4.6 L5.5 7.4 L0 7.4 Z M5.5 6 C8 1.2 14 0.2 20 2.2 C16 6.2 12 10 5.5 6 Z"'
         ' fill="currentColor"/></svg>')


def mana(symbols, cost):
    return "".join(f'<span class="pip"><img src="{symbols.data_uri(m)}"></span>' for m in re.findall(r"\{[^}]+\}", cost or ""))


# the double-faced markers: what sits before the name, and what the other face is called at the foot
DFC_ICON = {("transform", 0): "☀", ("transform", 1): "☾", ("modal_dfc", 0): "▲", ("modal_dfc", 1): "▼"}


# the pinline plate: the normal frame's four elements' pinlines, painted before them (template.html .pinlines)
PINLINES = "".join(f'<div class="pinlines {layer}">'
                   + "".join(f'<div class="pinline pl-{e}"></div>' for e in ("title", "art", "type", "text"))
                   + "</div>" for layer in ("shade", "light"))


def body_html(card, symbols, layout, flavor, pt_html, other_face=None, footer="", crown="", set_icon=None):
    """The markup inside .card for a layout: the bars, the art window, the text box and its
    companions. Split builds two half cards; battle and split lie sideways (the .turn box)."""
    ident = card.get("layout"), card.get("face_index", 0)
    icon = f'<span class="dfc">{DFC_ICON[ident]}</span>' if ident in DFC_ICON else ""
    def title(c):
        return (f'<div class="bar titlebar"><span class="name">{icon}{esc(smart(c["name"]))}</span>'
                f'<span class="cost">{mana(symbols, c.get("mana_cost"))}</span></div>')

    def typebar(c):
        return f'<div class="bar typebar"><span class="type">{esc(c["type_line"])}</span>{set_symbol(card["rarity"], set_icon)}</div>'

    other = ""
    if other_face:
        other_icon = DFC_ICON.get((card.get("layout"), 1 - card.get("face_index", 0)), "")
        other = (f'<div class="other-face"><span class="dfc">{other_icon}</span> '
                 f'{esc(other_face["name"])} <small>{esc(other_face["type_line"])}</small></div>')
    if layout == "split":
        halves = []
        for f in card["card_faces"][:2]:
            halves.append(f'<div class="half"><div class="frame"></div>{title(f)}<div class="art"></div>{typebar(f)}'
                          f'<div class="textbox">{render_text(f, symbols)}</div></div>')
        return f'<div class="turn">{"".join(halves)}</div>'
    if layout == "battle":
        return (f'<div class="turn"><div class="frame"></div>{title(card)}<div class="art"></div>{typebar(card)}'
                f'<div class="textbox" id="text">{render_text(card, symbols, flavor)}</div>'
                f'<div class="defense"><span>{esc(str(card.get("defense")))}</span></div>{other}{footer}</div>')
    if layout == "adventure":
        main, adv = card["card_faces"][0], card["card_faces"][1]
        box = (f'<div class="textbox adventure" id="text"><div class="adv">'
               f'<div class="adv-title"><span>{esc(adv["name"])}</span>'
               f'<span class="cost">{mana(symbols, adv.get("mana_cost"))}</span></div>'
               f'<div class="adv-type">{esc(adv["type_line"])}</div>'
               f'<div class="adv-text">{render_text(adv, symbols)}</div></div>'
               f'<div class="main">{render_text(main, symbols, flavor)}</div></div>')
        return f'{title(main)}<div class="art"></div>{typebar(main)}{box}{pt_html}'
    text = render_text(card, symbols, flavor, layout)
    if layout == "planeswalker":
        loyalty = f'<div class="loyalty"><span>{esc(str(card.get("loyalty")))}</span></div>'
        return (f'{PINLINES}{crown}{title(card)}<div class="art"></div>{typebar(card)}'
                f'<div class="textbox" id="text">{text}</div>{loyalty}{other}')
    if layout in ("saga", "class"):
        return f'{title(card)}<div class="art"></div><div class="textbox" id="text">{text}</div>{typebar(card)}{other}'
    cls = "has-pt" if pt_html else ""
    return (f'{PINLINES}{crown}{title(card)}<div class="art"></div>{typebar(card)}'
            f'<div class="textbox {cls}" id="text">{text}{other}</div>{pt_html}')


def collector_number(card):
    """The number as the card prints it: three digits for a plain number, as-is for A1 or 12★."""
    n = card["collector_number"]
    return f"{int(n):03d}" if n.isdigit() else esc(n)


def build_html(card, *, symbols, art_url, theme="wizards", fonts_css="", set_size=None, set_icon=None,
               flavor=None, art_filter=None, set_css="", frame_vars=None, maker="", year="", other_face=None):
    """The whole page for one card. `art_url` is the file:// URL of the image to show;
    `fonts_css` the @font-face rules for local faces (frame.local_fonts); `set_size` and `set_icon`
    the card's own set's printed size and expansion symbol SVG (frame.Sets), unknown when None;
    `frame_vars` the frame knobs as css (frame_css), the defaults when None; `other_face` the
    record of a double-faced card's other side, named at the foot of the text box."""
    title, body = THEMES[theme]
    kind = frame_kind(card)
    frame, frame_dark, bar, bar_edge, box, pinline = FRAMES[kind]
    tint = land_tint(card)
    if tint:  # measured off Boseiju (NEO): bar #c2cacc and box #bececa against green's #b8cdc3 / #d3e5da
        _, _, tbar, bar_edge, tbox, pinline = FRAMES[tint]
        bar, box = mix(tbar, "#ccc9c9", 0.5), mix(tbox, "#adb4b4", 0.5)
    pair = frame_pair(card)
    frame_b, box_b, pinline_b, kind_b = frame, box, pinline, kind  # the right-hand colour: the left's, off a pair
    if pair:
        a, b = pair
        bar, bar_edge, pinline, pinline_b = PAIR_BAR, mix(FRAMES[a][3], FRAMES[b][3], 0.5), FRAMES[a][5], FRAMES[b][5]
        if kind == "land":
            box, box_b = DUAL_BOX[a], DUAL_BOX[b]
        else:  # a hybrid spell: the band itself blends, its two textures cross-fading
            kind, kind_b = a, b
            frame, frame_b, box, box_b = FRAMES[a][0], FRAMES[b][0], FRAMES[a][4], FRAMES[b][4]
            frame_dark = mix(FRAMES[a][1], FRAMES[b][1], 0.5)
    rarity = card["rarity"]
    rarity_hi = RARITY[rarity][1] if rarity in ("uncommon", "rare", "mythic") else "transparent"
    layout = layout_of(card)
    pt = pt_plate(f'{card["power"]}/{card["toughness"]}') if card.get("power") is not None else ""
    legendary = "legendary" in (card.get("frame_effects") or []) or card["type_line"].startswith("Legendary")
    # the collector line carried through from the printed card: its number and set in a wide sans, the
    # artist in the title face as small caps after a brush; the studio's credit on the right, in the rules
    # serif, where the real cards put the year and the publisher
    footer_cls = " has-pt" if pt else ""  # the credit line drops to the bottom line beside a P/T box
    footer = (f'<div class="footer{footer_cls}"><span class="collector">'
              f'<b>{collector_number(card)}/{set_size or "?"} {card["rarity"][0].upper()}</b><br>'
              f'{esc(card["set"].upper())} • {esc(card.get("lang", "en").upper())} '
              f'{BRUSH}<span class="artist">{esc(card["artist"])}</span></span>'
              f'<span class="credit">{year} · {esc(maker)}</span></div>')
    turned = layout in ("split", "battle")  # sideways: no stamp or crown; a battle's footer rides inside the turned box
    stamped = rarity in ("rare", "mythic") and not turned
    tpl = string.Template((PKG / "template.html").read_text())
    return tpl.substitute(
        font_link=font_link(title + body), local_fonts=fonts_css,
        title_font=stack(title), body_font=stack(body),
        frame=frame, frame_dark=frame_dark, bar=bar, bar_edge=bar_edge, box=box, pinline=pinline,
        frame_b=frame_b, box_b=box_b, pinline_b=pinline_b,
        noise=NOISE_URI, texture=texture_uri(kind), texture_b=texture_uri(kind_b), set_css=set_css,
        legendary=" legendary" if legendary and not turned else "",
        pair=(" pair hybrid" if kind_b != kind else " pair") if pair else "",
        frame_vars=frame_vars or frame_css(),
        watermark=watermark_uri(set_icon), rarity_hi=rarity_hi, layout=layout,
        stamp='<div class="stamp"></div>' if stamped else "", stamped=" stamped" if stamped else "",
        body=body_html(card, symbols, layout, flavor, pt, other_face, footer if layout == "battle" else "",
                       crown=crown_html() if legendary and not turned else "", set_icon=set_icon),
        footer="" if layout == "battle" else footer,
        art=art_url, art_filter=art_filter or "none",
    )

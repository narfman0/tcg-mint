"""The card frame: Scryfall record in, HTML out.

Layout is HTML/CSS (template.html) rendered by headless Chromium, so text
wrapping, italic reminder text and inline mana symbols come for free and the
frame is vector down to the last pixel. Everything here is pure: no browser,
no card file, and no network except the mana-symbol SVGs, which are fetched
into symbols/ once and inlined as data URIs.

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
PACKAGED_FAMILIES = {"Almendra": "title fallback", "Liberation Serif": "rules text fallback"}
LOCAL_FAMILIES = {"Beleren", "Matrix Bold", "MPlantin", *PACKAGED_FAMILIES}  # never ask Google for these

# M15 frame palette: (frame, frame-dark, bar, bar-edge, text box)
FRAMES = {
    "W": ("#e8e1c9", "#b9ad86", "#f4efdf", "#8b8160", "#f8f5ea"),
    "U": ("#2160a3", "#143f6f", "#d7e3f1", "#34527a", "#e6edf5"),
    "B": ("#3b3a3c", "#1c1b1d", "#cfcbca", "#3a3637", "#dad6d3"),
    "R": ("#c8402d", "#7f2418", "#f2d9c8", "#7b3d2c", "#f5e6da"),
    "G": ("#237243", "#144428", "#d3e3cf", "#2f5a3b", "#e2ebde"),
    "gold": ("#d1b055", "#8f7228", "#f1e6bf", "#7d6530", "#f5eed6"),
    "artifact": ("#a6b3ba", "#67747b", "#e4eaed", "#5d6a70", "#ecf0f2"),
    "land": ("#b39a7c", "#7a6548", "#ece2d0", "#6b5a42", "#f2ebdd"),
    "C": ("#c9cdc4", "#8e948a", "#e8ebe4", "#767b71", "#f0f2ec"),
}

# set symbol fill by rarity: (edge colour, highlight colour)
RARITY = {
    "common": ("#000000", "#000000"),
    "uncommon": ("#6e7a82", "#dfe6ea"),
    "rare": ("#8a6a1c", "#f2dc8c"),
    "mythic": ("#9c2a10", "#f7a23c"),
}

# paper grain: a tiled fractal-noise SVG, layered at low alpha over the flat fills
NOISE = base64.b64encode(
    b"<svg xmlns='http://www.w3.org/2000/svg' width='160' height='160'>"
    b"<filter id='n'><feTurbulence type='fractalNoise' baseFrequency='.85' numOctaves='3' stitchTiles='stitch'/>"
    b"<feColorMatrix values='0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 .13 0'/></filter>"
    b"<rect width='100%' height='100%' filter='url(#n)'/></svg>"
).decode()
NOISE_URI = "data:image/svg+xml;base64," + NOISE

# rules text starts at 11.6px and fit() shrinks it; below this it is hard to read in print
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

    def data_uri(self, sym):
        return "data:image/svg+xml;base64," + base64.b64encode(self.path(sym).read_bytes()).decode()


# --- fonts ----------------------------------------------------------------
def font_files(fonts_dir):
    """(family, weight, style, path) for every font file in fonts/, keyed off
    the filename: Beleren-Bold.ttf -> Beleren 700; Mplantin-Italic.ttf -> MPlantin italic."""
    known = {"beleren": "Beleren", "matrix": "Matrix Bold", "mplantin": "MPlantin",
             "almendra": "Almendra", "liberationserif": "Liberation Serif", "tinos": "Tinos"}
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
def frame_for(card):
    t = card["type_line"]
    cols = card.get("colors") or []
    if "Land" in t and not cols:
        return FRAMES["land"]
    if len(cols) > 1:
        return FRAMES["gold"]
    if not cols:
        return FRAMES["artifact"] if "Artifact" in t else FRAMES["C"]
    return FRAMES[cols[0]]


def set_symbol(rarity):
    """An eight-point burst -- 'blasted' -- filled by rarity like a real expansion symbol."""
    pts = []
    for i in range(16):
        r = 11 if i % 2 == 0 else 5.2
        a = math.pi * i / 8 - math.pi / 2
        pts.append(f"{12 + r * math.cos(a):.2f},{12 + r * math.sin(a):.2f}")
    edge, hi = RARITY.get(rarity, RARITY["common"])
    return (f'<svg class="setsym" viewBox="0 0 24 24"><defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1">'
            f'<stop offset="0" stop-color="{edge}"/><stop offset=".5" stop-color="{hi}"/><stop offset="1" stop-color="{edge}"/>'
            f'</linearGradient></defs><polygon points="{" ".join(pts)}" fill="url(#g)" stroke="#000" stroke-width="1"/></svg>')


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def render_text(card, symbols, flavor=None):
    def syms(s):
        return re.sub(r"\{[^}]+\}", lambda m: f'<img class="sym" src="{symbols.data_uri(m.group(0))}">', esc(s))
    text = card.get("oracle_text") or ""
    # a basic land shows one big mana symbol instead of its "({T}: Add {G}.)" line
    m = re.fullmatch(r"\(\{T\}: Add (\{[WUBRGC]\})\.\)", text.strip())
    if card["type_line"].startswith("Basic") and m:
        return f'<p class="big-sym"><span class="pip"><img src="{symbols.data_uri(m.group(1))}"></span></p>'
    paras = []
    for p in text.split("\n") if text else []:  # a vanilla card has no rules paragraph, only its flavor
        p = syms(p)
        p = re.sub(r"\(([^)]*)\)", r'<span class="reminder">(\1)</span>', p)
        # a run of symbols plus any trailing punctuation wraps as one unit
        p = re.sub(r'((?:<img class="sym"[^>]*>)+[.,;:]?)', r'<span class="nowrap">\1</span>', p)
        paras.append(f"<p>{p}</p>")
    flavor = card.get("flavor_text") if flavor is None else flavor
    if flavor:
        # Scryfall marks the non-italic spans of flavor text (card names, emphasis) with *...*
        f = re.sub(r"\*([^*]+)\*", r'<span class="upright">\1</span>', esc(flavor))
        paras.append(f'<p class="flavor">{f}</p>')
    return "\n".join(paras)


def build_html(card, *, symbols, art_url, theme="wizards", fonts_css="", number=1, set_code="SET", set_size=1,
               flavor=None, art_filter=None, set_css="", maker="", maker_code="", year=""):
    """The whole page for one card. `art_url` is the file:// URL of the image to show;
    `fonts_css` the @font-face rules for local faces (frame.local_fonts)."""
    title, body = THEMES[theme]
    frame, frame_dark, bar, bar_edge, box = frame_for(card)
    cost = "".join(f'<span class="pip"><img src="{symbols.data_uri(m)}"></span>'
                   for m in re.findall(r"\{[^}]+\}", card.get("mana_cost") or ""))
    pt = f'<div class="pt"><span>{card["power"]}/{card["toughness"]}</span></div>' if card.get("power") is not None else ""
    legendary = "legendary" in (card.get("frame_effects") or []) or card["type_line"].startswith("Legendary")
    tpl = string.Template((PKG / "template.html").read_text())
    return tpl.substitute(
        font_link=font_link(title + body), local_fonts=fonts_css,
        title_font=stack(title), body_font=stack(body),
        frame=frame, frame_dark=frame_dark, bar=bar, bar_edge=bar_edge, box=box,
        noise=NOISE_URI, set_css=set_css,
        crown='<div class="crown-o"></div><div class="crown"></div>' if legendary else "",
        name=esc(card["name"]), cost=cost,
        art=art_url, art_filter=art_filter or "none",
        type_line=esc(card["type_line"]), set_symbol=set_symbol(card["rarity"]), set_code=set_code,
        text=render_text(card, symbols, flavor), pt=pt, text_class="has-pt" if pt else "",
        number=f"{number:03d}", set_size=set_size, rarity=card["rarity"][0].upper(),
        artist=esc(card["artist"]), maker_code=maker_code, maker=maker,
        date=year,
        orig_set=card["set"].upper(), orig_number=card["collector_number"],
    )

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


def _burst():
    """The set symbol's outline: an eight-point burst -- 'blasted' -- as SVG polygon points."""
    pts = []
    for i in range(16):
        r = 11 if i % 2 == 0 else 5.2
        a = math.pi * i / 8 - math.pi / 2
        pts.append(f"{12 + r * math.cos(a):.2f},{12 + r * math.sin(a):.2f}")
    return " ".join(pts)


def set_symbol(rarity):
    """The burst filled by rarity like a real expansion symbol."""
    edge, hi = RARITY.get(rarity, RARITY["common"])
    return (f'<svg class="setsym" viewBox="0 0 24 24"><defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1">'
            f'<stop offset="0" stop-color="{edge}"/><stop offset=".5" stop-color="{hi}"/><stop offset="1" stop-color="{edge}"/>'
            f'</linearGradient></defs><polygon points="{_burst()}" fill="url(#g)" stroke="#000" stroke-width="1"/></svg>')


def watermark_uri():
    """The burst in flat black, as a data URI: the text box's watermark, faded by the knob."""
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><polygon points="{_burst()}" fill="#000"/></svg>'
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
        p = ability_word(syms(p))
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


def mana(symbols, cost):
    return "".join(f'<span class="pip"><img src="{symbols.data_uri(m)}"></span>' for m in re.findall(r"\{[^}]+\}", cost or ""))


# the double-faced markers: what sits before the name, and what the other face is called at the foot
DFC_ICON = {("transform", 0): "☀", ("transform", 1): "☾", ("modal_dfc", 0): "▲", ("modal_dfc", 1): "▼"}


def body_html(card, symbols, layout, flavor, pt_html, other_face=None, footer=""):
    """The markup inside .card for a layout: the bars, the art window, the text box and its
    companions. Split builds two half cards; battle and split lie sideways (the .turn box)."""
    ident = card.get("layout"), card.get("face_index", 0)
    icon = f'<span class="dfc">{DFC_ICON[ident]}</span>' if ident in DFC_ICON else ""
    title = lambda c: f'<div class="bar titlebar"><span class="name">{icon}{esc(c["name"])}</span><span class="cost">{mana(symbols, c.get("mana_cost"))}</span></div>'  # noqa: E731
    typebar = lambda c: f'<div class="bar typebar"><span class="type">{esc(c["type_line"])}</span>{set_symbol(card["rarity"])}</div>'  # noqa: E731
    other = (f'<div class="other-face"><span class="dfc">{DFC_ICON.get((card.get("layout"), 1 - card.get("face_index", 0)), "")}</span> '
             f'{esc(other_face["name"])} <small>{esc(other_face["type_line"])}</small></div>') if other_face else ""
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
        box = (f'<div class="textbox adventure" id="text"><div class="adv"><div class="adv-title"><span>{esc(adv["name"])}</span>'
               f'<span class="cost">{mana(symbols, adv.get("mana_cost"))}</span></div><div class="adv-type">{esc(adv["type_line"])}</div>'
               f'<div class="adv-text">{render_text(adv, symbols)}</div></div><div class="main">{render_text(main, symbols, flavor)}</div></div>')
        return f'{title(main)}<div class="art"></div>{typebar(main)}{box}{pt_html}'
    text = render_text(card, symbols, flavor, layout)
    if layout == "planeswalker":
        loyalty = f'<div class="loyalty"><span>{esc(str(card.get("loyalty")))}</span></div>'
        return f'{title(card)}<div class="art"></div>{typebar(card)}<div class="textbox" id="text">{text}</div>{loyalty}{other}'
    if layout in ("saga", "class"):
        return f'{title(card)}<div class="art"></div><div class="textbox" id="text">{text}</div>{typebar(card)}{other}'
    cls = "has-pt" if pt_html else ""
    return f'{title(card)}<div class="art"></div>{typebar(card)}<div class="textbox {cls}" id="text">{text}{other}</div>{pt_html}'


def build_html(card, *, symbols, art_url, theme="wizards", fonts_css="", number=1, set_code="SET", set_size=1,
               flavor=None, art_filter=None, set_css="", frame_vars=None, maker="", maker_code="", year="",
               other_face=None):
    """The whole page for one card. `art_url` is the file:// URL of the image to show;
    `fonts_css` the @font-face rules for local faces (frame.local_fonts); `frame_vars` the frame
    knobs as css (frame_css), the defaults when None; `other_face` the record of a double-faced
    card's other side, named at the foot of the text box."""
    title, body = THEMES[theme]
    frame, frame_dark, bar, bar_edge, box = frame_for(card)
    rarity = card["rarity"]
    rarity_hi = RARITY[rarity][1] if rarity in ("uncommon", "rare", "mythic") else "transparent"
    layout = layout_of(card)
    pt = f'<div class="pt"><span>{card["power"]}/{card["toughness"]}</span></div>' if card.get("power") is not None else ""
    legendary = "legendary" in (card.get("frame_effects") or []) or card["type_line"].startswith("Legendary")
    footer = (f'<div class="footer"><span><b>{number:03d}/{set_size} {card["rarity"][0].upper()}</b><br>{esc(set_code)} · EN · '
              f'<span class="brush">✎</span> {esc(card["artist"])}</span>'
              f'<span>{esc(maker_code)} · {esc(maker)} · {year} · {card["set"].upper()} {card["collector_number"]}</span></div>')
    turned = layout in ("split", "battle")  # sideways: no stamp or crown; a battle's footer rides inside the turned box
    tpl = string.Template((PKG / "template.html").read_text())
    return tpl.substitute(
        font_link=font_link(title + body), local_fonts=fonts_css,
        title_font=stack(title), body_font=stack(body),
        frame=frame, frame_dark=frame_dark, bar=bar, bar_edge=bar_edge, box=box,
        noise=NOISE_URI, set_css=set_css, frame_vars=frame_vars or frame_css(),
        watermark=watermark_uri(), rarity_hi=rarity_hi, layout=layout,
        stamp='<div class="stamp"></div>' if rarity in ("rare", "mythic") and not turned else "",
        crown='<div class="crown-o"></div><div class="crown"></div>' if legendary and not turned else "",
        body=body_html(card, symbols, layout, flavor, pt, other_face, footer if layout == "battle" else ""),
        footer="" if layout == "battle" else footer,
        art=art_url, art_filter=art_filter or "none",
    )

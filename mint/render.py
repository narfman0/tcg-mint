"""Render cards from Scryfall data into the M15-style frame, at print resolution.

    mint render [--set sets/bls1.json] [--styled] [--theme NAME | --compare]
                [--dpi 1200] [--out DIR] ["Card Name" ...]

Layout is HTML/CSS (template.html) rendered by headless Chromium, so text
wrapping, italic reminder text and inline mana symbols come for free and the
frame is vector down to the last pixel. Art is Scryfall's art_crop for now
(cached in art/); upscaling comes later. Output is 2.72x3.72in with bleed,
which is both MPC's template and what an imposer wants.

A set file (JSON) carries the set code, size, an optional art_filter (the set's
"flair", a CSS filter applied when --styled is given) and per-card overrides:
number, flavor (your own flavor text), art (a local image), art_filter.
A .css file beside it is injected last, for the set's frame identity.
With --set and no card names, the whole set is rendered.

Fonts: drop Wizards' faces into fonts/ (Beleren-Bold.ttf, Mplantin.ttf,
Matrix-Bold.ttf ...) and the "wizards" theme picks them up by filename; the
fallbacks are the closest open faces from Google Fonts.
"""
import argparse
import base64
import datetime as dt
import json
import math
import os
import re
import string
import sys
import tempfile
import urllib.request

from . import ART, CARDS, FONTS, PKG, SYMBOLS

# --- identity: change these -------------------------------------------------
MAKER = "narfman0"
MAKER_CODE = "BLS"  # Blasted Studios
# ---------------------------------------------------------------------------

# Font stacks: (title, body). Local families first, then Google Fonts fallbacks.
# The "wizards" stack is Beleren (M15 title face) -> Matrix Bold (the 2003-2014
# title face) -> Almendra; MPlantin (rules text) -> Liberation Serif (Times,
# which descends from Plantin) -> Tinos.
THEMES = {
    "wizards":   (["Beleren", "Matrix Bold", "Almendra"], ["MPlantin", "Liberation Serif", "Tinos"]),
    "cinzel":    (["Cinzel"], ["EB Garamond"]),
    "cormorant": (["Cormorant SC"], ["Crimson Pro"]),
    "alegreya":  (["Alegreya SC"], ["Alegreya"]),
    "fell":      (["IM Fell English SC"], ["IM Fell English"]),
    "marcellus": (["Marcellus"], ["Libre Baskerville"]),
    "spectral":  (["Spectral SC"], ["Spectral"]),
}
LOCAL_FAMILIES = {"Beleren", "Matrix Bold", "MPlantin", "Liberation Serif"}  # never ask Google for these

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

# the template is 100 CSS px per inch; the card is 2.5x3.5in plus 0.11in bleed
PAGE = {"width": 272, "height": 372}

# Universes Beyond printings (Scryfall: security_stamp == "triangle") are not
# wanted as art, except these: Lord of the Rings fits Magic well enough.
UB_EXEMPT = {"ltr", "ltc"}


def load_card(name):
    if not CARDS.exists():
        sys.exit(f"no card file at {CARDS}; run `mint cards` or point MINT_CARDS at one")
    want = name.lower()
    with open(CARDS) as f:
        for line in f:
            c = json.loads(line)
            if c["layout"] == "art_series":  # same name, no rules text or art id
                continue
            if c["name"].lower() == want or c["name"].lower().startswith(want + " //"):
                if c.get("security_stamp") == "triangle" and c["set"] not in UB_EXEMPT:
                    # Universes Beyond: crossover art is never wanted, and this
                    # printing is the only one in oracle_cards -- say so, loudly
                    print(f"warning: {c['name']}: art source is a Universes Beyond printing ({c['set'].upper()})",
                          file=sys.stderr)
                return front_face(c)
    sys.exit(f"not in {CARDS.name}: {name}")


def front_face(card):
    """Double-faced cards (transform, modal_dfc) keep art, text, cost and type per
    face; present the front face's fields at the top level so the frame renders
    it as a normal card. The back face is not rendered yet."""
    faces = card.get("card_faces")
    if faces and "image_uris" not in card:
        card = {**card, **{k: v for k, v in faces[0].items() if k != "object"}, "full_name": card["name"]}
    return card


def overrides(cards, card):
    """The set file's entry for a card, keyed by either its face name or its full 'A // B' name."""
    return cards.get(card["name"]) or cards.get(card.get("full_name", ""), {})


def symbols():
    SYMBOLS.mkdir(parents=True, exist_ok=True)
    idx = SYMBOLS / "symbology.json"
    if not idx.exists():
        urllib.request.urlretrieve("https://api.scryfall.com/symbology", idx)
    return {s["symbol"]: s["svg_uri"] for s in json.load(open(idx))["data"]}


def symbol_data_uri(sym, table):
    fn = SYMBOLS / (re.sub(r"[^A-Za-z0-9]", "_", sym) + ".svg")
    if not fn.exists():
        urllib.request.urlretrieve(table[sym], fn)
    return "data:image/svg+xml;base64," + base64.b64encode(fn.read_bytes()).decode()


def art_path(card, override=None, upscaled=True):
    """file:// URL of the art: an override image, else the 4x upscale if
    `mint upscale` has made one, else Scryfall's art crop (fetched on demand)."""
    if override:
        return "file://" + os.path.abspath(override)
    ART.mkdir(parents=True, exist_ok=True)
    big = ART / (card["illustration_id"] + ".x4.png")
    if upscaled and big.exists():
        return "file://" + str(big)
    fn = ART / (card["illustration_id"] + ".jpg")
    if not fn.exists():
        urllib.request.urlretrieve(card["image_uris"]["art_crop"], fn)
    return "file://" + str(fn)


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


def font_files():
    """(family, weight, style, path) for every font file in fonts/, keyed off
    the filename: Beleren-Bold.ttf -> Beleren 700; Mplantin-Italic.ttf -> MPlantin italic."""
    known = {"beleren": "Beleren", "matrix": "Matrix Bold", "mplantin": "MPlantin"}
    out = []
    if not FONTS.is_dir():
        return out
    for fn in sorted(FONTS.iterdir()):
        if fn.suffix.lower() not in (".ttf", ".otf", ".woff", ".woff2"):
            continue
        stem = fn.stem
        base = re.split(r"[-_ ]", stem)[0].lower()
        family = known.get(base, stem.split("-")[0])
        weight = 700 if re.search(r"bold", stem, re.I) or family == "Matrix Bold" else 400
        style = "italic" if re.search(r"italic", stem, re.I) else "normal"
        out.append((family, weight, style, fn))
    return out


def local_fonts():
    """@font-face rules for whatever is in fonts/."""
    fmt = {".ttf": "truetype", ".otf": "opentype", ".woff": "woff", ".woff2": "woff2"}
    return "\n".join(
        f"@font-face {{ font-family: '{family}'; src: url('file://{fn}') format('{fmt[fn.suffix.lower()]}'); "
        f"font-weight: {weight}; font-style: {style}; }}"
        for family, weight, style, fn in font_files())


def font_link(families):
    web = [f for f in families if f not in LOCAL_FAMILIES]
    fams = "&".join("family=" + f.replace(" ", "+") + ":ital,wght@0,400;0,700;1,400" for f in dict.fromkeys(web))
    return f"https://fonts.googleapis.com/css2?{fams}&display=swap" if fams else "data:text/css,"


def stack(families):
    return ", ".join(f"'{f}'" for f in families) + ", serif"


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


def render_text(card, table, flavor=None):
    def syms(s):
        return re.sub(r"\{[^}]+\}", lambda m: f'<img class="sym" src="{symbol_data_uri(m.group(0), table)}">', esc(s))
    text = card.get("oracle_text") or ""
    # a basic land shows one big mana symbol instead of its "({T}: Add {G}.)" line
    m = re.fullmatch(r"\(\{T\}: Add (\{[WUBRGC]\})\.\)", text.strip())
    if card["type_line"].startswith("Basic") and m:
        return f'<p class="big-sym"><img src="{symbol_data_uri(m.group(1), table)}"></p>'
    paras = []
    for p in text.split("\n"):
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


def build_html(card, theme, table, number, set_code, set_size, override, art_filter, set_css=""):
    title, body = THEMES[theme]
    frame, frame_dark, bar, bar_edge, box = frame_for(card)
    cost = "".join(f'<img src="{symbol_data_uri(m, table)}">' for m in re.findall(r"\{[^}]+\}", card.get("mana_cost") or ""))
    pt = f'<div class="pt"><span>{card["power"]}/{card["toughness"]}</span></div>' if card.get("power") is not None else ""
    legendary = "legendary" in (card.get("frame_effects") or []) or card["type_line"].startswith("Legendary")
    tpl = string.Template((PKG / "template.html").read_text())
    return tpl.substitute(
        font_link=font_link(title + body), local_fonts=local_fonts(),
        title_font=stack(title), body_font=stack(body),
        frame=frame, frame_dark=frame_dark, bar=bar, bar_edge=bar_edge, box=box,
        noise="data:image/svg+xml;base64," + NOISE, set_css=set_css,
        crown='<div class="crown-o"></div><div class="crown"></div>' if legendary else "",
        name=esc(card["name"]), cost=cost,
        art=art_path(card, override.get("art")), art_filter=art_filter or "none",
        type_line=esc(card["type_line"]), set_symbol=set_symbol(card["rarity"]), set_code=set_code,
        text=render_text(card, table, override.get("flavor")), pt=pt, text_class="has-pt" if pt else "",
        number=f"{number:03d}", set_size=set_size, rarity=card["rarity"][0].upper(),
        artist=esc(card["artist"]), maker_code=MAKER_CODE, maker=MAKER,
        date=dt.date.today().strftime("%Y"),
        orig_set=card["set"].upper(), orig_number=card["collector_number"],
    )


def render(page, html, out):
    # Chromium needs a file:// page for the file:// art and font references to resolve
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False) as f:
        f.write(html)
    try:
        # fonts are fetched lazily once layout asks for them, so wait for the
        # network to go quiet, then for the font set to settle, *then* fit text
        page.goto("file://" + f.name, wait_until="networkidle")
        page.evaluate("document.fonts.ready")
        page.evaluate("fit()")
        page.screenshot(path=out, clip={"x": 0, "y": 0, **PAGE})
    finally:
        os.unlink(f.name)


def browser(playwright, dpi):
    # full Chromium in new-headless mode: no separate headless-shell download
    b = playwright.chromium.launch(channel="chromium")
    ctx = b.new_context(viewport=PAGE, device_scale_factor=dpi / 100)
    return b, ctx.new_page()


def load_set(path):
    """The set JSON plus its optional sibling .css."""
    if not path:
        return {}, ""
    st = json.load(open(path))
    css_fn = os.path.splitext(path)[0] + ".css"
    return st, open(css_fn).read() if os.path.exists(css_fn) else ""


def main(argv=None):
    ap = argparse.ArgumentParser(prog="mint render", description=__doc__.split("\n\n")[0])
    ap.add_argument("names", nargs="*")
    ap.add_argument("--set", help="set JSON: code, size, art_filter, cards{name: {number, flavor, art, art_filter}}")
    ap.add_argument("--styled", action="store_true", help="apply the set's art_filter (the stylized variant)")
    ap.add_argument("--theme", default="wizards", choices=THEMES)
    ap.add_argument("--compare", action="store_true", help="render every theme into a contact sheet")
    ap.add_argument("--dpi", type=int, default=1200)
    ap.add_argument("--out", default=".", help="directory for the PNGs (default: current directory)")
    a = ap.parse_args(argv)

    st, set_css = load_set(a.set)
    cards = st.get("cards", {})
    names = a.names or list(cards)
    if not names:
        ap.error("give card names or a --set with cards")
    set_code = st.get("code", MAKER_CODE + "1")
    set_size = st.get("size", len(cards) or 100)

    from playwright.sync_api import sync_playwright
    table = symbols()
    os.makedirs(a.out, exist_ok=True)
    themes = list(THEMES) if a.compare else [a.theme]
    outs = []
    with sync_playwright() as p:
        b, page = browser(p, a.dpi)
        for i, name in enumerate(names, 1):
            card = load_card(name)
            ov = overrides(cards, card)
            number = ov.get("number", i)
            art_filter = None
            if a.styled:
                # a restyled image (mint restyle) wins; the CSS filter is the fallback
                styled = ART / f"{card['illustration_id']}.{st.get('style', {}).get('name', '-')}.png"
                if styled.exists() and not ov.get("art"):
                    ov = {**ov, "art": str(styled)}
                else:
                    art_filter = ov.get("art_filter") or st.get("art_filter")
            for th in themes:
                slug = re.sub(r"[^A-Za-z0-9]+", "_", card["name"]).strip("_")
                tag = f".{th}" if a.compare else ""
                prefix = f"{set_code}-" if a.set else ""
                out = os.path.join(a.out, f"{prefix}{number:03d}_{slug}{'.styled' if a.styled else ''}{tag}.png")
                render(page, build_html(card, th, table, number, set_code, set_size, ov, art_filter, set_css), out)
                outs.append(out)
                print(out)
        b.close()
    if a.compare:
        from PIL import Image
        ims = [Image.open(o) for o in outs]
        w, h = ims[0].size
        s = 4  # downscale for the sheet
        cols, rows = len(themes), len(names)
        sheet = Image.new("RGB", (cols * w // s, rows * h // s), "white")
        for k, im in enumerate(ims):
            sheet.paste(im.resize((w // s, h // s), Image.LANCZOS), ((k % cols) * w // s, (k // cols) * h // s))
        fn = os.path.join(a.out, "compare.png")
        sheet.save(fn)
        print(fn)
    return outs


if __name__ == "__main__":
    main()

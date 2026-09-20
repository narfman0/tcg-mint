"""Report which frame fonts are present in fonts/ and which are being substituted.

    mint fonts [--repair]

Wizards' font files are not distributed with tcg-mint (they are not ours to
redistribute); see fonts/README.md for where each one is published. The open
fallbacks (Almendra, Liberation Serif) ship in the package and are listed as
such rather than as extras.

--repair rewrites every font in fonts/ in place (needs fonttools, the [fonts]
extra) to cure the two faults the community copies carry: a table directory
Chromium's sanitizer rejects, after which the render silently uses the
fallback; and characters mapped to empty glyphs -- a middle dot, a C-acute --
which draw as nothing, since the browser sees a glyph and never falls back
for it. The rewrite rebuilds the directory and drops those mappings, so the
fallback face supplies exactly those characters.
"""
import os
import sys

from . import frame, workspace

WANT = {
    "Beleren":  "M15 title, type line and P/T face",
    "MPlantin": "rules and flavor text",
    "Matrix Bold": "2003-2014 title face (fallback for Beleren)",
}


def report(fonts_dir):
    """{family: [description, ...]} of what is present, and the list of missing families."""
    have = {}
    for family, weight, style, fn in frame.font_files(fonts_dir):
        have.setdefault(family, []).append(f"{fn.name} ({weight} {style})")
    return have, [f for f in WANT if f not in have]


# codepoints that are blank by design and stay mapped even to an empty glyph
BLANK = {0x09, 0x0A, 0x0D, 0x20, 0xA0, 0xAD, *range(0x2000, 0x200C), 0x202F, 0x205F, 0x3000, 0xFEFF}


def repair(path):
    """Rewrite one TrueType file: a fresh table directory, the cmap language reset, and every
    codepoint mapped to an empty glyph (no contours, not a composite, not a blank by design)
    unmapped. Returns the codepoints dropped, sorted."""
    from fontTools.ttLib import TTFont
    font = TTFont(path, recalcBBoxes=False)
    dropped = set()
    glyf = font["glyf"] if "glyf" in font else None
    for table in font["cmap"].tables:
        table.language = 0
        if glyf is None:
            continue
        for cp, name in list(table.cmap.items()):
            g = glyf.get(name)
            if cp not in BLANK and g is not None and g.numberOfContours == 0:
                del table.cmap[cp]
                dropped.add(cp)
    tmp = path.with_name(path.name + ".new")
    font.save(tmp)
    os.replace(tmp, path)
    return sorted(dropped)


def repair_all(fonts_dir):
    """Repair every .ttf and .otf in the directory; print one line each. Returns the count."""
    try:
        import fontTools  # noqa: F401
    except ImportError:
        sys.exit("--repair needs fonttools: pip install -e '.[fonts]'")
    files = sorted(p for p in fonts_dir.iterdir() if p.suffix.lower() in (".ttf", ".otf"))
    for p in files:
        try:
            dropped = repair(p)
        except Exception as e:  # a font fontTools cannot read is reported, not fatal
            print(f"  failed   {p.name}: {e}")
            continue
        chars = "".join(chr(c) for c in dropped[:12]) + ("…" if len(dropped) > 12 else "")
        print(f"  repaired {p.name}: table directory rebuilt"
              + (f", {len(dropped)} empty glyph(s) unmapped ({chars})" if dropped else ""))
    return len(files)


def main(argv=None):
    argv = list(argv or [])
    do_repair = "--repair" in argv
    if [a for a in argv if a != "--repair"]:
        sys.exit("usage: mint fonts [--repair]")
    ws = workspace.default()
    if do_repair:
        print(f"repairing fonts in {ws.fonts}")
        repair_all(ws.fonts)
    have, missing = report(ws.fonts)
    print(f"fonts dir: {ws.fonts}")
    for family, role in WANT.items():
        if family in have:
            print(f"  ok       {family:16} {', '.join(have[family])}")
        else:
            print(f"  missing  {family:16} {role}")
    for family in have:
        if family not in WANT and family not in frame.PACKAGED_FAMILIES:
            print(f"  extra    {family:16} {', '.join(have[family])}")
    packaged, _ = report(frame.FONTS)
    for family, role in frame.PACKAGED_FAMILIES.items():
        src = have.get(family) or packaged.get(family) or []
        where = "yours" if family in have else "packaged"
        print(f"  fallback {family:16} {role}: {', '.join(src)} ({where})")
    if missing:
        print("\nmissing faces use the packaged open fallbacks; see fonts/README.md for the real ones")
    return 1 if missing else 0

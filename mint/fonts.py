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

# the faces each family has to supply, not just the family: a family present only as its roman is
# not "ok". The frame sets flavor text, reminder text and ability words in italic
# (template.html), and with no italic face the browser shears the roman into a fake one -- it
# never falls back to Liberation Serif for a family it has already matched.
WANT = {
    "Beleren":     ("M15 title, type line and P/T face", [(700, "normal")]),
    "MPlantin":    ("rules and flavor text", [(400, "normal"), (400, "italic")]),
    "Matrix Bold": ("2003-2014 title face (fallback for Beleren)", [(700, "normal")]),
}
FACE = {(400, "normal"): "roman", (400, "italic"): "italic",
        (700, "normal"): "bold", (700, "italic"): "bold italic"}


def face(weight, style):
    return FACE.get((weight, style), f"{weight} {style}")


def shown(faces):
    """'Mplantin.ttf (roman), Mplantin-Italic.ttf (italic)' for a {(weight, style): path} map,
    in reading order: roman, italic, bold, bold italic."""
    order = lambda item: (item[0][0], item[0][1] == "italic")  # noqa: E731
    return ", ".join(f"{p.name} ({face(w, s)})" for (w, s), p in sorted(faces.items(), key=order))


def report(fonts_dir):
    """({family: {(weight, style): path}}, [(family, weight, style) ...]) -- what is present, and
    the faces WANT asks for that are not."""
    have = {}
    for family, weight, style, fn in frame.font_files(fonts_dir):
        have.setdefault(family, {})[(weight, style)] = fn
    missing = [(family, w, s) for family, (_, faces) in WANT.items() for (w, s) in faces
               if (w, s) not in have.get(family, {})]
    return have, missing


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
    for family, (role, faces) in WANT.items():
        mine = have.get(family, {})
        gone = [f for f in faces if f not in mine]
        if not gone:
            print(f"  ok       {family:18} {shown(mine)}")
        elif mine:  # the family is there but a face of it is not, and gets synthesized
            print(f"  partial  {family:18} {shown(mine)}: no {', '.join(face(*f) for f in gone)}, "
                  f"which the browser fakes from the roman")
        else:
            print(f"  missing  {family:18} {role}")
    for family, faces in have.items():
        if family not in WANT and family not in frame.PACKAGED_FAMILIES:
            print(f"  extra    {family:18} {shown(faces)}")
    packaged, _ = report(frame.FONTS)
    for family, role in frame.PACKAGED_FAMILIES.items():
        src = have.get(family) or packaged.get(family) or {}
        where = "yours" if family in have else "packaged"
        print(f"  fallback {family:18} {role}: {shown(src)} ({where})")
    if missing:
        print("\nmissing faces use the packaged open fallbacks; see fonts/README.md for the real ones")
    return 1 if missing else 0

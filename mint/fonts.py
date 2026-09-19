"""Report which frame fonts are present in fonts/ and which are being substituted.

    mint fonts

Wizards' font files are not distributed with tcg-mint (they are not ours to
redistribute); see fonts/README.md for where each one is published. The open
fallbacks (Almendra, Liberation Serif) ship in the package and are listed as
such rather than as extras.
"""
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


def main(argv=None):
    if argv:
        sys.exit("mint fonts takes no arguments")
    ws = workspace.default()
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

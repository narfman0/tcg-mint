"""Report which frame fonts are present in fonts/ and which are being substituted.

    mint fonts

Font files are not distributed with tcg-mint (they are not ours to
redistribute); see fonts/README.md for where each one is published.
"""
import sys

from . import FONTS, render

WANT = {
    "Beleren":  "M15 title, type line and P/T face",
    "MPlantin": "rules and flavor text",
    "Matrix Bold": "2003-2014 title face (fallback for Beleren)",
}


def main(argv=None):
    if argv:
        sys.exit("mint fonts takes no arguments")
    have = {}
    for family, weight, style, fn in render.font_files():
        have.setdefault(family, []).append(f"{fn.name} ({weight} {style})")
    print(f"fonts dir: {FONTS}")
    missing = 0
    for family, role in WANT.items():
        if family in have:
            print(f"  ok       {family:12} {', '.join(have[family])}")
        else:
            print(f"  missing  {family:12} {role}")
            missing += 1
    for family in have:
        if family not in WANT:
            print(f"  extra    {family:12} {', '.join(have[family])}")
    if missing:
        print("\nmissing faces fall back to Google Fonts substitutes; see fonts/README.md")
    return 1 if missing else 0

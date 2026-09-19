"""Report which frame fonts are present in fonts/ and which are being substituted.

    mint fonts

Font files are not distributed with tcg-mint (they are not ours to
redistribute); see fonts/README.md for where each one is published.
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
            print(f"  ok       {family:12} {', '.join(have[family])}")
        else:
            print(f"  missing  {family:12} {role}")
    for family in have:
        if family not in WANT:
            print(f"  extra    {family:12} {', '.join(have[family])}")
    if missing:
        print("\nmissing faces fall back to Google Fonts substitutes; see fonts/README.md")
    return 1 if missing else 0

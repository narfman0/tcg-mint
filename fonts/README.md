# fonts/

Font files go here and are **not** committed (`.gitignore` covers this
directory). They are picked up by filename: `Beleren-Bold.ttf`,
`Mplantin.ttf`, `Mplantin-Italic.ttf`, `Matrix-Bold.ttf`, and so on.
`mint fonts` reports what is present.

| face | role | where to find it |
|---|---|---|
| Beleren 2016 Bold | title, type line, P/T (M15 frame) | https://github.com/Saeris/typeface-beleren-bold — `Beleren2016-Bold.ttf`, save as `Beleren-Bold.ttf` |
| MPlantin | rules and flavor text | https://github.com/AlexandreArpin/mtg-font — `fonts/Mplantin.ttf` |
| Matrix Bold | title face of the 2003–2014 frame; fallback for Beleren | same repo — `fonts/Matrix-Bold.ttf` |

These are Wizards of the Coast / Monotype / Emigre property; use them for
personal proxies only. Without them the `wizards` theme substitutes the
closest open faces, which ship with the package under `mint/fonts/`
(Almendra Bold for titles, Liberation Serif for rules text; both SIL OFL),
so a render never needs the network for fonts. A face you put here always
wins over the packaged one of the same family.

## If Chromium refuses a font

Some of the community copies are old Mac conversions that Chromium's font
sanitizer (OTS) rejects — the render then silently uses the fallback and
`mint fonts` still says "ok". A round-trip through fontTools rebuilds the
table directory and fixes it:

```sh
pip install fonttools
python - <<'EOF'
from fontTools.ttLib import TTFont
for fn in ["fonts/Mplantin.ttf", "fonts/Matrix-Bold.ttf"]:
    t = TTFont(fn, recalcBBoxes=False)
    for tab in t["cmap"].tables:
        tab.language = 0
    t.save(fn + ".new"); import os; os.replace(fn + ".new", fn)
EOF
```

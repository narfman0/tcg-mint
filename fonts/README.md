# fonts/

Font files go here and are **not** committed (`.gitignore` covers this
directory). They are picked up by filename: `Beleren-Bold.ttf`,
`Mplantin.ttf`, `Mplantin-Italic.ttf`, `Matrix-Bold.ttf`, and so on.
`mint fonts` reports what is present.

| face | role | where to find it |
|---|---|---|
| Beleren 2016 Bold | title, type line, P/T (M15 frame) | https://github.com/Saeris/typeface-beleren-bold — `Beleren2016-Bold.ttf`, save as `Beleren-Bold.ttf` |
| MPlantin | rules and flavor text | https://github.com/narfman0/mtg-font branch `fix/empty-glyphs` — `fonts/Mplantin.ttf` (a fork of AlexandreArpin/mtg-font with the repair below already applied) |
| Matrix Bold | title face of the 2003–2014 frame; fallback for Beleren | same repo — `fonts/Matrix-Bold.ttf` |

These are Wizards of the Coast / Monotype / Emigre property; use them for
personal proxies only. Without them the `wizards` theme substitutes the
closest open faces, which ship with the package under `mint/fonts/`
(Almendra Bold for titles, Liberation Serif for rules text; both SIL OFL),
so a render never needs the network for fonts. A face you put here always
wins over the packaged one of the same family.

## Repairing a community copy

The copies in circulation are old Mac conversions with two faults. Chromium's
font sanitizer (OTS) rejects the table directory of some, and the render then
silently uses the fallback while `mint fonts` still says "ok". And many
characters are mapped to empty glyphs — in MPlantin the middle dot and the
whole Latin Extended-A block (Ć, Š, ł…), in Matrix Bold the backslash, pipe
and tilde — which draw as nothing: the browser sees a glyph, so it never
falls back for that character. Separators vanish from the collector line and
"Ćeran" prints as " eran".

```sh
pip install -e '.[fonts]'
mint fonts --repair
```

rewrites every font in `fonts/` in place: the table directory is rebuilt and
the empty-glyph mappings are dropped, so the fallback face (Liberation Serif)
supplies exactly those characters. Outlines are untouched; a repaired file is
repaired again without harm. The fork linked above carries the repaired
`.ttf` files, so from there nothing needs running.

# fonts/

Font files go here and are **not** committed (`.gitignore` covers this
directory). They are picked up by filename: `Beleren-Bold.ttf`,
`Mplantin.ttf`, `Mplantin-Italic.ttf`, `Matrix-Bold.ttf`, and so on.
`mint fonts` reports what is present, face by face.

| face | role | where to find it |
|---|---|---|
| Beleren 2016 Bold | title, type line, P/T (M15 frame) | https://github.com/Saeris/typeface-beleren-bold — `Beleren2016-Bold.ttf`, save as `Beleren-Bold.ttf` |
| MPlantin | rules and flavor text | https://github.com/narfman0/mtg-font branch `fix/empty-glyphs` — `fonts/Mplantin.ttf` (a fork of AlexandreArpin/mtg-font with the repair below already applied) |
| **MPlantin Italic** | **flavor text, reminder text, ability words** | https://github.com/narfman0/magarena — `resources/cardbuilder/fonts/MPlantin-Italic.ttf`, save as `Mplantin-Italic.ttf`. **Needs the repair below**; the mtg-font fork does not carry an italic |
| Matrix Bold | title face of the 2003–2014 frame; fallback for Beleren | mtg-font fork, as above — `fonts/Matrix-Bold.ttf` |

The italic is not optional dressing. `mint/template.html` sets flavor text,
reminder text and ability words in italic, and CSS font matching picks a
family *before* it picks a face: with MPlantin present as a roman only, the
browser stays inside MPlantin and shears the roman into a fake oblique rather
than falling back to Liberation Serif Italic. It looks nearly right, which is
why it went unnoticed — `mint fonts` used to group by family and call the
whole family `ok` on the strength of the roman alone. It now asks per face.

magarena's copy is the same cut as the roman above — probing outlines
glyph by glyph gives identical bounds — so the two sit together as a family
rather than merely sharing a name.

The collector line at the foot of a real card is set in a proprietary
geometric sans (Relay); Montserrat SemiBold (SIL OFL) ships in the package
as the stand-in, and the artist's name is the title face as small caps.

These are Wizards of the Coast / Monotype / Emigre property; use them for
personal proxies only. Without them the `wizards` theme substitutes the
closest open faces, which ship with the package under `mint/fonts/`
(Almendra Bold for titles, Liberation Serif for rules text; both SIL OFL),
so a render never needs the network for fonts. A face you put here always
wins over the packaged one of the same family.

## Faces the frame does not ask for

magarena carries three more that nothing in the frame currently uses. They
are safe to keep in `fonts/` — `mint fonts` lists them as `extra` — and are
there for later:

| face | note |
|---|---|
| `MPlantin-Bold.ttf` | the family's bold. No bold body text exists in the frame today |
| `Beleren Small Caps.ttf` | its own family, **not** a weight of Beleren. Could replace the synthesized small caps on the footer's artist line, which would change that line's face on every card — so it is installed, not wired up |
| `JaceBeleren-Bold.ttf` | an alternate Beleren cut |

magarena's `Beleren-Bold.ttf` is **worse** than the Saeris copy in the table
above (235 glyphs and 6 empty mappings against 284 and none); take Beleren
from Saeris.

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
`.ttf` files, so from there nothing needs running — the magarena italic and
its siblings do need it (each drops 186 empty mappings).

## Checking what you downloaded

Hash the file **as downloaded**, before repairing. A repaired file's hash is
machine-local: fontTools stamps `head.modified` with the moment it saved, so
two correct repairs of one source differ in those four bytes and nowhere else.

```sh
sha256sum Mplantin-Italic.ttf
```

| source file | sha256 |
|---|---|
| magarena `MPlantin-Italic.ttf` | `75046f50cc1f720420bc219ba775fafdac04367dcb3e4e5ce6e0f9790e075436` |
| magarena `MPlantin-Bold.ttf` | `4241e7ab4dc4480de8ef3c63e64fcff2c685b6f78a6d0f5524677cb85b7c5d62` |
| magarena `Beleren Small Caps.ttf` | `065de42b4047f8d4d88bcb5a232aef9c42773dfc0d19efecf780478ab2faf335` |
| magarena `JaceBeleren-Bold.ttf` | `dc7bed944859185bd1cc4adbcde0a4669bf819e9f5c0fef2a6f547e29a342ccd` |
| mtg-font `Mplantin.ttf` | `619300b3425d310729165fe9531b4d78cadbc27ddfad5da0bc3ca407f86e0b02` |
| mtg-font `Matrix-Bold.ttf` | `51e9a5c7699a38fbac86572021909cf21a8aa82559b46b6e66e0271c784b1bed` |

The two mtg-font files are already repaired where they are published, so
those hashes are of the repaired file and are stable — they were produced
once, in the fork.

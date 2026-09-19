# tcg-mint

Render trading cards from Scryfall data into your own frame at print
resolution, then print them yourself or publish them to MPC Autofill.

The frame is HTML/CSS rendered by headless Chromium: text wrapping, italic
reminder text, inline mana symbols and shrink-to-fit come for free, and the
whole frame is vector down to the last pixel — 1200 DPI costs nothing but
disk. The default frame reproduces the modern (M15) Magic layout, with its
geometry and text placement measured off Scryfall's scans rather than
eyeballed (`mint calibrate` shows the numbers). Cards carry your own collector
line: your set code and numbering, your name, the mint date, and a pointer
back to the original printing.

Output is 2.72 × 3.72 in with bleed — MakePlayingCards' template size, and
what any imposer wants.

## Install

```sh
pip install -e .
playwright install chromium
```

If `playwright install` times out on your network, fetch the same build with
curl and unzip it where Playwright expects it — the path is printed by
`python -c "from playwright.sync_api import sync_playwright as p; print(p().start().chromium.executable_path)"`.

Then, in the directory you want to work in (your *workspace*):

```sh
mint cards            # fetch Scryfall's oracle-cards bulk file (~200 MB, gitignored)
mint fonts            # see which frame fonts you have; fonts/README.md says where to get them
mint render "Cyclonic Rift"                        # -> ./014_Cyclonic_Rift.png at 1200 DPI
mint render --set sets/bls1.json --out proofs      # a whole set
mint render --set sets/bls1.json --styled --out proofs   # the set's stylized art variant
```

Set `MINT_HOME` to keep the workspace (fonts, caches, card file) somewhere
other than the current directory, and `MINT_CARDS` to share one Scryfall file
between projects.

## Sets

A set is a JSON file (see `sets/bls1.json`):

```json
{
  "code": "BLS1", "name": "Blasted Studios, Set One", "size": 18,
  "art_filter": "saturate(1.55) contrast(1.18) hue-rotate(-8deg)",
  "cards": {
    "Cyclonic Rift": {"number": 14, "flavor": "Everyone back to where you started. Except me."},
    "The One Ring":  {"number": 3, "art": "art/my-own-ring.png"}
  }
}
```

- `number` is the card's collector number in *your* set; the footer also
  records the original printing (`after RVR #40`) so the mapping runs both ways.
- `flavor` replaces the printed flavor text; omit the key to keep the original.
- `art` points at your own image; otherwise Scryfall's art crop is used.
- `art_filter` (set-wide or per card) is a CSS filter applied with
  `--styled` — the set's "flair" variant next to the faithful one.
- A `.css` file with the same name (`sets/bls1.css`) is injected after the
  base frame rules, so each set can carry its own frame identity: colours,
  textures, bar shapes, anything.

## Commands

| command | what |
|---|---|
| `mint render` | render cards by name or from a set file; `--compare` audition every font theme on one sheet |
| `mint calibrate` | measure title / type / P/T text placement on real Scryfall scans vs ours, in 1/100 in |
| `mint cards` | fetch or refresh Scryfall's bulk card file (`--kind default_cards` for per-printing art) |
| `mint fonts` | report which frame fonts are present |
| `mint print` | send a PDF to an Epson ET-8500 at true 100 % with the right black for the stock |

## Fonts

The frame wants Beleren (titles) and MPlantin (rules text). They are not
ours to redistribute; `fonts/README.md` says where each is published and how
to repair the community copies that Chromium's font sanitizer rejects.
Without them the closest open faces are substituted automatically.

## What's not here yet

- art upscaling (Scryfall's crops are ~300 DPI; a 4× Real-ESRGAN pass is the plan)
- an imposer (PNGs → 3×3 letter-size PDF with cut marks) to feed `mint print`
- layouts beyond `normal`: split, MDFC, planeswalker, saga
- picking art from a specific printing (`default_cards` is fetched; the render still uses the oracle default)

## Legal

Card names, rules text and art are © Wizards of the Coast. This tool is for
personal proxies; share renders the way the MPC Autofill community does and
don't sell them. The code is MIT.

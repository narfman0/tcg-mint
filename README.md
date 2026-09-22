# tcg-mint

Render trading cards from Scryfall data into your own frame at print
resolution, then print them yourself or publish them to MPC Autofill.

The frame is HTML/CSS rendered by headless Chromium: text wrapping, italic
reminder text, inline mana symbols and shrink-to-fit come for free, and the
whole frame is vector down to the last pixel — 1200 DPI costs nothing but
disk. The default frame reproduces the modern (M15) Magic layout, with its
geometry and text placement measured off Scryfall's scans rather than
eyeballed (`mint calibrate` shows the numbers). Cards keep the printed card's
collector line and expansion symbol — its number and set size, set code,
language and artist, the set's own icon in the type bar — and carry your name
and the mint year on the right, where the real cards put the publisher.

Beyond the normal card the frame knows the other shapes a deck holds:
planeswalkers (loyalty badges per ability, the loyalty shield), sagas
(chapters down the left, the art the full height on the right), classes (the
mirror, level bands on the right), adventures (the adventure in its own box
beside the creature's text), split cards and battles (sideways, two half
cards or the art beside the text), and both faces of transform and modal
double-faced cards, each marked with its icon and naming the other face at
the foot of the text box (`--faces` renders the backs). Colour follows the
real cards too: a land that makes one colour takes that colour's pinline,
and a two-colour card — a dual land, a fetch land by the basic types it
finds, a spell whose every coloured pip is hybrid — runs its left colour
into its right across the pinline, the text box and (on a spell) the frame.

Output is 2.72 × 3.72 in with bleed — MakePlayingCards' template size, and
what any imposer wants.

## Install

```sh
pip install -e .
playwright install chromium
```

For development, `pip install -e .[dev]` adds ruff and pytest; `pytest` runs the
unit tests and `pytest -m render` the one that drives Chromium.

If `playwright install` times out on your network, fetch the same build with
curl and unzip it where Playwright expects it — the path is printed by
`python -c "from playwright.sync_api import sync_playwright as p; print(p().start().chromium.executable_path)"`.

Then, in the directory you want to work in (your *workspace*):

```sh
mint cards            # fetch Scryfall's oracle-cards bulk file (~200 MB, gitignored)
mint fonts            # see which frame fonts you have; fonts/README.md says where to get them
mint render "Cyclonic Rift"                        # -> ./001_Cyclonic_Rift.png at 1200 DPI
mint render --set sets/bls1.json --out proofs      # a whole set
mint render --set sets/bls1.json --styled --out proofs   # the set's stylized art variant
```

Set `MINT_HOME` to keep the workspace (fonts, caches, card file) somewhere
other than the current directory, and `MINT_CARDS` to share one Scryfall file
between projects.

The first lookup builds a small SQLite index beside the card file
(`oracle-cards.jsonl.idx`, a few seconds); after that finding a card is
instant, and the index rebuilds itself whenever the card file changes.

## Sets

A set is a JSON file in `sets/` (`docs/examples/set.json` shows one of every
kind of entry; `sets/` and `styles/` are yours and git ignores both):

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

- `number` is the card's collector number in *your* set: it orders the set,
  names the output file (`BLS1-014_...png`) and keys the manifest. The card
  itself prints the original printing's number and set (`040/291 RVR`).
- `flavor` replaces the printed flavor text; omit the key to keep the original.
- `art` points at your own image; otherwise Scryfall's art crop is used.
- `printing` (`"rvr:40"`) renders a specific printing when the card file holds
  several (`mint cards --kind default_cards`); without it the newest
  non-crossover printing is used.
- `subject`, `base` and `seed` steer `mint restyle` for that card (below).
- `art_filter` (set-wide or per card) is a CSS filter applied with
  `--styled` — the set's "flair" variant next to the faithful one.
- In the style block, `color_match` (0–1) moves a finished restyle's
  colours back to its base's by that much — the fix for a faithful style
  whose palette drifts (a red seal gone brown). Off by default, and off
  keeps out of the recipe hash.
- A `frame` block holds the frame's dressing, each knob a strength from 0
  (off) to 1: `watermark` (the expansion symbol, faint, behind the rules text),
  `frame_texture` (the coloured frame's painted texture, one per colour as
  on the real cards: marbled parchment on white, wet glass on blue, fissured
  stone on black, crackle on red, a cell network on green, brushed metal on
  artifacts and gold, sand on lands, grain on colorless; generated, not
  copied), `art_bevel` (the black line around the art),
  `box_grain` (linen grain over the bars and text box), `foil_stamp` (the
  security stamp under the text box: the holofoil oval of a rare or mythic,
  or the printing's own -- Universes Beyond's triangle at any rarity, the
  Un-sets' acorn, the Signature Spellbooks' circle -- each with its bite out
  of the text box) and `rarity_tint`
  (the bars tinted silver, gold or orange by rarity). The defaults are the
  texture, the bevel, the grain and the stamp on; each reaches the frame as a CSS custom property of
  the same name (`--art-bevel`), so the set's css can still override any.
- A `.css` file with the same name (`sets/bls1.css`; `docs/examples/set.css`) is injected after the
  base frame rules, so each set can carry its own frame identity: colours,
  textures, bar shapes, anything.
- `design` names the frame design the set's cards render in, and a card
  entry's `design` overrides it: `m15` (the default), `extended` (the art
  window widened to the border), `borderless` (the art off the card's
  sides between the bars), `fullart` (the art under everything), or `auto`
  to follow each card's printing. A design steers the default printing to
  its own kind (a card set to `fullart` starts from its newest full-art
  printing), sizes a restyle or a clip to its shape unless the block
  spells `width` and `height`, and `mint check` warns when the picture is
  the wrong shape for it. Each design is measured off scans of real
  printings of its kind (`mint/designs/*.css` says which); a saga, class,
  split or battle card stays M15 whatever the design.

Unknown keys are errors (`mint check` finds them), so a typo in a recipe never
passes silently. Who you are on the cards, the ComfyUI address, the printer,
where the workbench exports a PDF to, and who reads a card's picture for
`mint describe` live in `mint.toml` in the workspace:

```toml
maker = "narfman0"
maker_code = "BLS"
comfy_url = "http://127.0.0.1:8188"
printer = "EPSON_ET_8500"
export_dir = "~/Desktop"
describer = "claude"          # or "ollama"; claude reads ANTHROPIC_API_KEY from the environment
describe_model = ""           # empty = the describer's default (claude-sonnet-5 / qwen2.5vl)
ollama_url = "http://127.0.0.1:11434"
```

## Commands

| command | what |
|---|---|
| `mint newset` | start a set file from a decklist (commander first); `--style` seeds a style block from a template or a built-in |
| `mint render` | render cards by name or from a set file; `--compare` audition every font theme on one sheet; `--faces` the backs of double-faced cards too |
| `mint restyle` | regenerate every card's art in the set's style through ComfyUI (img2img + ControlNet) |
| `mint describe` | a vision model reads each card's picture and text and writes its `subject` line; `--generate` then makes each card's `new` scene from it |
| `mint animate` | a short seamless clip of a card's art through ComfyUI (Wan 2.2), beside its stills; the workbench's card page is where it is meant to be pressed |
| `mint upscale` | 4× ESRGAN the art (or any variant, `--base HASH`) through a local ComfyUI; renders pick the result up automatically |
| `mint check` | validate set files and say which image each card renders with, plain and styled |
| `mint style` | save a set's art style as a template in `styles/` for other sets to start from; `list` and `show` them |
| `mint migrate` | move a pre-variant art cache (`art/<id>.<style>.png`) into `art/<id>/` with recipe sidecars |
| `mint calibrate` | measure title / type / P/T text placement on real Scryfall scans vs ours, in 1/100 in |
| `mint cards` | fetch or refresh Scryfall's bulk card file (`--kind default_cards` for per-printing art) |
| `mint fonts` | report which frame fonts are present; `--repair` fixes the community copies |
| `mint gc` | report variants no card picks, renders with, or starts from, and renders gone stale; `--delete` removes them |
| `mint doctor` | check the card file, the fonts, a Chromium launch, ComfyUI's nodes, every model file the styles name, and the Wan files and ffmpeg when a set has a motion block |
| `mint impose` | lay rendered PNGs out 3×3 on Letter/A4 with bleed and cut marks, as a 100 % PDF |
| `mint print` | send a PDF to an Epson ET-8500 at true 100 % with the right black for the stock |
| `mint serve` | the workbench: compare art, recipes and frames in a browser, and run the tools from it |
| `mint gallery` | export a set as a static, read-only gallery page |

End to end, on this machine:

```sh
mint upscale --set sets/bls1.json
mint render  --set sets/bls1.json --out proofs
mint impose  --out proofs/bls1.pdf proofs/0*.png
mint print   --test proofs/bls1.pdf        # one page on plain paper first
mint print   -p matte proofs/bls1.pdf
```

## The workbench

```sh
pip install -e '.[web]'
mint serve --open          # http://127.0.0.1:8300
mint serve --host 0.0.0.0  # reachable from a phone on the same network
mint serve --stop          # end the one running for this workspace (Ctrl-C in its terminal also works)
```

A local page over the workspace, for comparing and deciding. It fits a phone
too: the set nav scrolls, tiles and images fall into two columns, and every
control is thumb-sized. It is installable — *add to home screen* gives it an
icon and its own window, and a service worker keeps the page shell so the app
opens (and says the server is down) without it. Browsers only install from a
secure origin: `localhost`, or https — over plain http on the LAN the home
screen entry is a bookmark that opens in the browser. For a real install from
a phone, front it with https (`tailscale serve 8300` does it in one line).

- **Sets** — *new set* makes a set file from a pasted decklist (code, name,
  a style template). Every card is a tile (styled render,
  plain render, or just the art), with badges from the render manifest: no restyle for the current
  recipe, not rendered, stale render (the frame or the art changed since), rules text shrunk,
  Universes Beyond art, own art. *only what's missing* counts a stale render as missing.
  A search box matches name, type and artist. Order the tiles by number,
  name or *colour* (the shown image's hue, measured in the browser, so a
  take that wandered off the set's palette stands out); *sheet* drops the
  names and badges for a dense look at the pictures; *vs* puts a second look
  beside the first on every tile, the set-level A/B.
  Shift-click to select cards (or turn *select* on in the toolbar, or long-press
  a tile on a phone); render, enhance or restyle the selection. *new cards
  as …* is net-new art for the selection: the describer writes each card's
  subject line from its picture and text (cards that have one keep it), then
  a `new` scene follows from it in the look (below, "Subjects from the
  pictures").
  *all* in the nav puts every set on one board.
- **Viewer** (click a card) — the tile's image large: ← → or a swipe steps
  through the board in its current order, wheel / pinch / drag zoom and pan,
  double-click or double-tap for 2.5×,
  `s` `p` `a` switch styled / plain / art, `c` opens compare, `f` fullscreen.
- **Card** (`c`, or click a tile) — type, printing and subject up top, then
  three parts in pipeline order. *Generate*: one mode (restyle, repose, new, inspire)
  and only that mode's inputs — the look, what the picture starts from or
  takes its pose from, the seed, how many takes — all of them this card's
  own overrides, with a reset back to the set's. *Images*: the Scryfall crop,
  every variant the cache holds grouped by look with the knobs that differ
  from the set's recipe, each enhance beside the image it was made from.
  Mark two images A and B for a wipe (drag the line; wheel or pinch to zoom,
  then drag to pan), or a blind A/B.
  *Card*, at the bottom: the styled art — the variant the styled render
  uses — with the renders and their buttons.
  A restyled variant offers *keep* — it becomes the card's styled art (the
  entry's `pick`), whatever the recipe says — and *enhance*; a menu on every
  image holds *restyle / inspire from this*, *repose from this*, *pin its seed*
  and *make the set style from this*. A bin on every image deletes it, and a
  bin beside each group's heading empties the group (the source group's takes
  only the crop's enhances; the crop itself is fetched, not made).
- **Edit** — the set file as a form: its own fields (code, name, size, note,
  art filter, restyle base), the style block (edit the knobs, replace it
  from a template, save it as one, remove it) and the card list — every
  entry's number, subject, flavor, own art, art filter, seed and remix in a
  table, with move, rename, remove, add-from-decklist and renumber. Delete
  the set from here too; renders and the art cache stay.
- **Styles** (*styles* in the nav) — the templates in `styles/`: make one,
  edit every knob, its css and its frame knobs, apply it to a set (its frame
  knobs come along), delete it. Which sets carry each is shown; a
  set's block is a copy, so editing a template changes no set until it is
  applied again.
- **The look** — one picker on the board, in the viewer and beside the
  card's restyle button: the set's own recipe, any restyle the art cache
  holds, or a template not run yet. A styled tile shows that look, the
  filter finds cards without it, and *restyle* makes it — from each card's
  own base, subject, seed and remix mode. Variants land under the look's
  name, side by side on the card page; *keep* adopts one for its card, *make
  the set style from this* for the set. The `× N` beside the button makes N
  takes per card, each from its own random seed, to choose between. Takes
  are drafts — no ESRGAN pass, which is a large share of a take's time — so
  *keep* the one you like and *enhance* it; the renderer picks the enhance
  up. (The base's resolution doesn't matter for speed: everything is scaled
  to the generation size first.)
- **Recipe lab** — a form for every knob in the style block, a few probe
  cards, and a run button; results land as variants in a probe-by-recipe
  grid as they finish. New knobs are one field in `sets.Style` and one node
  in the workflow; the form follows.
- **Frame** — a slider per frame knob (watermark, art bevel, box grain, foil
  stamp, rarity tint), saved to the set file as you let go; edit the set's
  CSS and render a 300 DPI proof; overlay a Scryfall scan on your render to
  check text placement; render one card in every font theme.
- **Print run** (on the board, beside the render buttons) — one job that
  renders the cards whose render is missing or stale, lays them out 3×3 as
  a PDF under `out/<code>/print/`, and, when a stock is picked, sends it to
  the workspace's printer at 100% with `mint print`'s checks. The PDF is
  linked from the job and opens on the set's pdf page.
- **Pdfs** (*pdfs* on the board) — the set's print runs and `mint impose`'s
  `out/<code>.pdf`, newest first, with every page of the picked one shown
  as an image (poppler's `pdftoppm` renders them, cached like thumbnails).
  *Open* shows the file in the browser's own viewer, *download* saves it to
  the device the page is on, and *export* copies it to `export_dir` (the
  Desktop unless `mint.toml` says otherwise) on the workbench's machine, for
  another PDF app to print from; it asks before replacing a file already
  there. *Delete* removes a PDF; the renders it was made from stay.
- **Jobs** — what is queued and running, with logs and cancel.

`mint gallery --set sets/x.json` exports the Sets and Compare views as a
static read-only page with thumbnails, for sharing a set's look.

## Fonts

The frame wants Beleren (titles) and MPlantin (rules text). They are not
ours to redistribute; `fonts/README.md` says where each is published and how
to repair the community copies that Chromium's font sanitizer rejects.
Without them the closest open faces are substituted automatically.

## Art: upscaling and ComfyUI

Scryfall's art crops are ~626×457 — about 300 DPI on the card, visibly soft
next to a vector frame. `mint upscale` sends them through a local
[ComfyUI](https://github.com/comfyanonymous/ComfyUI) server and keeps the
4× result as an *enhance* variant (`art/<illustration_id>/enhance-<hash>.png`,
~1130 DPI); `mint render` uses it whenever it exists. `--base HASH` enhances
a restyled variant instead, and styled renders then pick that up.

```sh
# in your ComfyUI checkout, once: an upscale model in models/upscale_models/
curl -L -o models/upscale_models/4x-UltraSharp.pth \
  https://huggingface.co/Kim2091/UltraSharp/resolve/main/4x-UltraSharp.pth
python main.py --listen 127.0.0.1 --port 8188      # leave it running

# in your workspace
mint upscale --set sets/bls1.json                  # ~2 s a card on an RTX 5070 Ti
mint upscale --model RealESRGAN_x4plus.pth "Cyclonic Rift"
```

4x-UltraSharp is the default: on painted card art it keeps canvas grain and
brushwork where Real-ESRGAN x4plus goes smooth and plasticky. `COMFY_URL`
points at a server elsewhere. `mint/comfy.py` is a ~100-line client (upload,
queue a workflow, fetch outputs) that any other ComfyUI workflow can reuse.

## Art styles: one look per set

A set can carry a `style` block, and `mint restyle` regenerates every card's
art in that style through ComfyUI. The idea is that the style *is* the set's
identity — you don't mix styles inside one set, you make a set per look:

| set | look | why |
|---|---|---|
| Satoru (ninjas, Kamigawa: Neon Dynasty) | cyberpunk neon | the source set is already cyberpunk Kamigawa |
| Meren (graveyard, sacrifice, Yawgmoth) | dark-fantasy ink manga, heavy cross-hatching | tonally already there |
| Niv-Mizzet (Izzet) | stained glass / art nouveau | the guild's whole aesthetic |

### How it works

Plain img2img can't do this: at the denoise strength a real style change
needs (0.7+) the composition dissolves; below that you get a filter. So the
workflow is **img2img with structure control**: a ControlNet fed from the
original art — lineart or canny for ink styles, depth for painterly ones —
keeps *what's there* (the figure, the pose, the light) while the prompt and
an optional style LoRA reinvent *how it's drawn*. Denoise 0.8–0.95.

```
LoadImage (art crop) ─┬─ preprocessor (canny / lineart / depth) ─ ControlNet ─┐
                      └─ VAEEncode ────────────────────────────── KSampler ───┴─ VAEDecode ─ UltraSharp ─ SaveImage
CheckpointLoader ── CLIPTextEncode (style prompt / negative) ───────┘
```

The style block lives in the set JSON:

```json
"style": {
  "name": "neon",
  "prompt": "cyberpunk fantasy illustration, neon-lit rain, holographic signage, chrome and lacquer, cinematic rim light",
  "negative": "blurry, text, watermark, frame, border",
  "control": "canny", "control_strength": 0.8,
  "denoise": 0.85, "steps": 28, "cfg": 6, "seed": 7,
  "checkpoint": "juggernautXL_v9.safetensors",
  "loras": [{"name": "some-style.safetensors", "strength": 0.7}]
}
```

Every result is a *variant*: `art/<illustration_id>/<style>-<hash>.png` with a
`.json` sidecar holding the exact recipe and the image it started from. The
hash is the recipe's, so changing a knob makes a new file beside the old one
instead of overwriting it, and every attempt stays available to compare.
`mint render --styled` uses the variant matching the set's *current* recipe,
falling back to the CSS `art_filter` for cards that don't have one yet
(`mint check` lists which). Because everything is in the set file, a set's
look is reproducible and committed — same seed, same prompt, same models.
Each card's seed comes from the set's seed and its illustration id
(`"seed_rule": "stable"`), so cards differ, reruns don't, and adding a card
never changes another's; sets migrated from before this carry
`"seed_rule": "position"` so their existing images stay current.

`"remix"` in the style block (or per card) is what a restyle keeps of the
picture it starts with — four modes: **`restyle`** redraws it in the style
(img2img + ControlNet, the default); **`repose`** is a fresh picture that
holds only an OpenPose skeleton — read from the card's `"pose"` image (a
variant hash, or a path to any picture), else its base — at
`repose_strength` (0.5) until `repose_end` (0.3) of the steps; body,
clothes, hair and background are new, and a different pose image moves
the joints (a canny / lineart / depth map *is* the pose, whatever the
strength, which is why a restyle never moves a figure); **`new`** is a new scene from the prompt alone,
with the card's `subject` line (else its name and type line) as the only
thread back to the original; **`inspire`** is a new scene with the base as
an IP-Adapter reference — its look, palette and character carry over as if
they were part of the prompt, nothing holds its layout, and the words
decide the pose and the scene — at `inspire_weight` (0.7) until
`inspire_end` (0.8) of the steps, `inspire_type` `standard`, `prompt first`
(the words settle the composition before the image weighs in) or `style`
(the look without the subject). inspire needs the ComfyUI_IPAdapter_plus
node pack with `ip-adapter-plus_sdxl_vit-h.safetensors` in
`models/ipadapter` and `CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors` in
`models/clip_vision`. `"refine": 0.4` adds a second sampling pass at
1.5× the size for detail, and `"clip_skip": 2` is what Pony-family
checkpoints want.

Per card, `"base": "<variant hash>"` starts the restyle from an enhanced or
earlier restyled image instead of the crop, `"seed": 123` pins a seed you
liked, and `"pick": "<variant hash>"` names the variant styled renders use
outright — a take from a random seed, or one in another look — without the
recipe having to match it.

A card entry can add `"subject": "a red dragon with a blue-finned crest,
wings spread"` — prepended to the prompt so the style can't drift a character
into someone else (without it, the stained-glass Niv-Mizzet came out as an
art-nouveau woman). Commanders and named characters want one.

### Subjects from the pictures

A `new` scene has nothing but the subject line to tie it to the card, and
writing one for every card of a set is the slow part. `mint describe` does
it: a vision model reads the card's base image (the crop, or whatever its
restyles start from) with the card's name, type line and rules text,
describes what the picture shows, and writes a subject line from the three
— the figure's identity and look from the picture, the action from what the
card does, a scene that may be new, and no medium or palette words, which
the style prompt supplies. The subject goes into the set file like a
hand-written one (cards that already have one are kept unless `--force`);
the description sits beside the image (`art/<id>/described.json`) and the
card page shows it under the subject, with a *from the picture* button that
writes one card's line. `--generate` — or *new cards as …* on the board —
then makes each card's `new` scene in the set's style, the `new` mode over
whatever the style or the card says, so the variant lands beside the others
and *keep*, or a style whose `remix` is `new`, makes it the card's art.

```sh
mint describe --set sets/sat.json                    # every card without a subject
mint describe --set sets/sat.json --force "Satoru"   # rewrite one
mint describe --set sets/sat.json --generate         # and each card's new scene
```

The describer is `claude` (the Anthropic API; `ANTHROPIC_API_KEY` in the
environment, about a cent a card) or `ollama` (a local Ollama with a vision
model such as `qwen2.5vl`); `mint doctor` says whether it could take a call.

```sh
mint newset --code SAT --name "Satoru, ..." --style neon decks/satoru.txt   # sets/sat.json
mint restyle --set sets/sat.json                                             # ~13 s a card
mint render  --set sets/sat.json --styled --out proofs
```

Three recipes ship in `mint newset`: `neon` (canny control), `ink`
(lineart control, monochrome), `glass` (canny). They are starting points;
the block in the set file is the source of truth once created.

### Frame designs

The frame is M15, and a set (or one card) can ask for one of its modern
variants with `design`; each is measured off Scryfall scans of real
printings of its kind, and `mint/designs/<name>.css` carries the numbers:

- `extended` — the art off the card's sides, from under the title bar to
  the text box; a black-glass type bar over it, the corners feathered
  black, a legendary's crown cut to the bar (2019+ Commander decks and
  collector boosters).
- `borderless` — the picture out to the cut edge on all sides, the M15
  bars and text box floating on it on a pinline plate, the collector line
  on a black foot with the picture's corners arced into it.
- `fullart` — the art under everything; a basic gets the type bar at the
  foot with the mana medallion, a card with rules text a smoked-glass
  type bar and text plate, the collector line on a black strip.
- `auto` — each card takes its printing's design (`full_art`,
  `border_color`, `frame_effects: extendedart`).

A design steers the default printing to its own kind and sizes restyles
and clips to its art rectangle. Sagas, classes, splits and battles keep
the M15 frame whatever the design.

### Style templates

A style you want to reuse lives in `styles/<name>.json` — a bare style block,
plus an optional `styles/<name>.css` with the frame rules that go with it, and
an optional `frame` key holding the frame knobs, so a template brings its
whole look (a set that takes it takes the knobs too):

```sh
mint style save NIV                 # -> styles/glass.json, named after NIV's style
mint style save NIV --as cathedral  # under a name of your own
mint style list                     # templates on disk, then the built-ins they don't shadow
mint newset --code ABC --name "..." --style cathedral decks/abc.txt
```

Sets, templates, art variants and renders are all the workspace's, not the
repo's: git ignores `sets/`, `styles/`, `art/` and `out/`. The recipes this
project was built with are kept as reading matter in `docs/examples/styles/`
(stained glass, ink, linocut, woodblock, vanitas ...); copy one into
`styles/` to use it.

### Models

Nothing is bundled. SDXL is the practical choice on a 16 GB card (mature
ControlNets, ~5–8 s a card); Flux is prettier for painterly work but heavier.
Into ComfyUI's `models/`:

- `checkpoints/` — an SDXL checkpoint tuned for illustration (Juggernaut XL,
  DreamShaper XL, or base SDXL 1.0)
- `controlnet/` — xinsir's **ControlNet Union SDXL (promax)**: one file that
  covers canny, lineart, depth and more
- `loras/` — style LoRAs as wanted (Civitai is the usual source)
- later: IP-Adapter Plus, to anchor a whole set on one reference image

Preprocessors beyond canny (lineart, depth) come from the
`comfyui_controlnet_aux` custom node pack.

### On naming artists

Describe the style, don't invoke the person. "Confident single-weight pen
lines, dense architectural detail, fisheye crowds, no underdrawing" gets you
the Kim Jung Gi *feel*; a LoRA trained on his work days after his death in
2022 is the poster case for why not to do the other thing. Same for Miura —
"dark fantasy manga, heavy cross-hatching, screentone, black-ink dominant"
is the style; the name is a person. The original illustrator stays credited
in the footer either way: the composition is still theirs.

### Notes per style

- **Cyberpunk neon** — easiest, works from prompt alone with depth or canny control.
- **Ink line art** — most distinctive on a card (black ink in a full-colour
  M15 frame reads like WotC's artist-sketch cards). Lineart control at high
  weight; generate large — hatching is what the upscaler destroys first.
- **Dark manga / Berserk-style** — the hardest without a LoRA; base models
  give "generic dark manga." Worth it with a good dark-fantasy-manga LoRA.

## Art with motion: a clip per card

The card page of the workbench has an **animate** button on every image --
the crop, an enhance, any restyle -- and one on the styled-art line. Each
makes a two-second seamless loop of that image through Wan 2.2 (the 5B
TI2V model, image-to-video) and files it in the art cache as a *motion
variant*: a poster PNG (the loop's first frame) with the `.webm` beside it.
The clip plays in place on the card page and in the viewer; the poster is
what everything else sees, so renders, `gc`, `describe` and the gallery are
untouched. It is a clip of the *art*, not of the card, and never goes near
a PDF.

Where the clip starts from is the image whose button you press; the
styled-art button takes what `render --styled` would use, enhance included
-- which is how a set's SDXL look reaches the clip, since Wan cannot run an
SDXL LoRA but can animate the picture one made. The *motion* line on the
page is this card's own words for what moves, in place of the block's
prompt; the loop and length pickers beside it are for the run alone. Say
what moves and what stays still ("hair drifts, the figure breathes, the
camera is still"); "cinematic" and "camera pans" get a music video.

The knobs live in an optional `motion` block in the set file, every one
with a default, so a set without a block still animates:

```json
"motion": {
  "prompt": "hair drifts as if underwater, fabric sways, the figure breathes slowly; the camera is still",
  "remix": "animate",           // animate: from the image (I2V) | new: from the words alone (T2V)
  "width": 832, "height": 576,  // multiples of 32; the art window is 1.42:1
  "length": 49, "fps": 24,      // frames, 4n+1: 49 is two seconds, 81 about three and a half
  "loop": "pingpong",           // pingpong | crossfade | none
  "formats": ["webm"]           // webm | gif | apng | mp4, each written beside the poster
}
```

Per card, `"motion": "the wave curls and crashes, spray drifts"` replaces
the prompt. The effective recipe is hashed into the file name like a
restyle's, so a re-restyle of the base, a new line, or any knob is a new
clip beside the old one; the raw frames are not kept (re-looping means
regenerating). `mint animate --set sets/x.json ["Card" ...]` does the same
from the shell, `--from HASH` naming the image and `--remix new` a clip
from the words alone.

Into ComfyUI's `models/`, from Comfy-Org's `Wan_2.2_ComfyUI_Repackaged`
(`mint doctor` prints the URL of each one missing):

- `diffusion_models/wan2.2_ti2v_5B_fp16.safetensors` (10 GB)
- `text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors` (6.7 GB)
- `vae/wan2.2_vae.safetensors` (1.4 GB)

The 5B model fits a 16 GB card at 832 px with room to spare: about 50 s a
clip at 49 frames on an RTX 5070 Ti, plus the model load the first time.
`ffmpeg` does the encoding and has to be on PATH. The 14B pair is prettier
but needs a two-stage sampler and quantised weights; a second engine, later.

## Universes Beyond

Crossover printings (Marvel, Spider-Man, TMNT, Fortnite, …) are not wanted
as an art source here. Scryfall stamps every one of them `security_stamp:
"triangle"`, and the renderer warns whenever the printing it is about to use
carries it — except for sets in `UB_EXEMPT` (Lord of the Rings, which fits
Magic well enough). With the oracle-cards file there is one printing per card,
so the warning is all it can do; with `mint cards --kind default_cards` the
renderer picks the newest non-crossover printing by itself, and a card's
`printing` key picks one by hand. Cards that only exist in a non-exempt
crossover set will always warn — that's a deck decision, not a render one.

## What's not here yet

- IP-Adapter style anchoring for set-wide consistency
- layouts beyond `normal`: split, adventure, planeswalker, saga (double-faced
  cards render both faces in the normal frame with `--faces`)

## Legal

Card names, rules text and art are © Wizards of the Coast. This tool is for
personal proxies; share renders the way the MPC Autofill community does and
don't sell them. The code is MIT.

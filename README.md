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
| `mint newset` | start a set file from a decklist (commander first); `--style neon|ink|glass` seeds a style block |
| `mint render` | render cards by name or from a set file; `--compare` audition every font theme on one sheet |
| `mint restyle` | regenerate every card's art in the set's style through ComfyUI (img2img + ControlNet) |
| `mint upscale` | 4× ESRGAN the art through a local ComfyUI; renders pick the result up automatically |
| `mint calibrate` | measure title / type / P/T text placement on real Scryfall scans vs ours, in 1/100 in |
| `mint cards` | fetch or refresh Scryfall's bulk card file (`--kind default_cards` for per-printing art) |
| `mint fonts` | report which frame fonts are present |
| `mint impose` | lay rendered PNGs out 3×3 on Letter/A4 with bleed and cut marks, as a 100 % PDF |
| `mint print` | send a PDF to an Epson ET-8500 at true 100 % with the right black for the stock |

End to end, on this machine:

```sh
mint upscale --set sets/bls1.json
mint render  --set sets/bls1.json --out proofs
mint impose  --out proofs/bls1.pdf proofs/0*.png
mint print   --test proofs/bls1.pdf        # one page on plain paper first
mint print   -p matte proofs/bls1.pdf
```

## Fonts

The frame wants Beleren (titles) and MPlantin (rules text). They are not
ours to redistribute; `fonts/README.md` says where each is published and how
to repair the community copies that Chromium's font sanitizer rejects.
Without them the closest open faces are substituted automatically.

## Art: upscaling and ComfyUI

Scryfall's art crops are ~626×457 — about 300 DPI on the card, visibly soft
next to a vector frame. `mint upscale` sends them through a local
[ComfyUI](https://github.com/comfyanonymous/ComfyUI) server and caches the
4× result (`art/<illustration_id>.x4.png`, ~1130 DPI); `mint render` uses it
whenever it exists.

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
points at a server elsewhere. `mint/comfy.py` is a ~60-line client (upload,
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

Results are cached as `art/<illustration_id>.<style name>.png`; `mint render
--styled` uses them, falling back to the CSS `art_filter` for cards that
haven't been restyled yet. Because everything is in the set file, a set's look
is reproducible and committed — same seed, same prompt, same models. Each
card's seed is derived from the set's, so cards differ but reruns don't.

A card entry can add `"subject": "a red dragon with a blue-finned crest,
wings spread"` — prepended to the prompt so the style can't drift a character
into someone else (without it, the stained-glass Niv-Mizzet came out as an
art-nouveau woman). Commanders and named characters want one.

```sh
mint newset --code SAT --name "Satoru, ..." --style neon decks/satoru.txt   # sets/sat.json
mint restyle --set sets/sat.json                                             # ~13 s a card
mint render  --set sets/sat.json --styled --out proofs
```

Three recipes ship in `mint newset`: `neon` (canny control), `ink`
(lineart control, monochrome), `glass` (canny). They are starting points;
the block in the set file is the source of truth once created.

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

## What's not here yet

- IP-Adapter style anchoring for set-wide consistency
- layouts beyond `normal`: split, MDFC, planeswalker, saga
- picking art from a specific printing (`mint cards --kind default_cards`
  fetches the data; the render still uses the oracle default)

## Legal

Card names, rules text and art are © Wizards of the Coast. This tool is for
personal proxies; share renders the way the MPC Autofill community does and
don't sell them. The code is MIT.

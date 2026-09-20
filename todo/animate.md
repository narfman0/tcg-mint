# Card art with motion: `mint animate`

Not started. A plan, scoped 2026-09-20, to fold what tcg-motion does into
tcg-mint so a set can carry a `motion` block the way it carries `style`,
and each card gets a short seamless loop of its art beside its stills.

## Why here and not in tcg-motion

tcg-motion (`../tcg-motion`) already animates a still through ComfyUI, but
it is a copy of this repo's shapes: `motion/comfy.py` is `mint/comfy.py`
plus 40 lines, a reel is a set, `recipe_hash` is `sets.recipe_hash`, and
`motion pull` exists only to carry art across the repo boundary. Living
here it inherits the set file, the art cache, the workbench, `check`,
`doctor` and `gc` for free. tcg-motion keeps the one thing this plan does
not take -- animating a *region* of a still and compositing it back -- or
retires.

## The shape

### Set file: a `motion` block beside `style`

```json
"motion": {
  "prompt": "hair drifts as if underwater, fabric sways, the figure breathes slowly; the camera is still",
  "negative": "static, still image, frozen, blurry, low quality, text, watermark, flicker, jump cut",
  "remix": "animate",           // animate: from the card's styled art (I2V) | new: from words alone (T2V)
  "width": 832, "height": 576,  // the art window is 1.42:1; both multiples of 32
  "length": 49, "fps": 24,      // frames, 4n+1; 49 at 24 fps is two seconds, 81 is ~3.4 s
  "steps": 20, "cfg": 5.0, "shift": 8.0, "sampler": "uni_pc", "scheduler": "simple",
  "seed": 7, "seed_rule": "stable",
  "loop": "pingpong",           // pingpong | crossfade | none
  "crossfade": 12,              // frames blended tail-into-head when loop = crossfade
  "formats": ["webm"],          // webm | gif | apng | mp4
  "gif_width": 480,
  "model": "wan2.2_ti2v_5B_fp16.safetensors",
  "text_encoder": "umt5_xxl_fp8_e4m3fn_scaled.safetensors",
  "vae": "wan2.2_vae.safetensors",
  "loras": []                   // [{"name": "x.safetensors", "strength": 0.8}], model-only
}
```

Per card, `"motion": "the wave curls and crashes, spray drifts"` replaces
the prompt, the way `subject` steers restyle. A card can also override
`loop`, `length` and `seed` for motion (a `motion_*` prefix on the entry,
or a small object -- decide when writing `CardEntry`; keep unknown keys
errors as everywhere else).

Two modes, one graph:

- **animate** (default): image-to-video from the card's styled art -- the
  same file `render --styled` would use (`Art.resolve(card, style_hash=...)`,
  enhance included). This is how the set's look reaches the clip: Wan
  cannot run an SDXL LoRA, but it can animate the picture one made. Falls
  back to the crop when the set has no style. `base` in the recipe is that
  variant's hash (or `"crop"`), so a re-restyle is a new motion variant.
- **new**: text-to-video, no image. The card's `subject` line (from
  `mint describe`, else name + type line, as `SetFile.recipe` does at
  `sets.py:238`) is prepended to the prompt; `base` is `"none"`, as in
  restyle's `new` at `sets.py:249`. Wan 2.2 TI2V-5B is a unified T2V/I2V
  model, so this is the same node with `start_image` left out
  (`ComfyUI/comfy_extras/nodes_wan.py:1437`).

### Art cache: a variant of kind `motion`

`Art._read` (`art.py:119`) resolves every variant to a `.png`, and render,
the workbench, `gc` and `describe` all assume an image. Keep that true:

- `art/<illustration_id>/<label>-<hash>.png` is the **poster**, frame 0 of
  the loop. Everything that exists keeps working on it unchanged.
- `art/<illustration_id>/<label>-<hash>.webm` (and any other format asked
  for) sits beside it. `Variant` gains a `videos` property that lists the
  siblings; nothing else in `art.py` changes.
- The raw frames are not kept (unlike tcg-motion's `.frames/`): the loop
  treatment is cheap enough to redo by regenerating, and the cache is
  already the biggest thing in the workspace. If re-looping without the
  GPU turns out to matter, keep `<label>-<hash>.frames/` and add
  `mint animate --post`.
- Label: the motion block's `name` if it has one, else `"motion"`.
- `gc.py`: a motion variant's siblings go when its sidecar does; a
  restyle variant that a motion variant names as `base` is in use.

## What moves from tcg-motion (adapt, don't copy blind)

| from `../tcg-motion` | to | notes |
|---|---|---|
| `motion/wan.py` `workflow()` | `mint/wan.py` | `image_name=None` drops the LoadImage node and the `start_image` input; keep the `FILES` table for doctor |
| `motion/post.py` `pingpong`, `crossfade`, `looped`, `encode_args`, `encode` | `mint/loop.py` | drop `region_frames`, `feather_mask`, `composite`, `produce`, `main` |
| `motion/comfy.py` `Comfy.run_to_frames` | `mint/comfy.py` | `choices()` is already `options()` here; `fetch()` may already exist as part of `run_to_file` -- reuse |
| `motion/animate.py` `animate_clip` | `mint/animate.py` `animate(server, art, card, st, force=False, remix=None, seed=None) -> (Variant, made)` | shaped like `restyle.restyle()` at `restyle.py:204`; `main()` like `restyle.main()` |
| `tests/test_wan.py`, `tests/test_post.py` | `tests/` | minus the composite/region cases; add a `new`-mode graph test (no node 7, no `start_image`) |

What stays behind: `segment.py` (region, padding, generation size),
`composite`/`feather`, `newreel`, `pull`, `check`'s region maths, the
workspace.

## New in tcg-mint

1. **`sets.py`**: a `Motion` dataclass with the knobs above and
   `validate()` (length 4n+1, width/height % 32, loop in the three,
   formats in the four, crossfade * 2 < length, each lora has a name);
   `SetFile.motion` (None when absent); `SetFile.motion_recipe(record,
   art=None, seed=None, remix=None)` mirroring `recipe()` at `sets.py:203`
   -- knobs that do nothing stay out of the hash (`crossfade` unless
   loop is crossfade, `gif_width` unless gif is asked for, `loras` when
   empty), the seed from `card_seed` with the motion block's own seed and
   rule, `base` resolved through the art cache; `motion` in `SET_KEYS`
   and `from_dict`/`to_dict`; `CardEntry.motion`.
2. **`mint/animate.py`** + `"animate"` in `__main__.COMMANDS`:
   `mint animate --set sets/x.json [--force] [--remix new] ["Card" ...]`.
   Per card: resolve the base, upload it (or not), run the graph, fetch the
   frames to a temp dir, loop, save the poster, encode each format beside
   it, record the variant. Print `animated`/`cached` like restyle does.
   `ffmpeg` is needed only here: `shutil.which` with a plain message, as
   with Chromium.
3. **`check.py`**: with a motion block, say per card whether its motion
   variant for the current recipe exists (and which base it would start
   from).
4. **`doctor.py`**: when any set has a motion block, ask ComfyUI for the
   three Wan files (`UNETLoader`/`CLIPLoader`/`VAELoader` options) and
   print the Hugging Face URL of each missing one, from `wan.FILES`; note
   ffmpeg's presence.
5. **Workbench** (optional first pass, ~25 lines): `variant_dict`
   (`web/server.py:102`) adds `videos`; `app.js` shows
   `<video autoplay loop muted playsinline>` on a tile that has one and the
   poster otherwise; a `submit_animate` beside `submit_restyle`
   (`web/server.py:935`) with the same `takes`/seed handling, and an
   *animate* button on the card page.
6. **README**: a section under the style one; the model table and sizes
   from tcg-motion's README (5B fits 16 GB at 832 px, ~1 min a clip at 49
   frames on a 5070 Ti); the prompting note ("say what moves and what
   stays still; 'cinematic' and 'camera pans' get a music video").
7. **`pyproject.toml`**: nothing new -- pillow is there; ffmpeg is a
   binary.

Rough size: ~350 lines moved, ~200 new, tests ported. A day.

## Decisions taken in this plan (change if they turn out wrong)

- Whole art only. The art window is the region; no `region`/`padding`.
- Poster PNG as the variant file, video as a sibling -- so no code that
  reads variants has to learn about video.
- `animate` mode from the styled art is in from the start; it is one
  conditional and the only way a set's style carries into motion.
- The motion block is not yet part of `mint style` templates. Add when a
  second set wants the same motion recipe.
- Frames are not kept. See above.

## Later

- The "living card": the rendered frame with the art window moving. Needs
  a render with a transparent art window (`page.screenshot(omit_background=True)`
  with `$art` unset) and the `.art` rect from `getBoundingClientRect()` in
  the manifest; then frame-over-clip at a display DPI (~300; 1200 DPI is
  3264x4464 px of webm). The bevel (`template.html:149`) stays intact that
  way. Layout-specific windows: `template.html:110, :184, :193, :224`.
- Wan 2.2 14B I2V as a second engine (two-stage high/low-noise KSamplers,
  fp8 or GGUF) when the 5B look isn't enough.
- `WanFirstLastFrameToVideo` with the same image at both ends as a fourth
  loop mode.
- Wan-format style LoRAs in `loras` if any exist for a set's look.

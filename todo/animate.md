# Card art with motion: `mint animate`

Shipped 2026-09-21 (planned 2026-09-20). What this file keeps is the
decisions and what is deliberately not done; the README's "Art with motion"
section and `mint/animate.py` say how it works.

## Decisions (2026-09-21, with the user)

- **Per card, from the card view.** The animate buttons are on the card
  page -- one per image column, one on the styled-art line -- and nowhere
  else: no board button, no set-wide batch in the workbench. `mint animate`
  exists as the shell driver and takes card names like restyle.
- **The art only.** A clip is of the art window's picture. It is not a
  "living card" (no framed render with a moving window) and it never enters
  a PDF. The living card stays in "Later" below and may never come.
- Whole art, no `region`/`padding`: the art window is the region.
- Poster PNG as the variant file (kind `motion`), the videos as siblings
  with the same stem (`Variant.videos`); nothing that reads variants learns
  about video. A poster is never a card's styled art.
- `animate` (I2V from the styled art, enhance included) is the default
  mode; `new` (T2V from the subject line + the motion line) is the other.
  The base is the pressed column's hash, else what `render --styled` uses.
- The motion block is optional: every knob has a default, so a set without
  one animates. Per card, `motion` is a string that replaces the prompt.
  Loop and length can be changed per run from the page (not saved).
- Frames are not kept; re-looping is regenerating (~50 s a clip).
- Not part of `mint style` templates.
- `takes` from the page: up to 8 clips from random seeds.

## What went where

`mint/wan.py` (graph, `FILES`, `NODES`, `url()`), `mint/loop.py`
(pingpong / crossfade / encode), `Comfy.run_to_frames`, `mint/animate.py`,
`sets.Motion` + `SetFile.motion_recipe` + `CardEntry.motion`, `check`
(motion line per card when the set has a block), `doctor` (Wan files with
their HF URL, ffmpeg -- only when a set has a block), `gc` (a clip of a
kept image stays; a variant's videos go with it), the workbench
(`submit_animate`, `wan_info` readiness with a one-line hint, the motion
row, the clip columns and the viewer playing them). tcg-motion keeps the
region/composite work and can retire otherwise.

## Closed

- **The "living card" is not wanted** (decided 2026-09-23, with the user):
  motion belongs to the picture, never to the card. The rendered frame with
  a moving art window is off the list for good, not parked -- so the
  transparent-art-window render (`page.screenshot(omit_background=True)` with
  `$art` unset), the `.art` rect in the manifest and frame-over-clip
  compositing are all unneeded, and nothing in the codebase is waiting on
  them. Do not re-propose it.

## Later
- Wan 2.2 14B I2V as a second engine (two-stage high/low-noise KSamplers,
  fp8 or GGUF) when the 5B look isn't enough.
- `WanFirstLastFrameToVideo` with the same image at both ends as a fourth
  loop mode.
- Wan-format style LoRAs in `loras` if any exist for a set's look.
- Keeping frames (`<label>-<hash>.frames/` + `mint animate --post`) if
  re-looping without the GPU turns out to matter.
- The motion block in `mint style` templates, when a second set wants the
  same motion recipe.

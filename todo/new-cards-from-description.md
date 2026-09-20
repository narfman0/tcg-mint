# Net-new cards from title, text and a description of the current art

Landed 2026-09-20: `mint describe` (`mint/describe.py`) — a vision model
reads the card's base image with its name, type line and rules text, writes
a description and a subject line, the subject into the set file (kept if
one is there, `--force` rewrites) and the description beside the image
(`art/<id>/described.json`); `--generate` runs the existing `new` flow on
it through a one-off `remix` on `SetFile.recipe` / `restyle.restyle`, so
no fifth mode and no rewritten entries. Workbench: *from the picture* on
the card page, *new cards as …* on the board (a `describe` job with
`generate`), the description shown under the subject; `mint doctor` and
`/api/workspace` report whether the describer could take a call. Two
describers, `claude` (ANTHROPIC_API_KEY) and `ollama`, picked in mint.toml.

Still open:

- **Nobody has run it on a real set.** The instructions in
  `describe.INSTRUCTIONS` are a first draft: check on BLS1 that the subject
  lines stay content-only and that a `new` scene from one is recognisably
  the card. Bump `PROMPT_VERSION` when they change.
- **A local describer is not installed**: no Ollama on this machine, no
  Florence-2 node in ComfyUI. `ollama` is wired and untested against a live
  server; a ComfyUI captioner would need a subject-writer of its own.
- The describer reads the base at whatever size it is; a 2500-px enhance
  variant as base goes to the API whole. Downscale to ~1024 px first if
  that ever matters for cost or time.
- No "describe every card" job without generate on the board — the CLI
  does that (`mint describe --set …`); add a button if it is wanted.

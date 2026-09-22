# Frame designs: extended art, borderless, full art

Planned 2026-09-21. Everything rendered so far is the M15 frame (Scryfall
`frame: "2015"`): one template, its geometry measured off scans, and an art
pipeline that assumes the M15 art window (1.37:1). This task adds the modern
variants of that frame as *designs* a set or a card can choose, without
forking the template. Retro frames (2003 / 1997) and per-set showcase frames
are out: retro is a second template and a font problem; showcase is a set
CSS hook that already exists.

## The designs

Named after Scryfall's vocabulary, so `auto` can follow the printed card:

| design | what it is | Scryfall says | art the picture must cover (card units, bleed included where it reaches it) |
|---|---|---|---|
| `m15` | the frame as it is | `frame: 2015`, black border | 210.6 x 154 (the window) |
| `extended` | the art window widened to the border, everything else M15 | `frame_effects: extendedart` | 230 x 154 (x 10-240) |
| `borderless` | no border and no band: the art runs off the card's edges between the title bar and the type bar; the bars and text box sit where they always do | `border_color: borderless`, `full_art: false` | 272 x 200 |
| `fullart` | the art under everything; the title bar floating at the top, the type bar and a translucent text plate at the foot; a card with no rules text (a basic) has no plate | `full_art: true` | 272 x 372 (the whole card) |

`auto` (the set default is `m15`; `auto` is opt-in) resolves from the
printing in that order: full art, then borderless, then extended art.

## Phase 1 -- the scaffold (done 2026-09-21)

- `frame.DESIGNS`: name -> art window, css file. `frame.printed_design(card)`,
  `SetFile.design_of(record)` (card entry > set > `auto`).
- `SetFile.design` and `CardEntry.design` (validated against the names).
- `build_html(design=...)`: the design's class on `.card`; its css
  (`mint/designs/<name>.css`) injected between the base rules and the set
  css. **Each design's css is its own file so phase 2 agents never edit
  `template.html`**, and the design files are in `frame_hash`.
- The z-order fixed once in the base template: the art at 1, everything
  that may float over it (bars, text box, P/T, stamp, loyalty, defense,
  crown, footer) at 2, so a design puts the art under the frame by moving
  it and nothing else.
- Generation size follows the design: `frame.generation_size(design,
  pixels)` picks the multiple-of-32 size nearest the design's aspect at the
  same pixel budget as the block's default (1248x912 for restyle, 832x576
  for Wan). A style or motion block that spells `width`/`height` keeps
  them. On M15 the blocks' defaults are used as they are (they *are* the
  M15 sizes), so no recipe hash moves.
- The printings picker: `oddness(card, design)` does not count the design's
  own effect as odd, so a card set to `fullart` defaults to its newest
  full-art printing.
- Workbench: a design select on the set's frame page (saved to the set) and
  in the card view (saved to the entry); the design named on the card page.
- `mint check` reports a card whose design asks for art the printing's crop
  cannot cover (aspect further than 15% from the design's).
- Stub css files for `extended`, `borderless`, `fullart` (comments only)
  so every name renders -- as M15 -- until phase 2 fills them.

## Phase 2 -- one agent per design, in parallel, in worktrees

Each agent owns `mint/designs/<name>.css`, that design's row in the table
above if the measurements move it, its tests, and nothing else shared. For
each:

1. Pull three to five Scryfall scans of real printings of the kind
   (`Art.scan`; the printings API lists them, `oddness` names why) and
   measure the geometry the way `template.html`'s header did for M15:
   where the art starts and stops, where the bars sit, plate opacity,
   whether the pinline plate survives, what the footer sits on (full art
   prints the collector line on a black strip).
2. Write the css: move or hide the M15 pieces; never restate them.
3. Art source: what the design does when the picture is the wrong shape.
   `cover` crops (the M15 window into a full-art card loses the sides --
   the mock cut the bears' heads off); the design says whether that is
   acceptable, whether the picker should prefer a printing of its kind,
   and whether an outpaint step (ComfyUI inpaint from the window crop out
   to the design's rectangle) is worth a follow-up task.
4. A golden test (`tests/golden`) of one card in the design, and a
   contact sheet of the design across the normal layout and a basic land.

Layouts stay M15 in this pass: a saga, split or battle card in a non-M15
design renders M15 and `check` says so.

## Phase 3 -- merge and review (serial)

Merge the three; render designs x {normal, basic, legendary, rare with
stamp} into one sheet; one review pass across the three css files so
their conventions agree (plate opacity, pinline handling, footer strip);
README section; `mint calibrate` gains a `--design` if the agents made
measuring reusable.

## Decisions

- Designs are not dressing knobs: a design moves pieces, a knob fades them.
  A set's css still wins over both.
- The set default is `m15`, not `auto`: a set styled for M15 should not
  change frame because a basic's default printing is full art.
- A design changes the restyle recipe hash only through the generation
  size, and only off M15.

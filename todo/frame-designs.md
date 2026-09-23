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
| `extended` | the art off the card's sides between the title bar and a black glass type bar, everything else M15 | `frame_effects: extendedart` | 272 x 179.4 (the page's width, y 37-216.4) |
| `borderless` | no border and no band: the art runs off the card's edges from its top to the type bar; the bars and text box float on it where they always sit, on a pinline plate, the collector line on a black foot | `border_color: borderless`, `full_art: false` | 272 x 206 (the page's width, its top edge to the type bar) |
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

## Phase 2 -- one agent per design, in parallel, in worktrees (done 2026-09-21)

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

## Phase 3 -- merge and review (done 2026-09-22)

Merged the three onto the crown fix; the sheet (designs x creature, legend,
basic, stamped rare, saga) rendered and looked over; the conventions
reconciled: the layouts whose art is elsewhere fall back to M15 in
`build_html` (`frame.M15_LAYOUTS`) instead of each css scoping its own
selectors three different ways; the card carries `rarity-<r>` so a design
can style by rarity (extended's set-symbol halo, which had used "not
stamped" as a stand-in); `frame.DESIGNS` holds the measured rectangles
(extended 272 x 179.4, borderless 272 x 206); fullart's stamp disc follows
the re-measured bite. The plate opacities differ by design on purpose --
each is what its printings do. README section written. `mint calibrate
--design` landed 2026-09-22: the agents measured with one-off scripts, so the
half-way-point rule they used is now a band finder in calibrate.py that runs
against any design (calibrate.bands / edges), matched against the printings
whose own frame is that design.

## Decisions

- Designs are not dressing knobs: a design moves pieces, a knob fades them.
  A set's css still wins over both.
- The set default is `m15`, not `auto`: a set styled for M15 should not
  change frame because a basic's default printing is full art.
- A design changes the restyle recipe hash only through the generation
  size, and only off M15.

## Phase 4 -- textless, the 2003 frame, the 1997 frame (done 2026-09-22)

Three more designs, named by Scryfall's markers so `auto` follows them:
`textless` (`textless: true`; the whole page, only the title bar and the
collector line), `modern` (`frame: "2003"`, Eighth Edition to M14) and
`retro` (`frame: "1997"` and `"1993"`, the old border). The card now
carries `kind-<k>` (W U B R G gold artifact land C) so a design can carry
a palette of its own by colour, which the two era frames need, and the
era designs choose their own fonts from the local stacks (Matrix Bold for
2003, a Goudy Medieval stand-in for 1997; never a Google font in the
wizards theme). The M15 pieces are all absolutely placed, so an era frame
is a design that moves and repaints them, not a second template; if one
turns out to need a hook in the base (a piece M15 has no element for),
the smallest one, called out in the report. `frame.DESIGNS` holds
provisional art rectangles for the two era frames; the agents measure
the real ones and report them. Same rules as phase 2: one agent per
design in a worktree, scans not eyeballing, a golden, the M15 render
pixel-identical, `mint check` warns of a wrong-shape picture.

Merged 2026-09-22. The measured art rectangles are in `frame.DESIGNS`
(textless 210.6 x 303.6, modern 208 x 153, retro 192.5 x 153.7); no design
needed a hook in the base. `cards.oddness` gained the rule the textless
agent found: a printing of the design's own kind is not odd for what makes
it one -- its markers, its border, and the promo or box set that is the
only place some of them are printed -- so `design: "textless"` now picks a
textless promo instead of the plain printing. A planeswalker renders in
every design (the modern and textless agents mended theirs; retro's is an
anachronism that renders). `mint calibrate --design` landed with phase 3.

## Phase 5 -- the art a design's own printing carries (2026-09-23)

The one thing phase 4 left: **Scryfall's `art_crop` is the M15 window
whatever the printing is**, so a textless promo -- a card whose picture runs
the height of the face -- hands us 626 x 457 of landscape for a window that
wants 210.6 x 303.6. `cover` then keeps the aspect and throws away well over
half of it, and `mint check` has had nothing better to say than that it is
about to happen.

The fix is a second art source beside the crop: cut the picture out of
`art/scan_<id>.png`, the full-card scan the art cache already fetches for
`mint calibrate`, at the rectangle that design's *printings* leave
uncovered. For textless that is the M15 window's width from under the art's
line beneath the glass bar to the flat foot -- 19.6-230.2 x 39.6-320.6, the
numbers textless.css measured off twelve promos. Its foot carries the P/T
plate, the stamp's bite and the foot's sweep; those sit at M15's coordinates
in the print and at M15's coordinates in our render, so our own opaque pieces
land back on top of them.

- `frame.ART_RECT` (where each design's art sits -- the origin `DESIGNS`'
  size never had) and `frame.SCAN_CUT` (the pure-picture rectangle of a
  printing of that design). Only textless has a cut: the other designs are
  unmeasured, and a design with no entry behaves exactly as it does today.
- `Art.cut(card, design)` cuts and caches `art/cut_<design>_<id>.png`.
- `Art.resolve(..., design=...)` prefers it -- and an enhance made from it --
  when the design has a cut, the *printing* is of that design
  (`frame.printed_design`), and the plain crop does not fit the design's
  rectangle. Every caller of resolve passes the design, so the render, the
  stale check, `check`, `gc` and the workbench all agree on what a card
  renders with.
- The base name is `cut` (`cut:<design>` spelled out), so a restyle can start
  from it and say so in its recipe rather than "crop" quietly meaning
  something else.

Left for whoever measures them: a cut for `fullart`, `borderless`,
`extended`, `modern` and `retro`. Each wants the same treatment as textless
-- real scans, the half-way-point rule, the rectangle the print leaves
unpainted -- and none of them is guessed at here.

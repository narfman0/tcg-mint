# Two-colour frames: the gradient on dual lands, fetches and hybrid spells

Not started. Noted 2026-09-21.

The real M15 frame gives a two-colour card a left-to-right gradient rather
than gold when the card is *exactly* two colours in a way the frame can
name: the pinline, title bar, type bar and text box run colour A on the
left into colour B on the right, blending across the middle third. Breeding
Pool is green into blue, Verdant Catacombs (from KTK on; the ZEN printing
was plain land) black into green, Misty Rainforest blue into green, and a
hybrid spell like Kitchen Finks goes green into white. We paint all of
these flat today: lands get the land band (`FRAMES["land"]`), and any card
with two `colors` falls to `gold` in `frame.frame_kind`.

## Which cards

- **Lands that make two colours** -- duals, shocks, checks, pain lands,
  bounce lands: `produced_mana` holds exactly two of WUBRG. Order is the
  WUBRG order Scryfall gives; the real cards paint them in that order too
  (Breeding Pool G→U, Watery Grave U→B).
- **Fetch lands**: `produced_mana` is empty and so is `color_identity`, so
  the pair has to come off the oracle text -- "Search your library for a
  Swamp or Forest card" → B, G. Map the five basic land types to colours;
  take the pair only when exactly two distinct types appear in one search
  clause, so Prismatic Vista and Evolving Wilds stay plain land.
- **Hybrid spells**: `colors` has two entries and every coloured pip in
  `mana_cost` is a hybrid symbol (`{G/W}`, `{2/W}` counts too). A card
  with any plain coloured pip alongside (Figure of Destiny is fine, but
  Lorehold Command is not) stays gold. Three-colour hybrid stays gold.
- Everything else with two colours stays gold, as now.

## The shape

`frame_kind` keeps returning one key; add beside it a `frame_pair(card)`
that returns `(a, b)` or None. `page()` then builds the css from the two
`FRAMES` entries: for each of bar, bar-edge, box and pinline a
`linear-gradient(90deg, A 0 35%, B 65% 100%)` in place of the flat colour,
the `--frame` band on a land pair staying the land band with a dual tint
the way `land_tint` greys one colour today (measured off a shock land scan
rather than guessed), and on a hybrid spell taking the gradient outright.
The template's `var(--bar)` sites go through `color-mix` with `--frame`
(`template.html:169,198,205`) -- those mixes take an image, not a colour,
so the mixed values become their own gradient variables. `.pinline` is a
set of absolutely positioned strips, so each strip needs
`background-attachment`-style positioning against the card, not its own
box: `background-size: 250px` and a negative `background-position` per
strip, or one gradient on the `.pinlines` plate with the strips cut from
it by a mask.

Check against scans the way the pinline plate was: Breeding Pool (RVR),
Verdant Catacombs (MH2), Kitchen Finks (MMA) at 745x1040, the band's median
in the left, centre and right thirds.

## Open

- Whether `land_tint`'s one-colour grey mix and the pair's mix are the
  same recipe; measure a shock land before deciding.
- Split cards with two different single colours already turn sideways
  (`layout == "split"`) and each half gets its own frame on the real card;
  out of scope here, note it if the gradient code makes it cheap.
- The workbench card page shows the frame kind; show the pair.

# Examples

`sets/` and `styles/` are the workspace's own and git ignores them; these are
the shapes, as reading matter.

- `set.json` — a set file with one of every kind of card entry (`mint/sets.py`
  documents the keys), a style block, a motion block, the frame knobs and a
  design. `set.css` is the css a set may carry beside it.
- `styles/*.json` — the style templates this project was built with. Copy one
  into `styles/` and `mint newset --style <name>` or the workbench's styles
  page can use it.
- `foil-test-set.json` — nine cards for judging foil, one per imposed page,
  each owning one thing a mirror substrate does differently from paper: the
  frame colour that cannot shine, the two that shine most, saturation, the
  smallest type, the widest flat area, a planeswalker's near-black furniture,
  a full-art basic's cut edge, and the 1997 frame's cream box against M15's
  dark mass. Every printing is pinned and was picked by measuring its crop —
  its `note` says which number decided each one. Copy it into `sets/` and
  print it beside `mint foil --calibrate` (see the README's Foil section).

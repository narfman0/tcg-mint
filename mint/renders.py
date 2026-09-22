"""Which render a card prints as.

A set's out/ directory holds every render ever made for its cards -- render.py names each
file for what came out, so a render that differs from the last sits beside it rather than
over it (manifest.py). This is the rule for picking one of them:

    the card's entry can pin a file name, and that pin wins whenever it is of the mode
    asked for (plain or styled); otherwise the newest render of that mode does.

A render is *stale* when the frame (template, frame.py, the set's knobs and css) or the art
it used has moved on since it was made. A pinned render never is: pinning says this card
prints as this file, whatever has changed.

The workbench, `mint export` and a print run all ask here, so they agree on what a card
prints as.
"""
from pathlib import Path

from . import frame
from .errors import MintError
from .manifest import Manifest, frame_hash


def for_card(directory, name, pin=None, manifest=None):
    """Every render `directory`'s manifest holds for this card, newest first. Each entry is the
    manifest's, plus `file`, `path`, `mode` ("plain" or "styled") and `pinned`. A double-faced
    card's back is filed under the back face's own name, so it is not one of these; `backs_of`
    finds it. Renders in another frame theme (a --compare sheet) are not the card's render.
    Pass `manifest` to walk a whole set off one read of the file."""
    d = Path(directory)
    out = []
    mine = {name, name.split(" // ")[0]}  # a render is filed under the face's name
    for fn, e in (manifest or Manifest(d)).entries.items():
        if e.get("card") not in mine or e.get("back"):
            continue
        if e.get("theme") and e.get("theme") != "wizards":
            continue
        if not (d / fn).exists():
            continue
        out.append({**e, "file": fn, "path": str(d / fn), "mode": "styled" if e.get("styled") else "plain",
                    "pinned": fn == pin})
    out.sort(key=lambda r: r.get("rendered_at") or "", reverse=True)
    return out


def backs_of(directory, number, styled=False):
    """The renders of the back face of the card numbered `number`, newest first. A back face is
    rendered with `--faces` and carries the front's number, so the number is what pairs them."""
    d = Path(directory)
    out = [{**e, "file": fn, "path": str(d / fn), "mode": "styled" if e.get("styled") else "plain"}
           for fn, e in Manifest(d).entries.items()
           if e.get("back") and e.get("number") == number and bool(e.get("styled")) == bool(styled)
           and (d / fn).exists()]
    out.sort(key=lambda r: r.get("rendered_at") or "", reverse=True)
    return out


def want_hashes(st, card, art, entry=None):
    """The art hash each of plain / styled should render with now, for the stale check."""
    entry = entry if entry is not None else st.card(card)
    return {"plain": art.resolve(card, override=entry.art).hash,
            "styled": art.resolve(card, override=entry.art, style_hash=st.styled_hash(card, art=art)).hash}


def stale(entry, fhash, want=None):
    """Why this render is out of date, or None. `want` is want_hashes(); without it only the
    frame is checked. A pinned render is never stale."""
    if entry.get("pinned"):
        return None
    if entry.get("frame") != fhash:
        return "the frame changed"
    if want is not None and (entry.get("source") or {}).get("hash") != want.get(entry["mode"]):
        return "the art changed"
    return None


def chosen(renders, mode="plain"):
    """The render a card prints as in that mode -- its pin, else the newest -- or None."""
    of = [r for r in renders if r["mode"] == mode]
    return next((r for r in of if r["pinned"]), None) or (of[0] if of else None)


def state(directory, st, cards, art, name, *, mode="plain", manifest=None, fhash=None):
    """Everything about this card's renders in one call: (all, chosen, stale_reason). `cards` is a
    Cards; a name the card file does not know raises MintError. `manifest` and `fhash` are passed in
    when walking a whole set, so the file is read and the frame hashed once rather than per card."""
    entry = st.card({"name": name})
    card = cards.find(name, *st.lookup(name))
    fhash = fhash or frame_hash(st.css, frame.frame_css(st.frame))
    want = want_hashes(st, card, art, entry)
    every = for_card(directory, name, entry.render, manifest)
    for r in every:
        r["stale"] = stale(r, fhash, want)
    pick = chosen(every, mode)
    return every, pick, (pick or {}).get("stale")


def needing(directory, st, cards, art, names, *, mode="plain"):
    """The names whose chosen render is missing or stale -- what a print run or an export has to
    render before it can go ahead."""
    out = []
    m = Manifest(directory)                                   # one read for the whole walk
    fh = frame_hash(st.css, frame.frame_css(st.frame))
    for name in names:
        try:
            _, pick, why = state(directory, st, cards, art, name, mode=mode, manifest=m, fhash=fh)
        except MintError:
            continue  # the card file does not know it; the caller reports that on its own
        if not pick or why:
            out.append(name)
    return out

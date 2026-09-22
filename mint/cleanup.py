"""What could be thrown away, with what it weighs -- for the workbench's Cleanup page.

    from mint import cleanup
    report = cleanup.candidates(ws, keep_days=3)
    cleanup.remove(ws, ["a1b2c3d4e5f6", ...], keep_days=3)

`mint gc` answers the same question on the command line and deletes the lot;
this answers it as a list you pick from. Nothing here ever runs on its own and
nothing is selected for you: `candidates` only reads, and `remove` only takes
ids you hand it.

An id is a digest of the file it stands for, and `remove` re-runs `candidates`
and deletes only ids that are still candidates. So an id that has since become
the card's pinned render, or the recipe's variant, is refused rather than
obeyed -- the selection cannot go stale into a deletion.

The groups, in the order the page shows them:

    art not in use            variants no card picks, renders with or starts from
    art nothing refers to     a whole variant directory for a card no set has
    renders gone stale        the frame or the art moved on since
    superseded renders        a card keeps every render; these are not the one it prints
    proofs and theme sheets   the frame page's throwaways
    renders off the manifest  a PNG under out/ nothing recorded
    manifest entries          rows whose file is already gone (no space, just tidying)

Everything in use is excluded whatever its age: a pinned render, the render a
card prints as, the styled art, the recipe's variant, the base chain behind
either, and anything newer than `keep_days`.
"""
import datetime as dt
import hashlib
from dataclasses import dataclass, field
from pathlib import Path

from . import gc, renders, sets
from .art import Art
from .errors import MintError
from .manifest import Manifest

KEEP_DAYS = 3

# key -> (title, why it is safe to remove), in the order the page lists them
GROUPS = {
    "art": ("art not in use",
            "no card picks these, renders with them or starts a restyle from them; a restyle makes them again"),
    "art-unreferenced": ("art nothing refers to",
                         "every picture for a card no set file has any more"),
    "render-stale": ("renders gone stale",
                     "the frame or the art moved on since these were made, so they are not what the card prints now"),
    "render-superseded": ("renders a card no longer prints",
                          "a card keeps every render it has ever had; these are the ones it is not pinned to and "
                          "not the newest of their kind"),
    "render-proof": ("proofs and theme sheets",
                     "the frame page's throwaways, under out/<set>/proof and /themes; pressing the button makes them again"),
    "render-orphan": ("renders off the manifest",
                      "a PNG under out/<set> that no manifest records, so nothing knows what it was made from"),
    "manifest-row": ("manifest entries whose file is gone",
                     "rows pointing at files that are already deleted; no space, just tidying"),
}


@dataclass
class Item:
    """One thing that could go, and the handles `remove` needs to do it."""
    group: str
    what: str                      # what to call it on the page
    why: str                       # this item's own reason, when it has one
    bytes: int
    created: str = ""              # when it was made, ISO; "" when nothing recorded it
    set_code: str | None = None
    card: str | None = None
    files: list = field(default_factory=list)
    variant: object = None         # for an art variant: the Variant, deleted through Art
    directory: Path | None = None  # for a whole variant directory
    manifest: Manifest | None = None
    entry: str | None = None       # the manifest row to drop

    @property
    def id(self):
        """The file this stands for, digested. Deliberately not salted by the group: a file that two
        reasons could claim has one id, so `candidates` offers it once and a selection of it is
        unambiguous."""
        key = str(self.files[0]) if self.files else f"{self.manifest.path}|{self.entry}"
        return hashlib.sha1(key.encode()).hexdigest()[:12]

    def age_days(self, now=None):
        if not self.created:
            return None
        try:
            made = dt.datetime.fromisoformat(self.created)
        except ValueError:
            return None
        now = now or dt.datetime.now(dt.timezone.utc)
        if made.tzinfo is None:
            made = made.replace(tzinfo=dt.timezone.utc)
        return max(0, (now - made).days)

    def to_dict(self):
        return {"id": self.id, "group": self.group, "what": self.what, "why": self.why, "bytes": self.bytes,
                "created": self.created, "age_days": self.age_days(), "set": self.set_code, "card": self.card,
                "files": [str(p) for p in self.files]}


def size_of(paths):
    return sum(p.stat().st_size for p in paths if p.exists())


def mtime_of(path):
    try:
        return dt.datetime.fromtimestamp(path.stat().st_mtime, dt.timezone.utc).isoformat(timespec="seconds")
    except OSError:
        return ""


def _older(created, cutoff):
    """True when this was made before the cutoff. Something with no date is old enough: nothing
    recorded when it arrived, so it is not one of the last few days' work."""
    return not created or created < cutoff


def candidates(ws, keep_days=KEEP_DAYS, only=None):
    """Everything that could be removed, as Items. Reads only."""
    cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=keep_days)).isoformat()
    items, seen, errors = [], set(), []
    mans = {}

    def man(directory):
        """One Manifest per directory: two rows dropped from the same file have to be dropped from
        the same object, or the second save writes the first one's row back."""
        return mans.setdefault(Path(directory).resolve(), Manifest(directory))

    def add(item):
        if item.id in seen:       # a file is offered under one reason only, the first that claims it
            return
        seen.add(item.id)
        items.append(item)

    report = gc.collect(ws, only, keep_days)
    errors += report["errors"]

    for code, name, v in report["variants"]:
        files = [p for p in gc.files_of(v) if p.exists()]
        add(Item("art", f"{v.label}-{v.hash}", v.kind, size_of(files), v.created, code, name, files, variant=v))
    for d in report["unreferenced"]:
        files = [p for p in d.iterdir() if p.is_file()]
        add(Item("art-unreferenced", d.name, f"{len(files)} file(s)", size_of(files), mtime_of(d),
                 files=files, directory=d))

    # renders: stale first (it says more), then the ones a card simply no longer prints
    for code, m, fn, why in report["stale"]:
        p = m.path.parent / fn
        e = m.entries.get(fn, {})
        add(Item("render-stale", fn, why, size_of([p]), e.get("rendered_at", ""), code, e.get("card"), [p],
                 manifest=man(m.path.parent), entry=fn))

    for st in _sets(ws, only, errors):
        out_dir = ws.home / "out" / st.code.lower()
        if not out_dir.is_dir():
            continue
        m = man(out_dir)
        for name in st.names():
            pin = st.card({"name": name}).render
            every = renders.for_card(out_dir, name, pin)
            # what the card prints now, and the newest of each kind -- the one it would fall back to
            # if the pin were dropped. Offering that would make unpinning lose the card its render.
            keep = set()
            for mode in ("plain", "styled"):
                of = [r for r in every if r["mode"] == mode]
                if of:
                    keep.add(of[0]["file"])
                if (ch := renders.chosen(every, mode)):
                    keep.add(ch["file"])
            for r in every:
                if r["file"] in keep or r["pinned"] or not _older(r.get("rendered_at", ""), cutoff):
                    continue
                p = Path(r["path"])
                add(Item("render-superseded", r["file"], f"{r.get('design') or 'm15'} · {r['mode']}",
                         size_of([p]), r.get("rendered_at", ""), st.code, name, [p], manifest=m, entry=r["file"]))
        for sub in ("proof", "themes"):
            d = out_dir / sub
            if not d.is_dir():
                continue
            sm = man(d)
            for fn, e in sm.entries.items():
                p = d / fn
                if not p.exists() or not _older(e.get("rendered_at", ""), cutoff):
                    continue
                add(Item("render-proof", f"{sub}/{fn}", e.get("theme") or sub, size_of([p]),
                         e.get("rendered_at", ""), st.code, e.get("card"), [p], manifest=sm, entry=fn))

    for p in report["orphans"]:
        add(Item("render-orphan", p.name, "nothing recorded it", size_of([p]), mtime_of(p),
                 _code_of(ws, p), None, [p]))
    for code, m, fn in report["dropped"]:
        add(Item("manifest-row", fn, "its file is already gone", 0,
                 m.entries.get(fn, {}).get("rendered_at", ""), code, m.entries.get(fn, {}).get("card"),
                 manifest=man(m.path.parent), entry=fn))
    return {"items": items, "errors": errors, "keep_days": keep_days}


def _sets(ws, only, errors):
    for p in ws.set_files():
        try:
            st = sets.load(p)
        except MintError as e:
            errors.append(f"{p.name}: {e}")
            continue
        if only and st.code.lower() != only.lower():
            continue
        yield st


def _code_of(ws, path):
    try:
        return Path(path).relative_to(ws.home / "out").parts[0].upper()
    except ValueError:
        return None


def grouped(report):
    """The items as the page wants them: one block per group, with its own total."""
    out = []
    for key, (title, why) in GROUPS.items():
        mine = [i for i in report["items"] if i.group == key]
        if not mine:
            continue
        mine.sort(key=lambda i: (i.created or "", i.what))
        out.append({"key": key, "title": title, "why": why, "count": len(mine),
                    "bytes": sum(i.bytes for i in mine), "items": [i.to_dict() for i in mine]})
    return {"groups": out, "bytes": sum(i.bytes for i in report["items"]), "count": len(report["items"]),
            "keep_days": report["keep_days"], "errors": report["errors"]}


def remove(ws, ids, keep_days=KEEP_DAYS, only=None):
    """Delete the items with these ids, and only those. An id that is no longer a candidate -- it
    became the card's pin, or somebody else removed it -- is reported back, not guessed at."""
    wanted = set(ids)
    if not wanted:
        raise MintError("nothing selected")
    report = candidates(ws, keep_days, only)
    mine = [i for i in report["items"] if i.id in wanted]
    missed = sorted(wanted - {i.id for i in mine})
    art = Art(ws.art)
    freed, touched = 0, {}
    for item in mine:
        freed += item.bytes
        if item.variant is not None:
            art.delete(item.variant)
        elif item.directory is not None:
            for p in item.directory.iterdir():
                p.unlink()
            item.directory.rmdir()
        else:
            for p in item.files:
                if p.exists():
                    p.unlink()
        if item.manifest is not None and item.entry:
            item.manifest.entries.pop(item.entry, None)
            touched[id(item.manifest)] = item.manifest
    for m in touched.values():
        m.save()
    return {"removed": len(mine), "bytes": freed, "missed": missed}


def _fmt(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


def main(argv=None):
    """`mint cleanup` prints the same list the workbench shows, and removes nothing."""
    import argparse
    import sys

    from . import workspace
    ap = argparse.ArgumentParser(prog="mint cleanup", description=__doc__.split("\n\n")[0])
    ap.add_argument("--keep-days", type=int, default=KEEP_DAYS, help=f"anything newer stays (default {KEEP_DAYS})")
    ap.add_argument("--set", help="one set only")
    a = ap.parse_args(argv)
    try:
        g = grouped(candidates(workspace.default(), a.keep_days, a.set))
    except MintError as e:
        sys.exit(str(e))
    for e in g["errors"]:
        print(f"  skipped  {e}")
    for block in g["groups"]:
        print(f"\n{block['title']}: {block['count']}, {_fmt(block['bytes'])}")
        print(f"  {block['why']}")
        for i in block["items"]:
            where = " ".join(x for x in (i["set"], i["card"]) if x)
            age = f"{i['age_days']}d" if i["age_days"] is not None else "?"
            print(f"    {_fmt(i['bytes']):>9}  {age:>4}  {where}: {i['what']}")
    print(f"\n{g['count']} item(s), {_fmt(g['bytes'])} in all."
          + ("  Pick what goes on the workbench's Cleanup page, or `mint gc --delete` takes the lot."
             if g["count"] else "  Nothing to remove."))
    return 0


if __name__ == "__main__":
    main()

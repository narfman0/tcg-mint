"""Find cards in Scryfall's bulk file.

The bulk file is ~200 MB of JSON lines, one card (or printing) per line. A
SQLite index beside it -- name, set, collector number, illustration id, byte
offset -- is built on first use and rebuilt whenever the file changes, so a
lookup is a seek instead of a scan of the whole file.

`oracle_cards` holds one printing per card; `default_cards` (see `mint cards
--kind`) holds every printing, and then `printings()` lists them and `find()`
prefers one that is not a Universes Beyond crossover.
"""
import json
import os
import re
import sqlite3
from pathlib import Path

from .errors import CardNotFound, MintError

# Universes Beyond printings (Scryfall: security_stamp == "triangle") are not
# wanted as art, except these: Lord of the Rings fits Magic well enough.
UB_EXEMPT = {"ltr", "ltc"}


def front_face(card):
    """Double-faced cards (transform, modal_dfc) keep art, text, cost and type per
    face; present the front face's fields at the top level so the frame renders
    it as a normal card. The full 'A // B' name is kept as full_name."""
    faces = card.get("card_faces")
    if faces and "image_uris" not in card:
        card = {**card, **{k: v for k, v in faces[0].items() if k != "object"}, "full_name": card["name"]}
    return card


def faces(card):
    """Every face of a card as its own renderable record: [front] for a normal card,
    [front, back] for transform / modal DFCs. Each carries face_index and full_name."""
    fs = card.get("card_faces")
    if not fs or "image_uris" not in fs[0]:  # split / adventure faces share one image: one card
        return [dict(card, face_index=0)]
    out = []
    for i, f in enumerate(fs):
        out.append({**card, **{k: v for k, v in f.items() if k != "object"},
                    "full_name": card.get("full_name", card["name"]), "face_index": i})
    return out


def is_universes_beyond(card):
    return card.get("security_stamp") == "triangle" and card.get("set") not in UB_EXEMPT


# The default printing: the newest one that looks like a normal card. Every printing gets
# a penalty for each way it is not one; the lowest penalty wins, newest first among equals.
# With a per-printing card file (`mint cards --kind default_cards`) the newest printing of a
# staple is usually a Secret Lair, a promo or a showcase frame, and that is not what anyone
# means by "the card".
ODD_SET_TYPES = {"box": 25, "masterpiece": 25, "promo": 30, "spellbook": 20, "funny": 20, "memorabilia": 60,
                 "token": 60, "minigame": 60, "vanguard": 60, "planechase": 30, "archenemy": 30}
ODD_FRAME = {"showcase", "extendedart", "inverted", "etched", "shatteredglass", "textless", "borderless", "fullart"}


def TODAY():
    import datetime as dt
    return dt.date.today().isoformat()


def oddness(card):
    """(penalty, reasons) for a printing as the default; 0 is a plain black-bordered card."""
    why = []
    if card.get("digital"):
        why.append(("digital", 100))
    if card.get("lang", "en") != "en":
        why.append((card["lang"], 100))
    if card.get("oversized"):
        why.append(("oversized", 100))
    if not card.get("illustration_id"):
        why.append(("no art", 100))
    if (card.get("released_at") or "") > TODAY():
        why.append(("unreleased", 50))
    if is_universes_beyond(card):
        why.append(("Universes Beyond", 40))
    t = card.get("set_type")
    if t in ODD_SET_TYPES:
        why.append((t.replace("box", "Secret Lair / box set"), ODD_SET_TYPES[t]))
    if card.get("promo") and t != "promo":
        why.append(("promo", 30))
    if card.get("set") == "plst" or card.get("set", "").startswith("mb"):
        why.append(("The List / Mystery Booster", 15))
    if card.get("border_color") not in (None, "black"):
        why.append((card["border_color"] + " border", 10))
    odd = ODD_FRAME & set(card.get("frame_effects") or [])
    if odd:
        why.append((", ".join(sorted(odd)), 10))
    if card.get("full_art") and "Land" not in card.get("type_line", ""):
        why.append(("full art", 10))
    if card.get("textless"):
        why.append(("textless", 20))
    return sum(p for _, p in why), [w for w, _ in why]


def default_printing(cands):
    """The printing `find` uses without an explicit one: least odd, newest among those, and
    the lowest collector number within a set (the plain printing sits before its variants)."""
    def key(c):
        m = re.match(r"\d+", c.get("collector_number", ""))
        return (oddness(c)[0], c.get("released_at") or "", int(m.group()) if m else 10**6)  # released: newest first, below
    if not cands:
        return None
    best = min(oddness(c)[0] for c in cands)
    tied = [c for c in cands if oddness(c)[0] == best]
    newest = max(c.get("released_at") or "" for c in tied)
    return min((c for c in tied if (c.get("released_at") or "") == newest), key=key)


def warnings(card):
    """Things about this printing the user should hear about, as short strings."""
    out = []
    if is_universes_beyond(card):
        out.append(f"art source is a Universes Beyond printing ({card['set'].upper()})")
    return out


class Cards:
    def __init__(self, path):
        self.path = Path(path)
        self.index_path = self.path.with_name(self.path.name + ".idx")
        self._db = None

    # --- index ---------------------------------------------------------------
    def _signature(self):
        st = os.stat(self.path)
        return f"{st.st_size}:{int(st.st_mtime)}"

    def db(self):
        if self._db is None:
            if not self.path.exists():
                raise MintError(f"no card file at {self.path}; run `mint cards` or point MINT_CARDS at one")
            db = sqlite3.connect(self.index_path)
            db.execute("CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT)")
            row = db.execute("SELECT v FROM meta WHERE k = 'sig'").fetchone()
            if not row or row[0] != self._signature():
                self.build(db)
            self._db = db
        return self._db

    def build(self, db=None):
        """(Re)build the index from the card file. A few seconds for oracle_cards."""
        db = db or sqlite3.connect(self.index_path)
        db.executescript("""
            DROP TABLE IF EXISTS cards;
            CREATE TABLE cards (name TEXT, lname TEXT, lfull TEXT, set_code TEXT, number TEXT, illustration_id TEXT,
                                layout TEXT, stamp TEXT, released TEXT, offset INTEGER, length INTEGER);
            CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);
        """)
        rows = []
        with open(self.path, "rb") as f:
            offset = 0
            for line in f:
                n = len(line)
                if n > 1:
                    c = front_face(json.loads(line))
                    rows.append((c["name"], c["name"].lower(), c.get("full_name", c["name"]).lower(),
                                 c.get("set"), c.get("collector_number"),
                                 c.get("illustration_id"), c.get("layout"), c.get("security_stamp"),
                                 c.get("released_at"), offset, n))
                offset += n
        db.executemany("INSERT INTO cards VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows)
        db.execute("CREATE INDEX cards_lname ON cards(lname)")
        db.execute("CREATE INDEX cards_lfull ON cards(lfull)")
        db.execute("CREATE INDEX cards_illustration ON cards(illustration_id)")
        db.execute("INSERT OR REPLACE INTO meta VALUES ('sig', ?)", (self._signature(),))
        db.execute("INSERT OR REPLACE INTO meta VALUES ('count', ?)", (str(len(rows)),))
        db.commit()
        return len(rows)

    def _read(self, offset, length):
        with open(self.path, "rb") as f:
            f.seek(offset)
            return json.loads(f.read(length))

    # --- lookup --------------------------------------------------------------
    def printings(self, name):
        """Every record for this name (the full 'A // B' name or its front face),
        newest first. Art-series cards (same name, no rules text) are excluded."""
        want = name.lower()
        rows = self.db().execute(
            "SELECT offset, length FROM cards WHERE (lname = ? OR lfull = ?) "
            "AND (layout IS NULL OR layout != 'art_series') ORDER BY released DESC, set_code", (want, want)).fetchall()
        return [front_face(self._read(o, n)) for o, n in rows]

    def find(self, name, printing=None):
        """The card to render for this name. With several printings on file, the newest
        that looks like a normal card wins (default_printing); `printing` ("rvr:40")
        picks one explicitly."""
        cands = self.printings(name)
        if not cands:
            raise CardNotFound(f"not in {self.path.name}: {name}")
        if printing:
            code, _, num = printing.partition(":")
            for c in cands:
                if c["set"] == code.lower() and (not num or c["collector_number"] == num):
                    return c
            raise CardNotFound(f"{name}: no printing {printing!r} on file (have {', '.join(self.printing_ids(cands))})")
        return default_printing(cands)

    @staticmethod
    def printing_ids(cards):
        return [f"{c['set']}:{c['collector_number']}" for c in cards]

    def by_illustration(self, illustration_id):
        row = self.db().execute("SELECT offset, length FROM cards WHERE illustration_id = ?", (illustration_id,)).fetchone()
        return front_face(self._read(*row)) if row else None

    def count(self):
        row = self.db().execute("SELECT v FROM meta WHERE k = 'count'").fetchone()
        return int(row[0]) if row else 0

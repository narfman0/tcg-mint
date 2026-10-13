"""Find cards in Scryfall's bulk file.

The bulk file is ~200 MB of JSON lines, one card (or printing) per line. A
SQLite index beside it -- name, set, collector number, illustration id, byte
offset -- is built on first use and rebuilt whenever the file changes, so a
lookup is a seek instead of a scan of the whole file.

`oracle_cards` holds one printing per card; `default_cards` (see `mint cards
--kind`) holds every printing, and then `printings()` lists them and `find()`
prefers one that is not a Universes Beyond crossover (is_universes_beyond).
"""
import json
import os
import re
import sqlite3
from pathlib import Path

from .errors import CardNotFound, MintError
from .frame import printed_design

BUILD_WAIT = 600  # seconds a lookup waits on a rebuild in progress before "database is locked"

# Universes Beyond printings are not wanted as art -- no crossover is, Tolkien
# included: a set code here would be exempted, and nothing is.
#
# The test is `promo_types` containing "universesbeyond". The triangle security
# stamp is kept as a fallback but no longer carries the check on its own: Magic
# stopped stamping the crossovers once they became ordinary releases, so Marvel,
# Spider-Man, Avatar, TMNT, Star Trek and The Hobbit all print an *oval* stamp
# (or none) and used to score as plain black-bordered cards -- which is how the
# newest Sol Ring became a Marvel Super Heroes Commander printing. The promo type
# is a strict superset of the triangle in Scryfall's data: every triangle card
# carries it, and ~4.7k more do.
UB_EXEMPT = set()  # set codes to treat as ordinary Magic art despite the promo type


def front_face(card):
    """Double-faced cards (transform, modal_dfc) keep art, text, cost and type per
    face; present the front face's fields at the top level so the frame renders
    it as a normal card. The full 'A // B' name is kept as full_name."""
    faces = card.get("card_faces")
    if faces and "image_uris" not in card:
        card = {**card, **{k: v for k, v in faces[0].items() if k != "object"}, "full_name": card["name"]}
    return card


ADDS_RE = re.compile(r"Add ([^.\n]*)")
FACE_ONLY = {"power", "toughness", "loyalty", "defense", "flavor_text", "flavor_name", "color_indicator", "watermark",
             "printed_name", "printed_text", "printed_type_line"}


def made_mana(text):
    """The colours a face's own text makes ("{T}: Add {U}." -> ["U"]), in WUBRGC order: the card's
    produced_mana is the union of both faces, which paints a Pathway's blue front as a blue-red dual."""
    syms = {m for add in ADDS_RE.findall(text or "") for m in re.findall(r"\{([WUBRGC])\}", add)}
    return [c for c in "WUBRGC" if c in syms]


def faces(card):
    """Every face of a card as its own renderable record: [front] for a normal card,
    [front, back] for transform / modal DFCs. Each carries face_index and full_name, and the
    card-wide fields that are really one face's -- produced_mana, the legendary frame effect -- are
    rederived from the face, so a land's front is not tinted by its back's mana and a land whose
    back is a legend wears no crown."""
    fs = card.get("card_faces")
    if not fs or "image_uris" not in fs[0]:  # split / adventure faces share one image: one card
        return [dict(card, face_index=0)]
    # a record flattened by front_face carries the front's own fields at the top level; the keys a face only
    # has when it applies (a creature's P/T, a planeswalker's loyalty, flavour text, the colour indicator)
    # must not leak from the front into a back that has none
    base = {k: v for k, v in card.items() if k not in FACE_ONLY}
    out = []
    for i, f in enumerate(fs):
        face = {**base, **{k: v for k, v in f.items() if k != "object"},
                "full_name": card.get("full_name", card["name"]), "face_index": i}
        face["produced_mana"] = made_mana(face.get("oracle_text"))
        effects = [e for e in (card.get("frame_effects") or []) if e != "legendary"]
        if (face.get("type_line") or "").startswith("Legendary"):
            effects.append("legendary")
        face["frame_effects"] = effects
        out.append(face)
    return out


def is_universes_beyond(card):
    ub = ("universesbeyond" in (card.get("promo_types") or [])
          or card.get("security_stamp") == "triangle")
    return ub and card.get("set") not in UB_EXEMPT


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


# the frame effects each design's own printings carry, which are not odd for it ("inverted" marks nothing
# visible and rides along on the promos that print textless and borderless cards)
DESIGN_FRAME = {"extended": {"extendedart"}, "fullart": {"fullart", "inverted"}, "borderless": {"inverted"},
                "textless": {"textless", "fullart", "inverted"}}


def oddness(card, design=None):
    """(penalty, reasons) for a printing as the default; 0 is a plain black-bordered card. With a frame
    design (frame.DESIGNS), a printing of that design's own kind is not odd for the things that make it
    one -- its markers, its border, and the promo or box set it was printed in, which is the only place
    some of them exist -- so a card set to full art defaults to its newest full-art printing, and one set
    to textless to a textless promo; everything else still counts, and a printing of another kind is
    ranked behind."""
    mine = bool(design) and design != "m15" and printed_design(card) == design  # a printing of the design's own kind
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
        # a last resort, not merely odd: ranked behind every printing that is still a
        # normal Magic card (a Secret Lair, a promo, a showcase frame), so a crossover
        # wins only when it is the card's only printing
        why.append(("Universes Beyond", 90))
    t = card.get("set_type")
    if t in ODD_SET_TYPES and not mine:
        why.append((t.replace("box", "Secret Lair / box set"), ODD_SET_TYPES[t]))
    if card.get("promo") and t != "promo" and not mine:
        why.append(("promo", 30))
    if card.get("set") == "plst" or card.get("set", "").startswith("mb"):
        why.append(("The List / Mystery Booster", 15))
    border = card.get("border_color")
    plain_border = border == "borderless" and (mine or design in ("borderless", "fullart"))
    if border not in (None, "black") and not plain_border:
        why.append((border + " border", 10))
    odd = ODD_FRAME & set(card.get("frame_effects") or [])
    if mine:
        odd -= DESIGN_FRAME.get(design, set())
    if odd:
        why.append((", ".join(sorted(odd)), 10))
    if card.get("full_art") and "Land" not in card.get("type_line", "") and not mine and design != "fullart":
        why.append(("full art", 10))
    if not mine and design and design != "m15":  # the design's own printings come first
        why.append((f"not {design}", 5))
    if card.get("textless") and not mine:
        why.append(("textless", 20))
    return sum(p for _, p in why), [w for w, _ in why]


def default_printing(cands, design=None):
    """The printing `find` uses without an explicit one: least odd (for the frame design, if any),
    newest among those, and the lowest collector number within a set (the plain printing sits
    before its variants)."""
    def key(c):
        m = re.match(r"\d+", c.get("collector_number", ""))
        # released: newest first, below
        return (oddness(c, design)[0], c.get("released_at") or "", int(m.group()) if m else 10**6)
    if not cands:
        return None
    best = min(oddness(c, design)[0] for c in cands)
    tied = [c for c in cands if oddness(c, design)[0] == best]
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
        return f"v2:{st.st_size}:{int(st.st_mtime)}"  # v2: split and adventure cards indexed by their first face too

    def _stale(self, db):
        row = db.execute("SELECT v FROM meta WHERE k = 'sig'").fetchone()
        return not row or row[0] != self._signature()

    def _connect(self):
        # autocommit, so build() can hold one explicit transaction; the timeout is how long a
        # lookup waits for another thread's (or process's) rebuild of a default_cards file
        return sqlite3.connect(self.index_path, timeout=BUILD_WAIT, isolation_level=None)

    def db(self):
        if self._db is None:
            if not self.path.exists():
                raise MintError(f"no card file at {self.path}; run `mint cards` or point MINT_CARDS at one")
            db = self._connect()
            try:
                db.execute("CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT)")
                if self._stale(db):
                    self.build(db)
            except BaseException:
                db.close()
                raise
            self._db = db
        return self._db

    def build(self, db=None):
        """(Re)build the index from the card file. A few seconds for oracle_cards, a minute
        for default_cards. One builder at a time: the workbench opens a connection per
        request thread, and after a `mint cards` refresh several of them notice the stale
        index together -- the rest queue on the write lock and find it fresh when they get it."""
        db = db or self._connect()
        db.execute("BEGIN IMMEDIATE")
        try:
            if self._stale(db):  # still -- a thread ahead of us in the queue may have done it
                db.execute("DROP TABLE IF EXISTS cards")
                db.execute("""CREATE TABLE cards (name TEXT, lname TEXT, lfull TEXT, set_code TEXT, number TEXT,
                                                  illustration_id TEXT, layout TEXT, stamp TEXT, released TEXT,
                                                  offset INTEGER, length INTEGER)""")
                rows = self._rows()
                db.executemany("INSERT INTO cards VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows)
                db.execute("CREATE INDEX cards_lname ON cards(lname)")
                db.execute("CREATE INDEX cards_lfull ON cards(lfull)")
                db.execute("CREATE INDEX cards_illustration ON cards(illustration_id)")
                db.execute("INSERT OR REPLACE INTO meta VALUES ('sig', ?)", (self._signature(),))
                db.execute("INSERT OR REPLACE INTO meta VALUES ('count', ?)", (str(len(rows)),))
            count = int(db.execute("SELECT v FROM meta WHERE k = 'count'").fetchone()[0])
            db.execute("COMMIT")
        except BaseException:
            db.execute("ROLLBACK")
            raise
        return count

    def _rows(self):
        rows = []
        with open(self.path, "rb") as f:
            offset = 0
            for line in f:
                n = len(line)
                if n > 1:
                    c = front_face(json.loads(line))
                    # a split or adventure card keeps its 'A // B' name; its first face's name finds it too
                    first = (c.get("card_faces") or [{}])[0].get("name") or c["name"]
                    rows.append((c["name"], first.lower(), c.get("full_name", c["name"]).lower(),
                                 c.get("set"), c.get("collector_number"),
                                 c.get("illustration_id"), c.get("layout"), c.get("security_stamp"),
                                 c.get("released_at"), offset, n))
                offset += n
        return rows

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

    def find(self, name, printing=None, design=None):
        """The card to render for this name. With several printings on file, the newest
        that looks like a normal card wins (default_printing) -- or like the frame `design`
        asked for (sets.SetFile.lookup); `printing` ("rvr:40") picks one explicitly."""
        cands = self.printings(name)
        if not cands:
            raise CardNotFound(f"not in {self.path.name}: {name}")
        if printing:
            code, _, num = printing.partition(":")
            for c in cands:
                if c["set"] == code.lower() and (not num or c["collector_number"] == num):
                    return c
            raise CardNotFound(f"{name}: no printing {printing!r} on file (have {', '.join(self.printing_ids(cands))})")
        return default_printing(cands, design)

    @staticmethod
    def printing_ids(cards):
        return [f"{c['set']}:{c['collector_number']}" for c in cards]

    def by_illustration(self, illustration_id):
        row = self.db().execute("SELECT offset, length FROM cards WHERE illustration_id = ?", (illustration_id,)).fetchone()
        return front_face(self._read(*row)) if row else None

    def count(self):
        row = self.db().execute("SELECT v FROM meta WHERE k = 'count'").fetchone()
        return int(row[0]) if row else 0

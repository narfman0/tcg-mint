"""Orders: what goes to the printer in one batch, and the file that says so.

    {
      "name": "october",
      "note": "the three commander decks",
      "stock": "(S33) Superior Smooth",   what MakePlayingCards prints it on
      "dpi": 800, "mode": "styled",       the resolution, and which render of each card
      "foil": "holo", "foil_strength": 1, holographic fronts, and how hard they are treated
      "sets": [
        {"code": "SLV"},                                   the whole set, one of each
        {"code": "GSH", "cards": {"Plains": 0, "Sol Ring": 2}},
        {"code": "BLS1", "copies": 0, "cards": {"Cyclonic Rift": 1}}
      ]
    }

A set is the aggregate of cards; an order is a union of sets, and it holds only what it
*changes* about them. It never copies a card list -- a card added to a deck is in the order the
moment it is in the set, which is the whole point of naming the set rather than its contents.

Everything an order can say about a card is one number, **how many copies to print**:

    copies            the set's default, 1 unless the line says otherwise
    cards[name]       that card's own count, overriding the default
    0                 not printed -- how a card is taken out of the order
    "copies": 0       nothing from this set but the cards named -- how one card is taken out
                      of a big set without listing the other two hundred

Each set's cards print behind that set's own back (sets.Back), so a union comes back sortable;
export.py does the printing and back.py draws the backs.

The reason to union at all is the bracket -- MakePlayingCards bills an order at the next size up,
and three decks in one batch are billed once. `Order.bill` is that arithmetic: what each set
contributes, what the whole order costs, how much room is left before the next bracket, and how
many cards would have to go to fall back to the one below.
"""
import json
import os
import re
from dataclasses import dataclass, field, fields
from pathlib import Path

from .errors import SetError

MODES = ("plain", "styled")
SLUG = re.compile(r"[a-z0-9][a-z0-9-]*")


def slug(name):
    """An order's name as a file name: lower case, spaces and punctuation to dashes."""
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s or "order"


@dataclass
class SetEntry:
    """One set in an order: which, how many of each, and the exceptions."""
    code: str
    copies: int = 1                             # of each card in the set; 0 = only the cards named
    cards: dict = field(default_factory=dict)   # name -> count, overriding copies (0 = not printed)

    def count(self, name):
        """How many of this card the order prints: its own count, else the set's default."""
        n = self.cards.get(name)
        return self.copies if n is None else n

    def validate(self, where):
        if not isinstance(self.code, str) or not self.code:
            raise SetError(f"{where}: a set line needs a code")
        if not isinstance(self.copies, bool) and isinstance(self.copies, int) and 0 <= self.copies <= 99:
            pass
        else:
            raise SetError(f"{where}: copies must be a whole number from 0 to 99, not {self.copies!r}")
        for name, n in self.cards.items():
            if isinstance(n, bool) or not isinstance(n, int) or not 0 <= n <= 99:
                raise SetError(f"{where}: cards[{name!r}] must be a whole number from 0 to 99, not {n!r}")


@dataclass
class Order:
    name: str
    note: str | None = None
    stock: str | None = None          # None = export's default cardstock
    dpi: int | None = None            # None = export's default (MPC's maximum)
    mode: str = "plain"               # which render of each card: MODES
    foil: str | None = None           # a mint.foil profile name; None = no foil
    foil_strength: float = 1.0
    sets: list = field(default_factory=list)   # of SetEntry, in the order they take slots
    # not part of the file
    path: Path | None = field(default=None, compare=False)

    @property
    def slug(self):
        return self.path.stem if self.path else slug(self.name)

    def entry(self, code):
        return next((e for e in self.sets if e.code.upper() == code.upper()), None)

    def names(self, st):
        """The card names this order prints from `st`, in the set's own order, a name repeated
        once per copy. An empty list when the set is in the order but nothing of it prints."""
        e = self.entry(st.code)
        if e is None:
            return []
        return [n for n in st.names() for _ in range(e.count(n))]

    def parts(self, loaded):
        """[(SetFile, [name ...])] for export.export_union: the sets in the order they were added,
        each with the names it prints. `loaded` maps an upper-case code to its SetFile. A set the
        workspace no longer holds is skipped -- `bill` is what reports it."""
        out = []
        for e in self.sets:
            st = loaded.get(e.code.upper())
            if st is not None:
                out.append((st, self.names(st)))
        return out

    def bill(self, loaded):
        """What this order costs, and what is wrong with it. Returns

            {"rows": [{"code", "name", "cards", "copies", "missing", "gone"}],
             "total", "bracket", "headroom", "drop", "under", "problems"}

        `headroom` is how many more cards fit before the bracket goes up, `drop` how many would
        have to go to fall to the one below, and `under` that lower bracket. `missing` names cards
        the line counts that the set does not have any more -- a deck edited out from under the
        order -- and `gone` marks a set the workspace has lost."""
        from .export import BRACKETS, bracket
        rows, problems = [], []
        for e in self.sets:
            st = loaded.get(e.code.upper())
            if st is None:
                rows.append({"code": e.code, "name": None, "cards": 0, "copies": 0, "missing": [], "gone": True})
                problems.append(f"{e.code}: no such set in the workspace any more")
                continue
            names = self.names(st)
            missing = [n for n in e.cards if n not in st.cards]
            if missing:
                problems.append(f"{e.code}: {', '.join(missing)} -- counted by the order, not in the set any more")
            rows.append({"code": st.code, "name": st.name, "cards": len(names),
                         "copies": len({n for n in names}), "missing": missing, "gone": False,
                         "back": bool(st.back)})
        total = sum(r["cards"] for r in rows)
        b = bracket(total)
        under = max([x for x in BRACKETS if x < b], default=None)
        return {"rows": rows, "total": total, "bracket": b, "headroom": b - total,
                "drop": None if under is None else max(0, total - under), "under": under,
                "problems": problems}

    # --- editing -----------------------------------------------------------
    def add_set(self, code, copies=1):
        """Put a set in the order, or leave it where it is if it is already in."""
        e = self.entry(code)
        if e:
            e.copies = copies
            return e
        e = SetEntry(code=code.upper(), copies=copies)
        self.sets.append(e)
        return e

    def drop_set(self, code):
        e = self.entry(code)
        if e is None:
            raise SetError(f"{code} is not in this order")
        self.sets.remove(e)

    def set_count(self, code, name, n):
        """Print `n` of this card. `n` back at the set's default drops the exception rather than
        writing it down, so the file keeps saying only what it changes."""
        e = self.entry(code)
        if e is None:
            raise SetError(f"{code} is not in this order")
        if n == e.copies:
            e.cards.pop(name, None)
        else:
            e.cards[name] = n
        return e

    # --- (de)serialisation --------------------------------------------------
    def to_dict(self):
        d = {"name": self.name}
        for k in ("note", "stock", "dpi", "foil"):
            if getattr(self, k) is not None:
                d[k] = getattr(self, k)
        if self.mode != "plain":
            d["mode"] = self.mode
        if self.foil and self.foil_strength != 1.0:
            d["foil_strength"] = self.foil_strength
        d["sets"] = [{k: v for k, v in (("code", e.code), ("copies", e.copies), ("cards", e.cards))
                      if k == "code" or (k == "copies" and v != 1) or (k == "cards" and v)}
                     for e in self.sets]
        return d


def _build(cls, d, where):
    if not isinstance(d, dict):
        raise SetError(f"{where}: expected an object")
    known = {f.name for f in fields(cls) if f.name != "path"}
    unknown = set(d) - known
    if unknown:
        raise SetError(f"{where}: unknown key(s) {', '.join(sorted(unknown))}; known: {', '.join(sorted(known))}")
    try:
        return cls(**d)
    except TypeError as e:
        raise SetError(f"{where}: {e}") from None


def from_dict(d, where="order"):
    if not isinstance(d, dict) or not d.get("name"):
        raise SetError(f"{where}: an order needs a name")
    d = dict(d)
    lines = d.pop("sets", [])
    o = _build(Order, d, where)
    if o.mode not in MODES:
        raise SetError(f"{where}: mode must be one of {', '.join(MODES)}, not {o.mode!r}")
    if o.dpi is not None and not (isinstance(o.dpi, int) and not isinstance(o.dpi, bool) and o.dpi > 0):
        raise SetError(f"{where}: dpi must be a positive whole number, not {o.dpi!r}")
    if not isinstance(lines, list):
        raise SetError(f"{where}: sets must be a list of set lines")
    o.sets = [_build(SetEntry, e or {}, f"{where}: sets[{i}]") for i, e in enumerate(lines)]
    seen = set()
    for i, e in enumerate(o.sets):
        e.code = e.code.upper() if isinstance(e.code, str) else e.code
        e.validate(f"{where}: sets[{i}]")
        if e.code in seen:
            raise SetError(f"{where}: {e.code} is in the order twice; one line per set")
        seen.add(e.code)
    return o


def load(path):
    path = Path(path)
    try:
        d = json.loads(path.read_text())
    except FileNotFoundError:
        raise SetError(f"no order file {path}") from None
    except json.JSONDecodeError as e:
        raise SetError(f"{path}: not valid JSON ({e})") from None
    o = from_dict(d, str(path))
    o.path = path
    return o


def save(path, o):
    path = Path(path)
    os.makedirs(path.parent, exist_ok=True)
    tmp = path.with_suffix(".json.part")
    tmp.write_text(json.dumps(o.to_dict() if isinstance(o, Order) else o, indent=2, ensure_ascii=False) + "\n")
    os.replace(tmp, path)
    if isinstance(o, Order):
        o.path = path


def find(ws, name):
    """An order by name or slug, however it was typed."""
    p = Path(name)
    if p.suffix == ".json" and p.is_file():
        return load(p)
    fn = ws.orders / f"{slug(name)}.json"
    if not fn.is_file():
        raise SetError(f"no order {name!r}: `mint order` lists them")
    return load(fn)


def every(ws):
    """Every order in the workspace, by file name. A file that will not parse comes back as an
    error row rather than stopping the list."""
    out = []
    for fn in sorted(ws.orders.glob("*.json")):
        try:
            out.append(load(fn))
        except SetError as e:
            out.append(str(e))
    return out


def by_code(ws):
    """{CODE: SetFile} for every set in the workspace. A set file is not named after its code --
    sets/bls1.json holds BLS -- and two files can even carry the same code, so this reads them and
    indexes what they say, first file wins, the way the workbench resolves a code."""
    from . import sets as sets_mod
    out = {}
    for fn in ws.set_files():
        try:
            st = sets_mod.load(fn)
        except SetError:
            continue
        out.setdefault(st.code.upper(), st)
    return out


def loaded_sets(ws, o):
    """{CODE: SetFile} for the sets this order names, skipping any the workspace has lost."""
    every = by_code(ws)
    return {e.code.upper(): every[e.code.upper()] for e in o.sets if e.code.upper() in every}

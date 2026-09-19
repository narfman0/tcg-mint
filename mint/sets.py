"""Set files: the JSON that says what a set is, and the schema behind it.

    {
      "code": "BLS1", "name": "...", "size": 18,
      "art_filter": "saturate(1.4)",       CSS filter for --styled when no restyle exists
      "style": {...},                      the restyle recipe (Style below; restyle.py explains the knobs)
      "cards": {
        "Card Name": {"number": 1, "flavor": "...", "art": "path.png", "art_filter": "...",
                      "subject": "what the picture is of", "printing": "rvr:40",
                      "base": "<variant hash>", "seed": 123}
      }
    }

A .css file with the same stem (sets/bls1.css) is injected after the frame's
own rules, for the set's identity. Unknown keys are errors -- a typo in a
recipe should never pass silently -- and `mint check` reports them.

The *effective recipe* for a card (`SetFile.recipe`) is the style with the
card's subject ahead of the prompt, its own seed, and the image it starts
from; its hash names the restyle output (see art.py), so changing any knob
gives a new variant instead of overwriting the old one.
"""
import dataclasses
import hashlib
import json
import os
import zlib
from dataclasses import dataclass, field, fields
from pathlib import Path

from .errors import SetError

CONTROLS = ("canny", "lineart", "depth")
SEED_RULES = ("stable", "position")


@dataclass
class Style:
    name: str
    prompt: str
    negative: str = "blurry, low quality, text, watermark, signature, frame, border, deformed"
    control: str = "canny"
    control_strength: float = 0.8
    control_end: float = 0.9
    denoise: float = 0.85
    steps: int = 28
    cfg: float = 6.0
    seed: int = 7
    # stable: each card's seed comes from the set seed and its illustration id, so
    # adding a card never changes another's. position: the pre-A2 rule, seed*1000+index.
    seed_rule: str = "stable"
    sampler: str = "dpmpp_2m"
    scheduler: str = "karras"
    checkpoint: str = "juggernautXL_v9.safetensors"
    controlnet: str = "controlnet-union-sdxl-promax.safetensors"
    upscaler: str = "4x-UltraSharp.pth"
    loras: list = field(default_factory=list)  # [{"name": "x.safetensors", "strength": 0.7}]
    width: int = 1248
    height: int = 912
    grayscale_source: bool = False
    # keys the file spelled out, so saving keeps them even at their default value
    explicit: set = field(default_factory=set, compare=False, repr=False)

    def validate(self, where):
        if self.control not in CONTROLS:
            raise SetError(f"{where}: control must be one of {', '.join(CONTROLS)}, not {self.control!r}")
        if self.seed_rule not in SEED_RULES:
            raise SetError(f"{where}: seed_rule must be one of {', '.join(SEED_RULES)}")
        for k in ("denoise", "control_strength", "control_end"):
            v = getattr(self, k)
            if not 0 <= v <= 1:
                raise SetError(f"{where}: {k} must be between 0 and 1, not {v}")
        for lora in self.loras:
            if not isinstance(lora, dict) or "name" not in lora:
                raise SetError(f"{where}: each lora needs a name")


@dataclass
class CardEntry:
    number: int | None = None
    flavor: str | None = None        # replaces the printed flavor text
    art: str | None = None           # your own image instead of Scryfall's
    art_filter: str | None = None    # per-card CSS filter for --styled
    subject: str | None = None       # what the picture is of; prepended to the style prompt
    printing: str | None = None      # "set:number" to render a specific printing
    base: str | None = None          # the image a restyle starts from: a variant hash, else the crop
    seed: int | None = None          # this card's seed, instead of the derived one


@dataclass
class SetFile:
    code: str
    name: str = ""
    size: int | None = None
    note: str | None = None
    art_filter: str | None = None
    style: Style | None = None
    cards: dict = field(default_factory=dict)  # name -> CardEntry, in collector order
    # not part of the file
    path: Path | None = field(default=None, compare=False)
    css: str = field(default="", compare=False)

    # --- lookups ------------------------------------------------------------
    def card(self, record):
        """The entry for a Scryfall record (or {"name": ...}), by face name or full 'A // B' name."""
        return self.cards.get(record["name"]) or self.cards.get(record.get("full_name", "")) or CardEntry()

    def names(self):
        return list(self.cards)

    def position(self, name):
        return list(self.cards).index(name) if name in self.cards else 0

    def card_seed(self, name, illustration_id, style=None):
        """This card's seed: pinned in its entry, else derived from the style's seed by its rule."""
        style = style or self.style
        entry = self.cards.get(name) or CardEntry()
        if entry.seed is not None:
            return entry.seed
        if style.seed_rule == "position":
            return style.seed * 1000 + self.position(name)
        return style.seed * 1000 + zlib.crc32(illustration_id.encode()) % 1000

    def recipe(self, record, style=None):
        """The effective restyle recipe for one card, as a plain dict, or None without a style."""
        style = style or self.style
        if style is None:
            return None
        entry = self.card(record)
        r = {k: v for k, v in dataclasses.asdict(style).items() if k not in ("name", "seed_rule", "explicit")}
        if entry.subject:
            r["prompt"] = f"{entry.subject}, {r['prompt']}"
        r["seed"] = self.card_seed(record["name"], record.get("illustration_id", ""), style)
        r["base"] = entry.base or "crop"
        return r

    def promote(self, recipe, record):
        """The Style a variant's recipe implies for the whole set: the set's style with the
        variant's knobs, the card's subject prefix removed from the prompt, and no per-card
        seed or base. Rendering with this style makes that variant the card's current one
        (its seed is re-derived; if the variant's seed was pinned, pin it in the entry too)."""
        entry = self.card(record)
        knobs = {k: v for k, v in recipe.items() if k in {f.name for f in fields(Style)} and k not in ("name", "seed")}
        if entry.subject and knobs.get("prompt", "").startswith(entry.subject + ", "):
            knobs["prompt"] = knobs["prompt"][len(entry.subject) + 2:]
        base = self.style or Style(name="style", prompt="")
        new = dataclasses.replace(base, **knobs)
        new.explicit = set(base.explicit) | set(knobs)
        return new

    # --- (de)serialisation --------------------------------------------------
    def to_dict(self):
        d = {"code": self.code, "name": self.name}
        for k in ("size", "note", "art_filter"):
            if getattr(self, k) is not None:
                d[k] = getattr(self, k)
        if self.style:
            d["style"] = _slim(dataclasses.asdict(self.style), Style, self.style.explicit)
        d["cards"] = {n: {k: v for k, v in dataclasses.asdict(e).items() if v is not None} for n, e in self.cards.items()}
        return d


def recipe_hash(recipe):
    """Eight hex characters naming a recipe: same knobs, same base, same hash.
    Numbers are canonicalised (6 and 6.0 are the same knob) so the hash does not
    depend on how a set file happened to spell a value."""
    canon = json.dumps(_canon(recipe), sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(canon.encode()).hexdigest()[:8]


def _canon(v):
    if isinstance(v, bool):
        return v
    if isinstance(v, int | float):
        return float(v)
    if isinstance(v, dict):
        return {k: _canon(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_canon(x) for x in v]
    return v


def _slim(d, cls, keep=()):
    """Drop fields that still hold their default and were not spelled out, so the file stays short."""
    defaults = {f.name: (f.default_factory() if f.default_factory is not dataclasses.MISSING else f.default)
                for f in fields(cls)}
    return {k: v for k, v in d.items() if k != "explicit" and (k in ("name", "prompt") or k in keep or defaults.get(k) != v)}


def _build(cls, d, where):
    if not isinstance(d, dict):
        raise SetError(f"{where}: expected an object")
    known = {f.name for f in fields(cls) if f.name not in ("path", "css", "explicit")}
    unknown = set(d) - known
    if unknown:
        raise SetError(f"{where}: unknown key(s) {', '.join(sorted(unknown))}; known: {', '.join(sorted(known))}")
    try:
        obj = cls(**d)
    except TypeError as e:
        raise SetError(f"{where}: {e}") from None
    for f in fields(cls):
        v = getattr(obj, f.name)
        t = _base_type(f.type)
        want = {"int": int, "float": (int, float), "str": str, "bool": bool, "list": list, "dict": dict}.get(t)
        if v is not None and want and (not isinstance(v, want) or (t != "bool" and isinstance(v, bool))):
            raise SetError(f"{where}: {f.name} should be {t}, not {type(v).__name__}")
    return obj


def _base_type(t):
    """'int' for int, `int | None` or the string 'int | None'."""
    if isinstance(t, str):
        return t.replace(" | None", "").strip()
    args = getattr(t, "__args__", None)
    if args:
        t = next((x for x in args if x is not type(None)), t)
    return getattr(t, "__name__", str(t))


def from_dict(d, where="set"):
    if not isinstance(d, dict) or "code" not in d:
        raise SetError(f"{where}: a set needs a code")
    d = dict(d)
    style = d.pop("style", None)
    cards = d.pop("cards", {})
    st = _build(SetFile, d, where)
    if style is not None:
        st.style = _build(Style, style, f"{where}: style")
        st.style.explicit = set(style)
        st.style.validate(f"{where}: style")
    if not isinstance(cards, dict):
        raise SetError(f"{where}: cards must be an object of name -> entry")
    st.cards = {n: _build(CardEntry, e or {}, f"{where}: cards[{n!r}]") for n, e in cards.items()}
    return st


def load(path):
    """The set file plus its optional sibling .css."""
    path = Path(path)
    try:
        d = json.loads(path.read_text())
    except FileNotFoundError:
        raise SetError(f"no set file {path}") from None
    except json.JSONDecodeError as e:
        raise SetError(f"{path}: not valid JSON ({e})") from None
    st = from_dict(d, str(path))
    st.path = path
    css_fn = path.with_suffix(".css")
    st.css = css_fn.read_text() if css_fn.exists() else ""
    return st


def save(path, st):
    path = Path(path)
    os.makedirs(path.parent, exist_ok=True)
    tmp = path.with_suffix(".json.part")
    d = st.to_dict() if isinstance(st, SetFile) else st
    tmp.write_text(json.dumps(d, indent=2, ensure_ascii=False) + "\n")
    os.replace(tmp, path)
    if isinstance(st, SetFile):
        st.path = path

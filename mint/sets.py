"""Set files: the JSON that says what a set is, and the schema behind it.

    {
      "code": "BLS1", "name": "...", "size": 18,
      "art_filter": "saturate(1.4)",       CSS filter for --styled when no restyle exists
      "style": {...},                      the restyle recipe (Style below; restyle.py explains the knobs)
      "base": "spore",                     what every restyle starts from: a restyle label (that card's newest
                                           variant with it) or a variant hash; default the crop
      "cards": {
        "Card Name": {"number": 1, "flavor": "...", "art": "path.png", "art_filter": "...",
                      "subject": "what the picture is of", "printing": "rvr:40",
                      "base": "<variant hash>", "pose": "<variant hash>", "seed": 123,
                      "pick": "<variant hash>"}
      }
    }

A .css file with the same stem (sets/bls1.css) is injected after the frame's
own rules, for the set's identity. Unknown keys are errors -- a typo in a
recipe should never pass silently -- and `mint check` reports them.

The *effective recipe* for a card (`SetFile.recipe`) is the style with the
card's subject ahead of the prompt, its own seed, and the image it starts
from; its hash names the restyle output (see art.py), so changing any knob
gives a new variant instead of overwriting the old one. A base given as a
label ("spore") is resolved to that card's newest such variant when the art
cache is passed in, so the hash follows the actual input image.

The card's *styled art* (`SetFile.styled_hash`) is the variant its `pick`
names, else the one the effective recipe hashes to. A pick is how a take from
a random seed, or a restyle in another look, becomes the card's art without
rewriting the recipe to match it.
"""
import dataclasses
import hashlib
import json
import os
import re
import zlib
from dataclasses import dataclass, field, fields
from pathlib import Path

from .errors import SetError

CONTROLS = ("canny", "lineart", "depth", "openpose")
SEED_RULES = ("stable", "position")
# what a restyle keeps of the picture it starts from (restyle.py) -- three modes, not a scale:
#   restyle: the base's pixels and structure, redrawn in the style
#   repose:  a fresh picture in the pose of an image (the card's `pose`, else its base): an OpenPose
#            skeleton is all that is held, so a different pose image moves the joints
#   new:     a fresh picture from the prompt alone -- the subject line is all that links it to the card
#   inspire: a fresh picture with the base as an IP-Adapter reference: its look, palette and character
#            carry over, the words decide the pose, action and scene
REMIX = ("restyle", "repose", "new", "inspire")
INSPIRE_TYPES = ("standard", "prompt first", "style")  # the IP-Adapter weight types, in plain words


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
    # a second sampling pass over the first result at refine_scale x the size, with this
    # denoise (0.3-0.5 adds detail without changing the picture); 0 = off
    refine: float = 0.0
    refine_scale: float = 1.5
    # after the picture is made, move its colours back to the base's by this much (0-1; color.py):
    # a faithful restyle keeps the drawing but lets the palette drift, and this brings it back.
    # No-op in `new` mode, which has no base. 0 = off, and off keeps out of the recipe hash
    color_match: float = 0.0
    # 1 = the checkpoint's own CLIP; 2 = CLIP skip 2, which Pony-family checkpoints are trained for
    clip_skip: int = 1
    remix: str = "restyle"  # REMIX above; a card entry can override it
    # repose only: how hard, and for what fraction of the steps, the control holds the base's
    # layout. Composition is settled in the first third of the sampling, so the control has to
    # let go early and lightly or the pose is pinned exactly as in restyle. Starting points; tune
    # in the lab. Ignored (and kept out of the recipe) in the other modes.
    repose_strength: float = 0.5
    repose_end: float = 0.3
    # inspire only: how much the reference image weighs against the words, for what fraction of
    # the steps, and how -- standard: all of it; prompt first: the words settle the composition
    # before the image comes in; style: the image's look without its layout. Base-SDXL checkpoints
    # (Juggernaut) take 0.6-0.8; Pony burns to flat neon above ~0.5, so 0.35-0.5 there
    inspire_weight: float = 0.5
    inspire_end: float = 0.8
    inspire_type: str = "standard"
    # keys the file spelled out, so saving keeps them even at their default value
    explicit: set = field(default_factory=set, compare=False, repr=False)

    def validate(self, where):
        if self.control not in CONTROLS:
            raise SetError(f"{where}: control must be one of {', '.join(CONTROLS)}, not {self.control!r}")
        if self.seed_rule not in SEED_RULES:
            raise SetError(f"{where}: seed_rule must be one of {', '.join(SEED_RULES)}")
        if self.inspire_type not in INSPIRE_TYPES:
            raise SetError(f"{where}: inspire_type must be one of {', '.join(INSPIRE_TYPES)}, not {self.inspire_type!r}")
        if not 0 <= self.inspire_weight <= 2:
            raise SetError(f"{where}: inspire_weight must be 0-2")
        for k in ("denoise", "control_strength", "control_end", "repose_strength", "repose_end", "inspire_end"):
            v = getattr(self, k)
            if not 0 <= v <= 1:
                raise SetError(f"{where}: {k} must be between 0 and 1, not {v}")
        if not 0 <= self.refine <= 1:
            raise SetError(f"{where}: refine must be between 0 and 1, not {self.refine}")
        if not 1 <= self.refine_scale <= 3:
            raise SetError(f"{where}: refine_scale must be between 1 and 3, not {self.refine_scale}")
        if self.remix not in REMIX:
            raise SetError(f"{where}: remix must be one of {', '.join(REMIX)}, not {self.remix!r}")
        if not 1 <= self.clip_skip <= 12:
            raise SetError(f"{where}: clip_skip must be between 1 and 12, not {self.clip_skip}")
        for lora in self.loras:
            if not isinstance(lora, dict) or "name" not in lora:
                raise SetError(f"{where}: each lora needs a name")


@dataclass
class Frame:
    """The frame's dressing: each knob a strength 0-1 (0 = off), reaching template.html as a CSS
    custom property of the same name (--art-bevel ...), so a set's css can still override any."""
    watermark: float = 0.0     # the set symbol, faint, behind the rules text
    art_bevel: float = 1.0     # a dark line and a light pinline around the art window
    box_grain: float = 1.0     # linen grain over the bars and the text box (1 = the text box's old look)
    foil_stamp: float = 1.0    # the holofoil oval under the text box, on rares and mythics
    rarity_tint: float = 0.0   # the bars tinted with the rarity's colour

    def validate(self, where="frame"):
        for f in fields(self):
            v = getattr(self, f.name)
            if not 0 <= v <= 1:
                raise SetError(f"{where}: {f.name} should be between 0 and 1, not {v!r}")


@dataclass
class CardEntry:
    number: int | None = None
    flavor: str | None = None        # replaces the printed flavor text
    art: str | None = None           # your own image instead of Scryfall's
    art_filter: str | None = None    # per-card CSS filter for --styled
    subject: str | None = None       # what the picture is of; prepended to the style prompt
    printing: str | None = None      # "set:number" to render a specific printing
    base: str | None = None          # the image a restyle starts from: a variant hash or label, else the set's
    pose: str | None = None          # repose: the image whose pose to take: a hash, label, "crop" or a file path; else the base
    seed: int | None = None          # this card's seed, instead of the derived one
    remix: str | None = None         # this card's remix mode (REMIX), instead of the style's
    pick: str | None = None          # the variant hash --styled renders use, instead of the recipe's


@dataclass
class SetFile:
    code: str
    name: str = ""
    size: int | None = None
    note: str | None = None
    art_filter: str | None = None
    style: Style | None = None
    frame: Frame | None = None                 # the frame's dressing; None = the defaults
    base: str | None = None                    # every card's restyle base unless its entry says: hash or label
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

    def recipe(self, record, style=None, art=None, seed=None, remix=None):
        """The effective restyle recipe for one card, as a plain dict, or None without a style.
        With the art cache, a base named by label becomes that card's newest variant's hash.
        `seed` overrides for a one-off run (an unpinned "generate" rolls one) without touching the
        file, and `remix` likewise names the mode for this run alone (a `new` scene from a
        describer-written subject, whatever the style and the entry say)."""
        style = style or self.style
        if style is None:
            return None
        entry = self.card(record)
        r = {k: v for k, v in dataclasses.asdict(style).items() if k not in ("name", "seed_rule", "explicit")}
        # no-op knobs stay out of the hash, so older variants keep their names
        if r["clip_skip"] == 1:
            del r["clip_skip"]
        if not r["refine"]:
            del r["refine"], r["refine_scale"]
        if not r.get("color_match"):
            del r["color_match"]
        remix = remix or entry.remix or style.remix
        if remix not in REMIX:
            raise SetError(f"{record['name']}: remix must be one of {', '.join(REMIX)}, not {remix!r}")
        if remix == "restyle":
            del r["remix"]
        else:
            r["remix"] = remix
        if remix != "repose":  # the repose knobs only matter there; other modes' hashes stay
            del r["repose_strength"], r["repose_end"]
        if remix != "inspire":  # likewise the inspire knobs
            del r["inspire_weight"], r["inspire_end"], r["inspire_type"]
        else:  # and inspire runs no ControlNet and no img2img, so those knobs are not in its name
            for k in ("control", "control_strength", "control_end", "controlnet", "denoise"):
                del r[k]
        # a new picture has nothing but words to tie it to the card: the subject, else the card itself
        # (inspire has the reference image too, but the words still set the scene)
        fallback = f"{record['name']}, {record.get('type_line', '')}".rstrip(", ")  # a fresh picture's only thread to the card
        subject = entry.subject or (fallback if remix in ("new", "inspire") else None)
        if subject:
            r["prompt"] = f"{subject}, {r['prompt']}"
        r["seed"] = seed if seed is not None else self.card_seed(record["name"], record.get("illustration_id", ""), style)
        base = entry.base or self.base or "crop"
        if remix == "repose":  # the one image read is the pose source, and only its skeleton
            base = entry.pose or base
            r["control"] = "openpose"
        if art is not None and is_label(base):
            v = art.latest(record, base)
            base = v.hash if v else base
        r["base"] = "none" if remix == "new" else base  # `new` reads no image, so none names its variant
        return r

    def styled_hash(self, record, art=None):
        """The variant hash the card's styled art comes from: its pick, else the effective
        recipe's hash, else None without a style."""
        pick = self.card(record).pick
        if pick:
            return pick
        return recipe_hash(self.recipe(record, art=art)) if self.style else None

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
        for k in ("size", "note", "art_filter", "base"):
            if getattr(self, k) is not None:
                d[k] = getattr(self, k)
        if self.style:
            d["style"] = _slim(dataclasses.asdict(self.style), Style, self.style.explicit)
        if self.frame and _slim(dataclasses.asdict(self.frame), Frame):
            d["frame"] = _slim(dataclasses.asdict(self.frame), Frame)
        d["cards"] = {n: {k: v for k, v in dataclasses.asdict(e).items() if v is not None} for n, e in self.cards.items()}
        return d


HASH_RE = re.compile(r"^[0-9a-f]{8}$")


def is_label(base):
    """A base that names a restyle label rather than the crop or a variant hash."""
    return bool(base) and base != "crop" and not re.fullmatch(r"[0-9a-f]{8}", base)


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
    frame = d.pop("frame", None)
    cards = d.pop("cards", {})
    st = _build(SetFile, d, where)
    if frame is not None:
        st.frame = _build(Frame, frame, f"{where}: frame")
        st.frame.validate(f"{where}: frame")
    if style is not None:
        st.style = _build(Style, style, f"{where}: style")
        st.style.explicit = set(style)
        st.style.validate(f"{where}: style")
    if not isinstance(cards, dict):
        raise SetError(f"{where}: cards must be an object of name -> entry")
    st.cards = {n: _build(CardEntry, e or {}, f"{where}: cards[{n!r}]") for n, e in cards.items()}
    for n, e in st.cards.items():
        if e.pick is not None and not re.fullmatch(r"[0-9a-f]{8}", e.pick):
            raise SetError(f"{where}: cards[{n!r}]: pick should be a variant hash (8 hex characters), not {e.pick!r}")
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

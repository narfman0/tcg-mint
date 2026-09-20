"""Write a card's subject line from its picture and its text, for a `new` scene.

    mint describe --set sets/satoru.json [--force] [--generate] ["Card Name" ...]

A `new` restyle draws from the prompt alone, and the card's `subject` line is
its only thread back to the card (sets.py). Writing one by hand for every
card of a set is the slow part, so this does it: a vision model reads the
card's base image -- the crop, or whatever the card's restyles start from --
together with the card's name, type line and rules text, describes what the
picture shows, and writes a subject line from the three: who or what is in
it (as the picture draws them), what they are doing (as the card says), and
where. The subject goes into the set file, where it is committed and can be
edited like any hand-written one; the description sits beside the image in
the art cache (art/<id>/described.json) so the card page can show where the
line came from.

The subject carries content only -- no medium, palette or artist words --
because the style prompt supplies those and a content noun in the wrong
place becomes every subject-less card's picture.

Two describers, picked in mint.toml (`describer`), both plain HTTP:

    claude   the Anthropic Messages API; ANTHROPIC_API_KEY in the environment,
             `describe_model` (default claude-sonnet-5). The default.
    ollama   a local Ollama with a vision model (`describe_model`, e.g.
             qwen2.5vl or llava) at `ollama_url` (default http://127.0.0.1:11434).

`--generate` runs the `new` flow on each card right after, in the set's
style: the same restyle as the card page's generate button with the mode set
to new, so the variant lands beside the others and `keep` or the recipe make
it the card's art. Cards that already have a subject are left alone unless
`--force` says otherwise: a hand-written line is not overwritten by a batch.
"""
import argparse
import base64
import json
import os
import re
import sys
import urllib.error
import urllib.request

from . import sets, workspace
from .art import Art
from .cards import Cards
from .errors import MintError

DESCRIBERS = ("claude", "ollama")
DEFAULT_MODEL = {"claude": "claude-sonnet-5", "ollama": "qwen2.5vl"}
PROMPT_VERSION = 1  # bump when the instructions change, so cached descriptions are told apart

INSTRUCTIONS = """\
You write the subject line for a trading-card illustration that an image model will paint from scratch.

The card:
{facts}

First, describe what this picture shows in two or three sentences: who or what is in it and how they look \
(species, build, clothing, weapons, colours), what they are doing, and the setting and light.

Then write the subject line for a new illustration of the same card: a comma-separated phrase of 12 to 30 words. \
Keep the figure's identity and look from the picture so the card stays recognisable; take the action from what the \
card's text says it does; the scene may be new. Content only -- no medium, art style, palette, mood, artist names or \
quality words, and no card game terms: a separate style prompt supplies those.

Answer with one JSON object and nothing else: {{"description": "...", "subject": "..."}}"""


class Describer:
    """One vision call: an image and a card's facts in, a description and a subject line out."""

    def __init__(self, kind="claude", model=None, key=None, url=None):
        if kind not in DESCRIBERS:
            raise MintError(f"describer must be one of {', '.join(DESCRIBERS)}, not {kind!r}")
        self.kind = kind
        self.model = model or DEFAULT_MODEL[kind]
        self.key = key if key is not None else os.environ.get("ANTHROPIC_API_KEY", "")
        self.url = (url or "http://127.0.0.1:11434").rstrip("/")

    @classmethod
    def from_workspace(cls, ws):
        return cls(ws.describer, ws.describe_model or None, url=ws.ollama_url)

    def ready(self):
        """(True, "") when a call could go out, else (False, why not)."""
        if self.kind == "claude" and not self.key:
            return False, "no ANTHROPIC_API_KEY in the environment; set it, or `describer = \"ollama\"` in mint.toml"
        return True, ""

    def alive(self):
        """Whether the describer would answer now: the key is there (claude), or Ollama is up."""
        if not self.ready()[0]:
            return False
        if self.kind == "ollama":
            try:
                with urllib.request.urlopen(self.url + "/api/tags", timeout=5):
                    return True
            except (urllib.error.URLError, TimeoutError):
                return False
        return True

    def require(self):
        ok, why = self.ready()
        if not ok:
            raise MintError(f"the {self.kind} describer is not set up: {why}")

    def describe(self, image_path, card, entry=None):
        """Read the image and the card; return {"description", "subject", "model"}."""
        self.require()
        text = INSTRUCTIONS.format(facts=facts(card, entry))
        with open(image_path, "rb") as f:
            data = f.read()
        answer = self._ask(data, mime(image_path), text)
        out = parse(answer)
        out["model"] = f"{self.kind}:{self.model}"
        return out

    # --- the two transports ---------------------------------------------------
    def _ask(self, data, mime_type, text):
        if self.kind == "claude":
            body = {"model": self.model, "max_tokens": 600, "messages": [{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": mime_type, "data": base64.b64encode(data).decode()}},
                {"type": "text", "text": text}]}]}
            req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=json.dumps(body).encode(), headers={
                "Content-Type": "application/json", "x-api-key": self.key, "anthropic-version": "2023-06-01"})
            r = self._send(req)
            return "".join(b.get("text", "") for b in r.get("content", []))
        body = {"model": self.model, "stream": False, "format": "json",
                "messages": [{"role": "user", "content": text, "images": [base64.b64encode(data).decode()]}]}
        req = urllib.request.Request(self.url + "/api/chat", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        return self._send(req).get("message", {}).get("content", "")

    def _send(self, req):
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:300]
            raise MintError(f"the {self.kind} describer answered {e.code}: {detail}") from None
        except (urllib.error.URLError, TimeoutError) as e:
            where = self.url if self.kind == "ollama" else "api.anthropic.com"
            raise MintError(f"no {self.kind} describer at {where}: {e}") from None


def facts(card, entry=None):
    """The card as the describer reads it: name, type line, rules and flavor text, and what the
    set file already says the subject is (a hand-written line is a hint, not a constraint)."""
    lines = [f"Name: {card['name']}", f"Type: {card.get('type_line', '')}"]
    if card.get("oracle_text"):
        lines.append("Text: " + card["oracle_text"].replace("\n", " / "))
    flavor = entry.flavor if entry and entry.flavor else card.get("flavor_text")
    if flavor:
        lines.append("Flavor: " + flavor.replace("\n", " "))
    if card.get("power") is not None and card.get("toughness") is not None:
        lines.append(f"Power/toughness: {card['power']}/{card['toughness']}")
    if entry and entry.subject:
        lines.append("Current subject line: " + entry.subject)
    return "\n".join(lines)


def parse(answer):
    """The {"description", "subject"} object out of a model's answer, however it wrapped it."""
    m = re.search(r"\{.*\}", answer or "", re.S)
    try:
        d = json.loads(m.group(0)) if m else None
    except json.JSONDecodeError:
        d = None
    if not isinstance(d, dict) or not str(d.get("subject", "")).strip():
        raise MintError(f"the describer's answer holds no subject line: {(answer or '').strip()[:200]!r}")
    subject = " ".join(str(d["subject"]).split()).strip().rstrip(".")
    return {"description": " ".join(str(d.get("description", "")).split()).strip(), "subject": subject}


def mime(path):
    ext = os.path.splitext(str(path))[1].lower()
    return {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}.get(ext, "image/png")


def base_of(st, entry):
    """What the describer looks at: the image the card's restyles start from, by the same rule
    (its own base, else the set's, else the crop)."""
    return entry.base or st.base or "crop"


def describe_card(describer, art, card, st, entry=None):
    """Describe one card's base image and return its record, which is also written beside the
    image (art.describe). The set file is not touched here: the caller writes the subject."""
    entry = entry or st.card(card)
    base = base_of(st, entry)
    if art is not None and sets.is_label(base):
        v = art.latest(card, base)
        base = v.hash if v else base
    src = art.base_path(card, base)
    d = describer.describe(src, card, entry)
    d["base"] = "crop" if base == "crop" else base
    d["prompt_version"] = PROMPT_VERSION
    return art.describe(card, d)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="mint describe", description=__doc__.split("\n\n")[0])
    ap.add_argument("names", nargs="*")
    ap.add_argument("--set", required=True)
    ap.add_argument("--force", action="store_true", help="rewrite subjects the set file already has")
    ap.add_argument("--generate", action="store_true", help="then make each card's `new` scene in the set's style")
    ap.add_argument("--no-upscale", action="store_true", help="with --generate: skip the ESRGAN pass")
    a = ap.parse_args(argv)
    ws = workspace.default()
    try:
        st = sets.load(a.set)
        names = a.names or st.names()
        if not names:
            ap.error("the set has no cards")
        describer = Describer.from_workspace(ws)
        describer.require()
        server = None
        if a.generate:
            from . import comfy
            if st.style is None:
                raise MintError(f"{a.set} has no `style` block to generate in")
            server = comfy.Comfy(ws.comfy_url)
            server.require()
        cards, art = Cards(ws.cards_file), Art(ws.art)
        for name in names:
            entry = st.card({"name": name})
            card = cards.find(name, entry.printing)
            if entry.subject and not a.force:
                print(f"kept      {card['name']}: {entry.subject}")
            else:
                d = describe_card(describer, art, card, st, entry)
                st.cards[name] = sets.from_dict({"code": "x", "cards": {name: {
                    **{k: v for k, v in vars(entry).items() if v is not None}, "subject": d["subject"]}}}).cards[name]
                sets.save(st.path, st)
                print(f"described {card['name']}: {d['subject']}")
            if server is not None:
                from . import restyle
                v, made = restyle.restyle(server, art, card, st, upscale=not a.no_upscale, remix="new")
                print(f"{'new     ' if made else 'cached  '}  {card['name']} -> {os.path.relpath(v.path)}")
    except MintError as e:
        sys.exit(str(e))


if __name__ == "__main__":
    main()

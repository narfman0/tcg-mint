"""Set files: the JSON that says what a set is.

    {
      "code": "BLS1", "name": "...", "size": 18,
      "art_filter": "saturate(1.4)",             CSS filter for --styled when no restyle exists
      "style": {...},                            see restyle.py
      "cards": {"Card Name": {"number": 1, "flavor": "...", "art": "path.png",
                              "art_filter": "...", "subject": "...", "printing": "rvr:40"}}
    }

A .css file with the same stem (sets/bls1.css) is injected after the frame's
own rules, for the set's identity.
"""
import json
import os
from pathlib import Path

from .errors import SetError


def load(path):
    """The set dict plus its optional sibling .css."""
    path = Path(path)
    try:
        st = json.loads(path.read_text())
    except FileNotFoundError:
        raise SetError(f"no set file {path}") from None
    except json.JSONDecodeError as e:
        raise SetError(f"{path}: not valid JSON ({e})") from None
    css_fn = path.with_suffix(".css")
    return st, css_fn.read_text() if css_fn.exists() else ""


def save(path, st):
    path = Path(path)
    os.makedirs(path.parent, exist_ok=True)
    tmp = path.with_suffix(".json.part")
    tmp.write_text(json.dumps(st, indent=2, ensure_ascii=False) + "\n")
    os.replace(tmp, path)


def overrides(st, card):
    """The set file's entry for a card, keyed by either its face name or its full 'A // B' name."""
    cards = st.get("cards", {})
    return cards.get(card["name"]) or cards.get(card.get("full_name", ""), {})

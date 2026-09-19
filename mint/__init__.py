"""tcg-mint: render trading cards from Scryfall data into your own frame, at print resolution.

Everything that is *yours* or *cached* lives in the workspace, MINT_HOME
(default: the current directory): fonts/, art/, symbols/, oracle-cards.jsonl
and your sets/. The package itself only ships code and the frame template.
"""
import os
from pathlib import Path

__version__ = "0.1.0"

PKG = Path(__file__).resolve().parent
HOME = Path(os.environ.get("MINT_HOME", os.getcwd())).resolve()


def home(*parts):
    """A path inside the workspace."""
    return HOME.joinpath(*parts)


# MINT_CARDS lets several projects share one ~200 MB Scryfall file
CARDS = Path(os.environ.get("MINT_CARDS", home("oracle-cards.jsonl")))
FONTS = home("fonts")
ART = home("art")
SYMBOLS = home("symbols")

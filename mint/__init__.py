"""tcg-mint: render trading cards from Scryfall data into your own frame, at print resolution.

Everything that is *yours* or *cached* lives in the workspace (see workspace.py);
the package itself only ships code and the frame templates.
"""
from pathlib import Path

__version__ = "0.1.0"

PKG = Path(__file__).resolve().parent

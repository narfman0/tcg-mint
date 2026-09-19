"""The one place we talk to Scryfall.

Scryfall refuses requests without a User-Agent and asks for 50-100 ms between
requests; every fetch in the package goes through here so both rules hold
everywhere. Downloads land atomically (written to a .part file, then renamed)
so an interrupted fetch never leaves a truncated file that later reads as a
cached success.
"""
import json
import os
import shutil
import time
import urllib.request

from . import __version__

UA = f"tcg-mint/{__version__} (+https://github.com/narfman0/tcg-mint)"
API = "https://api.scryfall.com"
GAP = 0.1  # seconds between requests
_last = 0.0


def _pace():
    global _last
    wait = _last + GAP - time.monotonic()
    if wait > 0:
        time.sleep(wait)
    _last = time.monotonic()


def _open(url, timeout):
    _pace()
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    return urllib.request.urlopen(req, timeout=timeout)


def get_json(url, timeout=30):
    with _open(url, timeout) as resp:
        return json.load(resp)


def fetch(url, dest, timeout=300):
    """Download url to dest (a Path or str), atomically. Returns dest."""
    dest = str(dest)
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    tmp = dest + ".part"
    with _open(url, timeout) as resp, open(tmp, "wb") as fh:
        shutil.copyfileobj(resp, fh)
    os.replace(tmp, dest)
    return dest

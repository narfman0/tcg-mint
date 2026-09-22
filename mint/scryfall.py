"""The one place we talk to Scryfall.

Scryfall refuses requests without a User-Agent and asks for 50-100 ms between
requests; every fetch in the package goes through here so both rules hold
everywhere. Downloads land atomically (written to a .part file, then renamed)
so an interrupted fetch never leaves a truncated file that later reads as a
cached success. Two threads after the same file (the workbench's printing
picker asks for a crop twice when the default is also in the list) take turns
on it: the second finds it on disk and fetches nothing.
"""
import json
import os
import shutil
import threading
import time
import urllib.request

from . import __version__

UA = f"tcg-mint/{__version__} (+https://github.com/narfman0/tcg-mint)"
API = "https://api.scryfall.com"
GAP = 0.1  # seconds between requests
_last = 0.0
_pacing = threading.Lock()
_files = threading.Lock()  # guards _fetching
_fetching: dict[str, threading.Lock] = {}  # one lock per destination being fetched


def _pace():
    global _last
    with _pacing:
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
    """Download url to dest (a Path or str), atomically, unless a concurrent fetch of the same
    dest lands it first. Returns dest."""
    dest = str(dest)
    with _files:
        lock = _fetching.setdefault(dest, threading.Lock())
    with lock:
        if os.path.exists(dest):
            return dest
        os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
        tmp = f"{dest}.{threading.get_ident()}.part"
        try:
            with _open(url, timeout) as resp, open(tmp, "wb") as fh:
                shutil.copyfileobj(resp, fh)
            os.replace(tmp, dest)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
    with _files:
        _fetching.pop(dest, None)
    return dest

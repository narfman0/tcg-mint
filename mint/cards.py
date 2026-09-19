"""Fetch Scryfall's bulk card file.

    mint cards [--kind oracle_cards] [--max-age DAYS] [--force]

Scryfall rebuilds its bulk files daily and has no delta feed, so this checks
the few-KB metadata endpoint and only downloads the archive when Scryfall's
copy is newer than the one we hold. The file lands at MINT_CARDS (default
oracle-cards.jsonl in the workspace); it is ~200 MB decompressed and belongs
in .gitignore, never in git.

`oracle_cards` is one entry per distinct card (the default printing); switch
to `default_cards` when you want to pick art from a specific printing.
"""
import argparse
import gzip
import json
import os
import shutil
import sys
import urllib.error
from datetime import datetime, timedelta, timezone

from . import CARDS, scryfall

BULK = scryfall.API + "/bulk-data"


def remote_meta(kind):
    for entry in scryfall.get_json(BULK)["data"]:
        if entry["type"] == kind:
            return entry
    sys.exit(f"scryfall no longer publishes a {kind!r} bulk file")


def stamp_path():
    return CARDS.with_suffix(".stamp.json")


def local_stamp():
    try:
        return json.load(open(stamp_path()))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def download(uri):
    archive = CARDS.with_suffix(CARDS.suffix + ".gz")
    scryfall.fetch(uri, archive)
    # decompress to a temp file so a failure mid-stream can't leave a truncated card file
    tmp = str(CARDS) + ".part"
    with gzip.open(archive, "rb") as src, open(tmp, "wb") as dst:
        shutil.copyfileobj(src, dst)
    os.replace(tmp, CARDS)
    archive.unlink()


def main(argv=None):
    ap = argparse.ArgumentParser(prog="mint cards", description=__doc__.split("\n\n")[0])
    ap.add_argument("--kind", default="oracle_cards", choices=["oracle_cards", "default_cards", "all_cards"])
    ap.add_argument("--max-age", type=float, default=7, metavar="DAYS",
                    help="skip the network entirely if the local file is newer than this (default 7)")
    ap.add_argument("--force", action="store_true", help="re-download even if Scryfall's copy is not newer")
    a = ap.parse_args(argv)

    have = CARDS.exists()
    st = local_stamp()
    fetched = datetime.fromisoformat(st["fetched"]) if st.get("fetched") else None
    if have and fetched and datetime.now(timezone.utc) - fetched < timedelta(days=a.max_age) and not a.force \
            and st.get("kind") == a.kind:
        print(f"{CARDS.name} is fresh (fetched {fetched:%Y-%m-%d}, max-age {a.max_age}d); nothing to do")
        return

    try:
        meta = remote_meta(a.kind)
    except (urllib.error.URLError, TimeoutError) as err:
        if have:
            print(f"scryfall unreachable ({err}); keeping the cached card file, which may be stale")
            return
        sys.exit(f"scryfall unreachable and no cached card file: {err}")

    updated = datetime.fromisoformat(meta["updated_at"])
    if have and meta["updated_at"] == st.get("updated_at") and st.get("kind") == a.kind and not a.force:
        print(f"scryfall's {a.kind} is unchanged since {updated:%Y-%m-%d}; no download needed")
    else:
        print(f"downloading {a.kind} ({meta['compressed_size'] / 1e6:.0f} MB compressed, "
              f"updated {updated:%Y-%m-%d %H:%M} UTC) -> {CARDS}")
        CARDS.parent.mkdir(parents=True, exist_ok=True)
        download(meta["jsonl_download_uri"])
    with open(stamp_path(), "w") as fh:
        json.dump({"kind": a.kind, "updated_at": meta["updated_at"],
                   "fetched": datetime.now(timezone.utc).isoformat(timespec="seconds")}, fh, indent=1)


if __name__ == "__main__":
    main()

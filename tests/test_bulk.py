"""`mint cards` freshness: when it talks to Scryfall and when it downloads, with no network."""
import json
import urllib.error
from datetime import datetime, timedelta, timezone

import pytest

from mint import bulk, workspace

OLD, NEW = "2026-09-01T09:00:00+00:00", "2026-09-18T09:00:00+00:00"


@pytest.fixture
def ws(tmp_path, monkeypatch):
    w = workspace.Workspace(tmp_path, tmp_path / "oracle-cards.jsonl")
    monkeypatch.setattr(workspace, "default", lambda: w)
    monkeypatch.setattr(bulk, "download", lambda uri, cards: pytest.fail(f"unexpected download of {uri}"))
    return w


def stamp(ws, age_days, updated_at=OLD, kind="oracle_cards"):
    fetched = datetime.now(timezone.utc) - timedelta(days=age_days)
    ws.cards_file.write_text("{}\n")
    json.dump({"kind": kind, "updated_at": updated_at, "fetched": fetched.isoformat(timespec="seconds")},
              open(bulk.stamp_path(ws.cards_file), "w"))


def meta(updated_at, kind="oracle_cards"):
    return {"type": kind, "updated_at": updated_at, "compressed_size": 5e7, "jsonl_download_uri": "https://x/cards.gz"}


def test_fresh_file_never_touches_the_network(ws, monkeypatch, capsys):
    stamp(ws, age_days=1)
    monkeypatch.setattr(bulk, "remote_meta", lambda kind: pytest.fail("asked scryfall"))
    bulk.main([])
    assert "is fresh" in capsys.readouterr().out


def test_stale_stamp_asks_but_unchanged_upstream_downloads_nothing(ws, monkeypatch, capsys):
    stamp(ws, age_days=10)
    monkeypatch.setattr(bulk, "remote_meta", lambda kind: meta(OLD))
    bulk.main([])
    assert "unchanged" in capsys.readouterr().out
    st = bulk.local_stamp(ws.cards_file)
    assert st["updated_at"] == OLD
    assert datetime.now(timezone.utc) - datetime.fromisoformat(st["fetched"]) < timedelta(minutes=1)  # re-stamped


def test_newer_upstream_downloads_and_restamps(ws, monkeypatch, capsys):
    stamp(ws, age_days=10)
    got = []
    monkeypatch.setattr(bulk, "remote_meta", lambda kind: meta(NEW))
    monkeypatch.setattr(bulk, "download", lambda uri, cards: got.append((uri, cards)))
    bulk.main([])
    assert got == [("https://x/cards.gz", ws.cards_file)]
    assert "downloading oracle_cards (50 MB" in capsys.readouterr().out
    assert bulk.local_stamp(ws.cards_file)["updated_at"] == NEW


def test_other_kind_or_force_or_missing_file_downloads(ws, monkeypatch):
    got = []
    monkeypatch.setattr(bulk, "remote_meta", lambda kind: meta(OLD, kind))
    monkeypatch.setattr(bulk, "download", lambda uri, cards: got.append(uri))
    stamp(ws, age_days=1)
    bulk.main(["--kind", "default_cards"])  # a fresh oracle file is not a default_cards file
    bulk.main(["--force"])
    ws.cards_file.unlink()
    bulk.main([])                           # stamp says fresh, but the file itself is gone
    assert len(got) == 3
    assert bulk.local_stamp(ws.cards_file)["kind"] == "oracle_cards"


def test_unreachable_scryfall_keeps_the_cache_or_fails(ws, monkeypatch, capsys):
    def down(kind):
        raise urllib.error.URLError("no route")
    monkeypatch.setattr(bulk, "remote_meta", down)
    stamp(ws, age_days=10)
    bulk.main([])
    assert "keeping the cached card file" in capsys.readouterr().out
    ws.cards_file.unlink()
    with pytest.raises(SystemExit, match="no cached card file"):
        bulk.main([])

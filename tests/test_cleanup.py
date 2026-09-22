"""mint cleanup: what is offered, what is never offered, and that removing takes only what was picked."""
import datetime as dt
import json

import pytest
from PIL import Image

from mint import cleanup, frame, sets, workspace
from mint.art import Art
from mint.errors import MintError
from mint.manifest import Manifest, frame_hash
from tests.conftest import synthetic_card

OLD = "2020-01-01T00:00:00+00:00"


@pytest.fixture
def ws(tmp_path, monkeypatch):
    monkeypatch.setenv("MINT_HOME", str(tmp_path))
    monkeypatch.delenv("MINT_CARDS", raising=False)
    monkeypatch.setattr(workspace, "_default", None)
    w = workspace.default()
    w.sets.mkdir()
    card = synthetic_card(name="Alpha", illustration_id="11111111-0000-0000-0000-000000000000")
    w.cards_file.write_text(json.dumps(card) + "\n")
    art = Art(w.art)
    art.crop(card, fetch=False).parent.mkdir(parents=True, exist_ok=True)
    art.crop(card, fetch=False).write_bytes(b"jpg" * 400)
    return w


def render_row(m, out, fn, *, at, fhash, card="Alpha", design="m15", styled=False, size=(272, 372)):
    m.entries[fn] = {"card": card, "number": 1, "theme": "wizards", "set": "TST", "styled": styled, "design": design,
                     "back": False, "source": {"kind": "crop", "hash": None}, "sizes": {"text": 8.0},
                     "shrunk": False, "frame": fhash, "dpi": 1200, "rendered_at": at}
    Image.new("RGB", size, (20, 40, 80)).save(out / fn)


def a_set(ws, **cards):
    st = sets.from_dict({"code": "TST", "name": "t", "cards": cards or {"Alpha": {"number": 1}}})
    sets.save(ws.sets / "tst.json", st)
    return sets.load(ws.sets / "tst.json")


def ids_by_group(report):
    out = {}
    for i in report["items"]:
        out.setdefault(i.group, []).append(i)
    return out


def test_a_card_keeps_what_it_prints_and_offers_the_rest(ws):
    """Three renders of one card: the newest is what it prints, so only the two behind it are
    offered -- and each is offered with the bytes it actually takes."""
    st = a_set(ws)
    out = ws.home / "out" / "tst"
    out.mkdir(parents=True)
    fh = frame_hash(st.css, frame.frame_css(st.frame))
    m = Manifest(out)
    render_row(m, out, "TST-001_Alpha-newest.png", at="2026-09-01T00:00:00+00:00", fhash=fh)
    render_row(m, out, "TST-001_Alpha-older.png", at=OLD, fhash=fh, design="retro")
    render_row(m, out, "TST-001_Alpha-oldest.png", at="2019-01-01T00:00:00+00:00", fhash=fh, design="fullart")
    m.save()

    by = ids_by_group(cleanup.candidates(ws))
    offered = sorted(i.what for i in by["render-superseded"])
    assert offered == ["TST-001_Alpha-older.png", "TST-001_Alpha-oldest.png"]  # not the newest
    for i in by["render-superseded"]:
        assert i.bytes == (out / i.what).stat().st_size and i.bytes > 0
        assert i.set_code == "TST" and i.card == "Alpha" and i.age_days() > 300


def test_the_render_a_card_is_pinned_to_is_never_offered(ws):
    """A pin says this card prints as this file. Age does not override that."""
    st = a_set(ws, Alpha={"number": 1, "render": "TST-001_Alpha-oldest.png"})
    out = ws.home / "out" / "tst"
    out.mkdir(parents=True)
    fh = frame_hash(st.css, frame.frame_css(st.frame))
    m = Manifest(out)
    render_row(m, out, "TST-001_Alpha-newest.png", at="2026-09-01T00:00:00+00:00", fhash=fh)
    render_row(m, out, "TST-001_Alpha-oldest.png", at=OLD, fhash=fh)
    m.save()

    what = [i.what for i in cleanup.candidates(ws)["items"]]
    assert "TST-001_Alpha-oldest.png" not in what   # pinned
    assert "TST-001_Alpha-newest.png" not in what   # the newest of its kind, so still the styled/plain answer


def test_nothing_younger_than_keep_days_is_offered(ws):
    st = a_set(ws)
    out = ws.home / "out" / "tst"
    out.mkdir(parents=True)
    fh = frame_hash(st.css, frame.frame_css(st.frame))
    m = Manifest(out)
    now = dt.datetime.now(dt.timezone.utc)
    render_row(m, out, "TST-001_Alpha-new.png", at=now.isoformat(), fhash=fh)
    render_row(m, out, "TST-001_Alpha-yesterday.png", at=(now - dt.timedelta(days=1)).isoformat(), fhash=fh)
    render_row(m, out, "TST-001_Alpha-lastmonth.png", at=(now - dt.timedelta(days=30)).isoformat(), fhash=fh)
    m.save()

    assert [i.what for i in cleanup.candidates(ws, keep_days=3)["items"]] == ["TST-001_Alpha-lastmonth.png"]
    assert [i.what for i in cleanup.candidates(ws, keep_days=90)["items"]] == []   # everything is recent enough
    got = sorted(i.what for i in cleanup.candidates(ws, keep_days=0)["items"])
    assert got == ["TST-001_Alpha-lastmonth.png", "TST-001_Alpha-yesterday.png"]   # still never the newest


def test_removing_takes_the_ids_given_and_nothing_else(ws):
    st = a_set(ws)
    out = ws.home / "out" / "tst"
    out.mkdir(parents=True)
    fh = frame_hash(st.css, frame.frame_css(st.frame))
    m = Manifest(out)
    render_row(m, out, "TST-001_Alpha-newest.png", at="2026-09-01T00:00:00+00:00", fhash=fh)
    render_row(m, out, "TST-001_Alpha-a.png", at=OLD, fhash=fh)
    render_row(m, out, "TST-001_Alpha-b.png", at=OLD, fhash=fh)
    m.save()

    by = ids_by_group(cleanup.candidates(ws))["render-superseded"]
    one = next(i for i in by if i.what == "TST-001_Alpha-a.png")
    r = cleanup.remove(ws, [one.id])
    assert r["removed"] == 1 and r["bytes"] == one.bytes and r["missed"] == []
    assert not (out / "TST-001_Alpha-a.png").exists()
    assert (out / "TST-001_Alpha-b.png").exists() and (out / "TST-001_Alpha-newest.png").exists()
    left = set(Manifest(out).entries)
    assert left == {"TST-001_Alpha-newest.png", "TST-001_Alpha-b.png"}  # the row went with the file
    with pytest.raises(MintError, match="nothing selected"):
        cleanup.remove(ws, [])


def test_two_rows_of_one_manifest_both_stay_dropped(ws):
    """Both rows come from the same manifest file: dropping them must not write each other back."""
    st = a_set(ws)
    out = ws.home / "out" / "tst"
    out.mkdir(parents=True)
    fh = frame_hash(st.css, frame.frame_css(st.frame))
    m = Manifest(out)
    render_row(m, out, "TST-001_Alpha-newest.png", at="2026-09-01T00:00:00+00:00", fhash=fh)
    render_row(m, out, "TST-001_Alpha-a.png", at=OLD, fhash=fh)
    render_row(m, out, "TST-001_Alpha-b.png", at=OLD, fhash="00000000")  # stale as well as superseded
    m.save()

    report = cleanup.candidates(ws)
    both = [i.id for i in report["items"] if i.what in ("TST-001_Alpha-a.png", "TST-001_Alpha-b.png")]
    assert len(both) == 2   # each file offered once, under one reason
    cleanup.remove(ws, both)
    assert set(Manifest(out).entries) == {"TST-001_Alpha-newest.png"}
    assert sorted(p.name for p in out.glob("*.png")) == ["TST-001_Alpha-newest.png"]


def test_an_id_that_stopped_being_a_candidate_is_refused(ws):
    """The page's selection is a moment old by the time it is sent. An id that has since become the
    card's pin is reported back, not obeyed."""
    st = a_set(ws)
    out = ws.home / "out" / "tst"
    out.mkdir(parents=True)
    fh = frame_hash(st.css, frame.frame_css(st.frame))
    m = Manifest(out)
    render_row(m, out, "TST-001_Alpha-newest.png", at="2026-09-01T00:00:00+00:00", fhash=fh)
    render_row(m, out, "TST-001_Alpha-old.png", at=OLD, fhash=fh)
    m.save()
    picked = ids_by_group(cleanup.candidates(ws))["render-superseded"][0]

    st.cards["Alpha"].render = "TST-001_Alpha-old.png"   # pinned in the meantime
    sets.save(st.path, st)
    r = cleanup.remove(ws, [picked.id])
    assert r["removed"] == 0 and r["missed"] == [picked.id]
    assert (out / "TST-001_Alpha-old.png").exists()


def test_grouped_totals_and_the_cli(ws, capsys):
    st = a_set(ws)
    out = ws.home / "out" / "tst"
    out.mkdir(parents=True)
    fh = frame_hash(st.css, frame.frame_css(st.frame))
    m = Manifest(out)
    render_row(m, out, "TST-001_Alpha-newest.png", at="2026-09-01T00:00:00+00:00", fhash=fh)
    render_row(m, out, "TST-001_Alpha-old.png", at=OLD, fhash=fh)
    m.save()
    (out / "stray.png").write_bytes(b"png" * 100)

    g = cleanup.grouped(cleanup.candidates(ws))
    assert g["count"] == 2 and g["bytes"] == sum(b["bytes"] for b in g["groups"])
    assert [b["key"] for b in g["groups"]] == ["render-superseded", "render-orphan"]
    assert all(b["why"] and b["title"] for b in g["groups"])

    assert cleanup.main([]) == 0
    printed = capsys.readouterr().out
    assert "renders a card no longer prints" in printed and "2 item(s)" in printed
    assert "Nothing to remove" not in printed
    assert sorted(p.name for p in out.glob("*.png")) == [  # listing removes nothing
        "TST-001_Alpha-newest.png", "TST-001_Alpha-old.png", "stray.png"]

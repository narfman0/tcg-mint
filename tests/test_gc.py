"""mint gc: what stays (picked, current, rendered, a base, fresh) and what goes, and stale renders."""
import datetime as dt
import json

import pytest

from mint import frame, gc, sets, workspace
from mint.art import Art
from mint.manifest import Manifest, frame_hash
from tests.conftest import synthetic_card


@pytest.fixture
def ws(tmp_path, monkeypatch):
    monkeypatch.setenv("MINT_HOME", str(tmp_path))
    monkeypatch.delenv("MINT_CARDS", raising=False)
    monkeypatch.setattr(workspace, "_default", None)
    w = workspace.default()
    w.sets.mkdir()
    cards = [synthetic_card(name=n, collector_number=str(i), illustration_id=f"{i:08d}-0000-0000-0000-000000000000")
             for i, n in enumerate(["Alpha", "Beta"], 1)]
    w.cards_file.write_text("".join(json.dumps(c) + "\n" for c in cards))
    return w


def variant(art, card, label, hash, kind="restyle", base="crop", created=None, recipe=None):
    v = art.new_variant(card, label, kind, recipe or {"prompt": "x", "base": base}, base, hash)
    if created:
        v.created = created
    v.path.parent.mkdir(parents=True, exist_ok=True)
    v.path.write_bytes(b"png" * 100)
    return art.record(v)


def test_collect_keeps_the_right_variants_and_finds_stale_renders(ws):
    st = sets.from_dict({"code": "TST", "name": "t", "style": {"name": "look", "prompt": "p"},
                         "cards": {"Alpha": {"number": 1}}})
    sets.save(ws.sets / "tst.json", st)
    st = sets.load(ws.sets / "tst.json")
    art = Art(ws.art)
    card = json.loads(ws.cards_file.read_text().splitlines()[0])
    art.crop(card, fetch=False).parent.mkdir(parents=True, exist_ok=True)
    art.crop(card, fetch=False).write_bytes(b"jpg")
    old = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=30)).isoformat(timespec="seconds")
    cur_hash = sets.recipe_hash(st.recipe(card, art=art))
    current = variant(art, card, "look", cur_hash, created=old, recipe=st.recipe(card, art=art))
    variant(art, card, "spore", "aaaaaaaa", created=old)  # what current was made from
    current.base = "aaaaaaaa"
    art.record(current)
    variant(art, card, "enhance", "bbbbbbbb", kind="enhance", base="aaaaaaaa", created=old)  # an enhance of that base
    variant(art, card, "look", "cccccccc", created=old)  # a stray take
    variant(art, card, "look", "dddddddd")  # a fresh take
    variant(art, card, "enhance", "eeeeeeee", kind="enhance", base="cccccccc", created=old)  # an enhance of the stray
    # a variant of a card no set has
    beta = json.loads(ws.cards_file.read_text().splitlines()[1])
    variant(art, beta, "look", "ffffffff", created=old)
    # renders: one current, one made before the frame changed, one whose file is gone
    out = ws.home / "out" / "tst"
    out.mkdir(parents=True)
    m = Manifest(out)
    fh = frame_hash(st.css, frame.frame_css(st.frame))
    renders = [("TST-001_Alpha.png", fh, None), ("TST-001_Alpha.styled.png", "00000000", cur_hash), ("gone.png", fh, None)]
    for fn, fhash, src in renders:
        m.entries[fn] = {"card": "Alpha", "number": 1, "theme": "wizards", "styled": ".styled" in fn,
                         "source": {"kind": "styled" if src else "crop", "hash": src}, "frame": fhash,
                         "rendered_at": "2026-01-01"}
        if fn != "gone.png":
            (out / fn).write_bytes(b"png")
    (out / "stray.png").write_bytes(b"png")
    m.save()

    r = gc.collect(ws, keep_days=3)
    going = {v.hash for _, _, v in r["variants"]}
    assert going == {"cccccccc", "eeeeeeee"}, going       # the stray take and the enhance made from it
    assert [d.name for d in r["unreferenced"]] == [beta["illustration_id"]]
    assert [(fn, why) for _, _, fn, why in r["stale"]] == [("TST-001_Alpha.styled.png", "the frame changed")]
    assert [p.name for p in r["orphans"]] == ["stray.png"] and [fn for _, _, fn in r["dropped"]] == ["gone.png"]

    gc.main(["--delete"])
    left = {v.hash for v in art.variants(card)}
    assert left == {cur_hash, "aaaaaaaa", "bbbbbbbb", "dddddddd"}
    assert not (ws.art / beta["illustration_id"]).exists()
    assert not (out / "TST-001_Alpha.styled.png").exists() and not (out / "stray.png").exists()
    assert set(Manifest(out).entries) == {"TST-001_Alpha.png"}


def test_a_clip_of_a_kept_image_stays_and_goes_with_its_files(ws):
    st = sets.from_dict({"code": "TST", "name": "t", "style": {"name": "look", "prompt": "p"}, "cards": {"Alpha": {"number": 1}}})
    sets.save(ws.sets / "tst.json", st)
    st = sets.load(ws.sets / "tst.json")
    art = Art(ws.art)
    card = json.loads(ws.cards_file.read_text().splitlines()[0])
    art.crop(card, fetch=False).parent.mkdir(parents=True, exist_ok=True)
    art.crop(card, fetch=False).write_bytes(b"jpg")
    old = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=30)).isoformat(timespec="seconds")
    cur = sets.recipe_hash(st.recipe(card, art=art))
    variant(art, card, "look", cur, created=old, recipe=st.recipe(card, art=art))
    kept = variant(art, card, "motion", "11111111", kind="motion", base=cur, created=old)    # a clip of the current
    stray = variant(art, card, "motion", "22222222", kind="motion", base="deadbeef", created=old)  # a clip of nothing kept
    for v in (kept, stray):
        v.path.with_suffix(".webm").write_bytes(b"webm" * 100)
    r = gc.collect(ws, keep_days=3)
    assert {v.hash for _, _, v in r["variants"]} == {"22222222"}
    assert gc.files_of(stray) == [stray.path, stray.path.with_suffix(".webm")]
    gc.main(["--delete"])
    assert not stray.path.with_suffix(".webm").exists() and kept.path.with_suffix(".webm").exists()


def test_the_render_a_card_is_pinned_to_is_never_stale(ws):
    """A pin says this card prints as this file, so gc leaves it even when the frame moved on."""
    st = sets.from_dict({"code": "TST", "name": "t",
                         "cards": {"Alpha": {"number": 1, "render": "TST-001_Alpha-aaaaaaaa.png"}}})
    sets.save(ws.sets / "tst.json", st)
    art = Art(ws.art)
    card = json.loads(ws.cards_file.read_text().splitlines()[0])
    art.crop(card, fetch=False).parent.mkdir(parents=True, exist_ok=True)
    art.crop(card, fetch=False).write_bytes(b"jpg")
    out = ws.home / "out" / "tst"
    out.mkdir(parents=True)
    m = Manifest(out)
    for fn in ("TST-001_Alpha-aaaaaaaa.png", "TST-001_Alpha-bbbbbbbb.png"):
        m.entries[fn] = {"card": "Alpha", "number": 1, "theme": "wizards", "styled": False, "design": "m15",
                         "source": {"kind": "crop", "hash": None}, "frame": "00000000",  # both made before a frame fix
                         "rendered_at": "2026-01-01"}
        (out / fn).write_bytes(b"png")
    m.save()

    r = gc.collect(ws, keep_days=3)
    assert [fn for _, _, fn, _ in r["stale"]] == ["TST-001_Alpha-bbbbbbbb.png"]
    gc.main(["--delete"])
    assert set(Manifest(out).entries) == {"TST-001_Alpha-aaaaaaaa.png"}

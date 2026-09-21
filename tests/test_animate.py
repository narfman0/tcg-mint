"""mint animate: the motion block and recipe, the Wan graph, the loop treatment, the motion variant."""
import json
import shutil

import pytest
from PIL import Image

from mint import animate, loop, sets, wan
from mint.art import Art
from mint.errors import MintError, SetError
from tests.conftest import synthetic_card

BASE = {"code": "TST", "name": "t", "style": {"name": "look", "prompt": "pen and ink"},
        "cards": {"Alpha": {"number": 1, "subject": "a dog"}, "Beta": {"number": 2}}}


def frames(n, size=(32, 16)):
    return [Image.new("RGB", size, (i * 255 // max(n - 1, 1), 0, 0)) for i in range(n)]


# --- the block and the recipe ---------------------------------------------------------------

def test_motion_block_round_trips_slim_and_validates():
    st = sets.from_dict({**BASE, "motion": {"prompt": "hair drifts", "length": 81}})
    assert st.motion.prompt == "hair drifts" and st.motion.length == 81 and st.motion.loop == "pingpong"
    assert st.to_dict()["motion"] == {"name": "motion", "prompt": "hair drifts", "length": 81}
    for bad in ({"length": 50}, {"width": 100}, {"loop": "bounce"}, {"formats": ["avi"]}, {"remix": "repose"},
                {"loop": "crossfade", "crossfade": 30}, {"typo": 1}):
        with pytest.raises(SetError):
            sets.from_dict({**BASE, "motion": {"prompt": "x", **bad}})
    with pytest.raises(SetError):
        sets.from_dict({**BASE, "cards": {"Alpha": {"motion": 3}}})


def test_motion_recipe_takes_the_card_line_seed_and_base(tmp_path):
    st = sets.from_dict({**BASE, "motion": {"prompt": "hair drifts"},
                         "cards": {**BASE["cards"], "Beta": {"motion": "waves roll"}}})
    alpha, beta = synthetic_card(name="Alpha", illustration_id="aaaa"), synthetic_card(name="Beta", illustration_id="bbbb")
    r = st.motion_recipe(alpha)
    assert r["prompt"] == "hair drifts" and r["base"] == "crop" and "remix" not in r
    assert "name" not in r and "seed_rule" not in r and "crossfade" not in r and "gif_width" not in r and "loras" not in r
    assert r["seed"] == 7000 + __import__("zlib").crc32(b"aaaa") % 1000
    assert st.motion_recipe(beta)["prompt"] == "waves roll"  # the card's line replaces the prompt
    # a set without a block animates with the defaults
    assert sets.from_dict(BASE).motion_recipe(alpha)["prompt"] == sets.Motion().prompt
    # the no-op knobs join the hash only when they do something
    st2 = sets.from_dict({**BASE, "motion": {"loop": "crossfade", "crossfade": 8, "formats": ["gif", "webm"], "gif_width": 320}})
    r2 = st2.motion_recipe(alpha)
    assert r2["crossfade"] == 8 and r2["gif_width"] == 320
    # new: words alone, the subject first, no image
    r3 = st.motion_recipe(alpha, remix="new")
    assert r3["prompt"] == "a dog, hair drifts" and r3["base"] == "none" and r3["remix"] == "new"
    assert st.motion_recipe(beta, remix="new")["prompt"].startswith("Beta, Creature")
    # a one-off seed and base
    r4 = st.motion_recipe(alpha, seed=5, base="deadbeef")
    assert r4["seed"] == 5 and r4["base"] == "deadbeef" and sets.recipe_hash(r4) != sets.recipe_hash(r)
    with pytest.raises(SetError):
        st.motion_recipe(alpha, remix="bounce")


def test_motion_recipe_starts_from_the_styled_art(tmp_path):
    """Without a base, the clip starts from what `render --styled` would use: the picked or current
    restyle, its enhance when there is one, else the crop."""
    st = sets.from_dict(BASE)
    art = Art(tmp_path)
    card = synthetic_card(name="Alpha")
    crop = art.crop(card, fetch=False)
    crop.parent.mkdir(parents=True, exist_ok=True)
    crop.write_bytes(b"jpg")
    assert st.motion_recipe(card, art=art)["base"] == "crop"
    cur = sets.recipe_hash(st.recipe(card, art=art))
    for label, kind, base, h in [("look", "restyle", "crop", cur), ("enhance", "enhance", cur, "e1e1e1e1")]:
        v = art.new_variant(card, label, kind, {"x": 1}, base, h)
        v.path.parent.mkdir(parents=True, exist_ok=True)
        v.path.write_bytes(b"png")
        art.record(v)
    assert st.motion_recipe(card, art=art)["base"] == "e1e1e1e1"
    st.cards["Alpha"].pick = "e1e1e1e1"
    assert st.motion_recipe(card, art=art)["base"] == "e1e1e1e1" and st.motion_recipe(card)["base"] == "e1e1e1e1"


# --- the graph --------------------------------------------------------------------------------

def test_workflow_shape():
    r = sets.from_dict(BASE).motion_recipe(synthetic_card(), seed=42)
    w = wan.workflow("in.png", r, 42, "x")
    kinds = {n["class_type"] for n in w.values()}
    assert {"UNETLoader", "CLIPLoader", "VAELoader", "ModelSamplingSD3", "Wan22ImageToVideoLatent", "KSampler",
            "VAEDecode", "SaveImage", "LoadImage"} <= kinds
    assert w["8"]["inputs"]["width"] == 832 and w["8"]["inputs"]["height"] == 576 and w["8"]["inputs"]["length"] == 49
    assert w["8"]["inputs"]["start_image"] == ["7", 0]
    assert w["9"]["inputs"]["seed"] == 42 and w["9"]["inputs"]["denoise"] == 1.0
    assert w["5"]["inputs"]["text"] == r["prompt"] and w["2"]["inputs"]["type"] == "wan"
    assert w["4"]["inputs"]["model"] == ["1", 0]  # no loras: sampling patches the base model
    for n in w.values():  # every reference points at a node that exists
        for v in n["inputs"].values():
            if isinstance(v, list):
                assert v[0] in w


def test_workflow_from_words_reads_no_image():
    r = sets.from_dict(BASE).motion_recipe(synthetic_card(), remix="new")
    w = wan.workflow(None, r, 1, "x")
    assert "7" not in w and "start_image" not in w["8"]["inputs"]
    assert "LoadImage" not in {n["class_type"] for n in w.values()}


def test_lora_chain():
    r = dict(sets.from_dict(BASE).motion_recipe(synthetic_card()),
             loras=[{"name": "a.safetensors"}, {"name": "b.safetensors", "strength": 0.5}])
    w = wan.workflow("in.png", r, 0, "x")
    assert w["lora0"]["inputs"]["model"] == ["1", 0] and w["lora0"]["inputs"]["strength_model"] == 0.8
    assert w["lora1"]["inputs"]["model"] == ["lora0", 0] and w["lora1"]["inputs"]["strength_model"] == 0.5
    assert w["4"]["inputs"]["model"] == ["lora1", 0]


# --- the loop ---------------------------------------------------------------------------------

def test_pingpong():
    seq = loop.pingpong(frames(5))
    assert len(seq) == 8
    assert [f.getpixel((0, 0))[0] for f in seq] == [0, 63, 127, 191, 255, 191, 127, 63]


def test_crossfade():
    seq = loop.crossfade(frames(9), 2)
    assert len(seq) == 7
    assert abs(seq[-1].getpixel((0, 0))[0] - seq[0].getpixel((0, 0))[0]) < 128  # the join is soft
    assert loop.crossfade(frames(5), 0) == frames(5)
    with pytest.raises(MintError):
        loop.crossfade(frames(5), 3)


def test_looped_dispatch():
    assert len(loop.looped(frames(5), "none")) == 5
    assert len(loop.looped(frames(5), "pingpong")) == 8
    with pytest.raises(MintError):
        loop.looped(frames(5), "bounce")


def test_encode_args():
    a = loop.encode_args("%04d.png", "o.webm", 24, "webm")
    assert a[0] == "ffmpeg" and "libvpx-vp9" in a and a[-1] == "o.webm"
    g = loop.encode_args("%04d.png", "o.gif", 12, "gif", 480)
    assert "palettegen" in g[g.index("-vf") + 1] and "scale=480" in g[g.index("-vf") + 1] and "-loop" in g
    assert "scale=" not in loop.encode_args("%04d.png", "o.gif", 12, "gif", 0)[-3]
    assert "apng" in loop.encode_args("f", "o.apng", 24, "apng")
    with pytest.raises(MintError):
        loop.encode_args("f", "o.avi", 24, "avi")


# --- the variant ------------------------------------------------------------------------------

class FakeComfy:
    """Answers a workflow with a few coloured frames, as run_to_frames would."""
    def __init__(self):
        self.graphs = []

    def upload(self, path):
        return "up/" + path.split("/")[-1]

    def run_to_frames(self, workflow, directory, timeout=0):
        self.graphs.append(workflow)
        paths = []
        for i, f in enumerate(frames(5, (64, 32))):
            p = f"{directory}/{i:04d}.png"
            f.save(p)
            paths.append(p)
        return paths


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="no ffmpeg")
def test_animate_makes_a_poster_and_clips_beside_it(tmp_path, art):
    st = sets.from_dict({**BASE, "motion": {"formats": ["webm", "gif"], "gif_width": 32}})
    cache = Art(tmp_path / "art")
    card = synthetic_card(name="Alpha")
    crop = cache.crop(card, fetch=False)
    crop.parent.mkdir(parents=True)
    shutil.copy(art, crop)
    server = FakeComfy()
    v, made = animate.animate(server, cache, card, st)
    assert made and v.kind == "motion" and v.label == "motion" and v.base == "crop"
    assert v.path.exists() and Image.open(v.path).size == (64, 32)
    assert [p.suffix for p in v.videos] == [".gif", ".webm"]
    with Image.open(v.path.with_suffix(".gif")) as g:
        assert g.n_frames == 8 and g.size[0] == 32  # pingpong of 5 frames, at the gif width
    assert server.graphs[0]["7"]["inputs"]["image"].startswith("up/")
    # cached the second time; forced the third; a different base is a different clip
    assert animate.animate(server, cache, card, st) == (v, False)
    assert animate.animate(server, cache, card, st, force=True)[1]
    assert cache.variants(card)[0].videos == v.videos
    v2, _ = animate.animate(server, cache, card, st, remix="new")
    assert v2.hash != v.hash and v2.base == "none" and "7" not in server.graphs[-1]
    # deleting the variant takes the clips with it
    cache.delete(v)
    assert not v.path.exists() and not v.path.with_suffix(".webm").exists() and not v.sidecar.exists()
    assert [x.hash for x in cache.variants(card)] == [v2.hash]


def test_animate_needs_ffmpeg(tmp_path, monkeypatch):
    monkeypatch.setattr(loop, "have_ffmpeg", lambda: False)
    with pytest.raises(MintError, match="ffmpeg"):
        recipe = sets.from_dict(BASE).motion_recipe(synthetic_card(), remix="new")
        animate.animate_file(FakeComfy(), None, str(tmp_path / "x"), recipe)


def test_sidecar_reads_back_as_a_motion_variant(tmp_path):
    cache = Art(tmp_path)
    card = synthetic_card()
    v = cache.new_variant(card, "motion", "motion", {"length": 49, "base": "crop"}, "crop", "abcdef12")
    v.path.parent.mkdir(parents=True)
    v.path.write_bytes(b"png")
    v.path.with_suffix(".webm").write_bytes(b"webm")
    v.path.with_suffix(".txt").write_bytes(b"not a clip")
    cache.record(v)
    assert "videos" not in json.loads(v.sidecar.read_text())
    got = cache.variants(card)[0]
    assert got.kind == "motion" and [p.name for p in got.videos] == ["motion-abcdef12.webm"]

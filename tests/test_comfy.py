"""The ComfyUI client: the bearer token rides on every request, and a refusal is told apart from a server that is down."""
import io
import json
import urllib.error
import urllib.request

import pytest

from mint import comfy
from mint.workspace import Workspace


class Served:
    """A stand-in for urlopen: records each Request, answers with canned JSON or an HTTP error."""
    def __init__(self, status=200):
        self.requests = []
        self.status = status

    def __call__(self, req, timeout=None):
        self.requests.append(req)
        if self.status != 200:
            raise urllib.error.HTTPError(req.full_url, self.status, "nope", {}, io.BytesIO(b""))
        body = {"subfolder": "tcg-mint", "name": "x.png"} if req.full_url.endswith("/upload/image") else {"ok": True}
        return io.BytesIO(json.dumps(body).encode())


def test_token_goes_on_every_request(monkeypatch, tmp_path):
    served = Served()
    monkeypatch.setattr(urllib.request, "urlopen", served)
    c = comfy.Comfy("http://gpu:8188/", token="s3cret")
    assert c.alive()
    src = tmp_path / "a.png"
    src.write_bytes(b"png")
    assert c.upload(str(src)) == "tcg-mint/x.png"
    c.fetch({"filename": "o.png", "subfolder": "", "type": "output"}, tmp_path / "o.png")
    assert [r.full_url for r in served.requests] == [
        "http://gpu:8188/system_stats", "http://gpu:8188/upload/image",
        "http://gpu:8188/view?filename=o.png&subfolder=&type=output"]
    assert all(r.get_header("Authorization") == "Bearer s3cret" for r in served.requests)
    assert served.requests[1].get_header("Content-type").startswith("multipart/form-data")


def test_no_token_means_no_header(monkeypatch):
    served = Served()
    monkeypatch.setattr(urllib.request, "urlopen", served)
    assert comfy.Comfy("http://127.0.0.1:8188").alive()
    assert served.requests[0].get_header("Authorization") is None


def test_require_explains_a_refusal(monkeypatch):
    monkeypatch.setattr(urllib.request, "urlopen", Served(401))
    with pytest.raises(comfy.ComfyError, match="wants a bearer token; set COMFY_TOKEN"):
        comfy.Comfy("http://gpu:8188").require()
    with pytest.raises(comfy.ComfyError, match="not the one it wants"):
        comfy.Comfy("http://gpu:8188", token="wrong").require()
    assert not comfy.Comfy("http://gpu:8188").alive()  # the workbench's probe still just says "down"


def test_require_when_nothing_answers(monkeypatch):
    def down(req, timeout=None):
        raise urllib.error.URLError("refused")
    monkeypatch.setattr(urllib.request, "urlopen", down)
    c = comfy.Comfy("http://127.0.0.1:8188", token="t")
    assert not c.refused()
    with pytest.raises(comfy.ComfyError, match="no ComfyUI at"):
        c.require()


def test_client_takes_url_and_token_from_the_workspace(tmp_path):
    ws = Workspace(tmp_path, tmp_path / "cards.jsonl", comfy_url="http://gpu:8188/", comfy_token="t")
    c = comfy.client(ws)
    assert (c.url, c.token) == ("http://gpu:8188", "t")
    assert comfy.client(Workspace(tmp_path, tmp_path / "cards.jsonl")).token == ""

"""A very small client for a local ComfyUI server.

ComfyUI's HTTP API takes a workflow as a graph of nodes ("API format" JSON),
runs it, and exposes the outputs. We use it as the image backend: upscaling
and style workflows. The URL comes from the workspace (COMFY_URL).
"""
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

from .errors import ComfyError

__all__ = ["Comfy", "ComfyError", "upscale_workflow"]


class Comfy:
    def __init__(self, url="http://127.0.0.1:8188"):
        self.url = url.rstrip("/")

    def _json(self, path, data=None):
        req = urllib.request.Request(self.url + path, data=json.dumps(data).encode() if data is not None else None,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)

    def alive(self):
        try:
            self._json("/system_stats")
            return True
        except (urllib.error.URLError, TimeoutError):
            return False

    def nodes(self):
        """The node class types this ComfyUI has (custom packs included), or an empty set when it is down."""
        try:
            return set(self._json("/object_info"))
        except (urllib.error.URLError, TimeoutError):
            return set()

    def options(self, class_type, input_name):
        """The choices a node's combo input offers -- CheckpointLoaderSimple's ckpt_name lists the
        checkpoint files ComfyUI has -- or None when the server or the node is not there."""
        try:
            info = self._json(f"/object_info/{class_type}")[class_type]
            spec = {**info["input"].get("required", {}), **info["input"].get("optional", {})}[input_name]
            if isinstance(spec[0], list):  # the classic form: the choices themselves
                return list(spec[0])
            if spec[0] == "COMBO" and isinstance(spec[1], dict):  # the newer form: {"options": [...]}
                return list(spec[1].get("options") or [])
            return None
        except (urllib.error.URLError, TimeoutError, KeyError, IndexError, TypeError):
            return None

    def require(self):
        if not self.alive():
            raise ComfyError(f"no ComfyUI at {self.url}; start it with: python main.py --listen 127.0.0.1 --port 8188")

    def upload(self, path, subfolder="tcg-mint"):
        """Copy a file into ComfyUI's input/ so a LoadImage node can see it. Returns the name to reference."""
        boundary = uuid.uuid4().hex
        name = os.path.basename(path)
        with open(path, "rb") as fh:
            data = fh.read()
        body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"{name}\"\r\n"
                f"Content-Type: application/octet-stream\r\n\r\n").encode() + data + \
               f"\r\n--{boundary}\r\nContent-Disposition: form-data; name=\"subfolder\"\r\n\r\n{subfolder}\r\n".encode() + \
               f"--{boundary}\r\nContent-Disposition: form-data; name=\"overwrite\"\r\n\r\ntrue\r\n--{boundary}--\r\n".encode()
        req = urllib.request.Request(self.url + "/upload/image", data=body,
                                     headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        with urllib.request.urlopen(req, timeout=120) as r:
            info = json.load(r)
        return f"{info['subfolder']}/{info['name']}" if info.get("subfolder") else info["name"]

    def run(self, workflow, timeout=600):
        """Queue a workflow and block until it finishes. Returns the history entry's outputs."""
        pid = self._json("/prompt", {"prompt": workflow, "client_id": "tcg-mint"})["prompt_id"]
        t0 = time.time()
        while time.time() - t0 < timeout:
            hist = self._json(f"/history/{pid}").get(pid)
            if hist:
                st = hist.get("status", {})
                if st.get("status_str") == "error":
                    msgs = [m for m in st.get("messages", []) if m[0] == "execution_error"]
                    raise ComfyError(msgs[0][1].get("exception_message", "workflow failed") if msgs else "workflow failed")
                return hist["outputs"]
            time.sleep(0.5)
        raise ComfyError("timed out waiting for ComfyUI")

    def fetch(self, image, dest):
        """Download one output image ({filename, subfolder, type}) to dest."""
        q = urllib.parse.urlencode({"filename": image["filename"], "subfolder": image.get("subfolder", ""),
                                    "type": image.get("type", "output")})
        with urllib.request.urlopen(self.url + "/view?" + q, timeout=120) as r, open(dest, "wb") as f:
            f.write(r.read())

    def run_to_file(self, workflow, dest, timeout=600):
        """Run a workflow whose SaveImage output is the result; save the first image to dest."""
        outputs = self.run(workflow, timeout)
        images = [im for node in outputs.values() for im in node.get("images", [])]
        if not images:
            raise ComfyError("workflow produced no image")
        self.fetch(images[0], dest)
        return dest

    def run_to_frames(self, workflow, directory, timeout=1800):
        """Run a workflow whose SaveImage output is a batch of frames; save them as
        directory/0000.png, 0001.png, ... in order. Returns the list of paths."""
        outputs = self.run(workflow, timeout)
        images = [im for node in outputs.values() for im in node.get("images", [])]
        if not images:
            raise ComfyError("workflow produced no frames")
        os.makedirs(directory, exist_ok=True)
        paths = []
        for i, im in enumerate(images):
            dest = os.path.join(directory, f"{i:04d}.png")
            self.fetch(im, dest)
            paths.append(dest)
        return paths


def upscale_workflow(image_name, model, prefix):
    """LoadImage -> UpscaleModelLoader -> ImageUpscaleWithModel -> SaveImage."""
    return {
        "1": {"class_type": "LoadImage", "inputs": {"image": image_name}},
        "2": {"class_type": "UpscaleModelLoader", "inputs": {"model_name": model}},
        "3": {"class_type": "ImageUpscaleWithModel", "inputs": {"upscale_model": ["2", 0], "image": ["1", 0]}},
        "4": {"class_type": "SaveImage", "inputs": {"images": ["3", 0], "filename_prefix": prefix}},
    }

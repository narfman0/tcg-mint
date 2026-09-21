"""The Wan 2.2 TI2V-5B video workflow, in ComfyUI's API format.

Every node is core ComfyUI (comfy_extras/nodes_wan.py) -- no custom node
packs. The 5B model is a unified text/image-to-video model that runs in 16 GB
with the fp8 umt5 text encoder; the 14B pair is prettier but needs a two-stage
sampler and quantised weights, and can come later as a second engine.

    UNETLoader ─ LoraLoaderModelOnly* ─ ModelSamplingSD3(shift) ─┐
    CLIPLoader(wan) ─ CLIPTextEncode ×2 ───────────────────────── KSampler ─ VAEDecode ─ SaveImage (one PNG per frame)
    LoadImage ─ Wan22ImageToVideoLatent(vae, w, h, length) ──────┘

With no image (`new` mode) the LoadImage node and the latent's `start_image`
are left out, and the same graph is text-to-video.
"""


def workflow(image_name, r, seed, prefix):
    """The graph for an effective motion recipe (sets.SetFile.motion_recipe); `image_name` is the
    uploaded start image, or None for a clip from the words alone."""
    w = {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": r["model"], "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": r["text_encoder"], "type": "wan", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": r["vae"]}},
    }
    model = ["1", 0]
    for i, lora in enumerate(r.get("loras") or []):
        nid = f"lora{i}"
        w[nid] = {"class_type": "LoraLoaderModelOnly",
                  "inputs": {"model": model, "lora_name": lora["name"], "strength_model": lora.get("strength", 0.8)}}
        model = [nid, 0]
    latent = {"vae": ["3", 0], "width": r["width"], "height": r["height"], "length": r["length"], "batch_size": 1}
    if image_name is not None:
        w["7"] = {"class_type": "LoadImage", "inputs": {"image": image_name}}
        latent["start_image"] = ["7", 0]
    w.update({
        "4": {"class_type": "ModelSamplingSD3", "inputs": {"model": model, "shift": r["shift"]}},
        "5": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": r["prompt"]}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": r["negative"]}},
        "8": {"class_type": "Wan22ImageToVideoLatent", "inputs": latent},
        "9": {"class_type": "KSampler", "inputs": {
            "model": ["4", 0], "positive": ["5", 0], "negative": ["6", 0], "latent_image": ["8", 0],
            "seed": seed, "steps": r["steps"], "cfg": r["cfg"], "sampler_name": r["sampler"],
            "scheduler": r["scheduler"], "denoise": 1.0}},
        "10": {"class_type": "VAEDecode", "inputs": {"samples": ["9", 0], "vae": ["3", 0]}},
        "11": {"class_type": "SaveImage", "inputs": {"images": ["10", 0], "filename_prefix": prefix}},
    })
    return w


# the motion knobs that name a model file: the node input that lists what ComfyUI has, the
# ComfyUI models/ folder each goes in, and where the repackaged files are published (doctor.py)
HF = "https://huggingface.co/Comfy-Org/Wan_2.2_ComfyUI_Repackaged/resolve/main/split_files/"
FILES = {
    "model": ("UNETLoader", "unet_name", "diffusion_models"),
    "text_encoder": ("CLIPLoader", "clip_name", "text_encoders"),
    "vae": ("VAELoader", "vae_name", "vae"),
}
NODES = ["UNETLoader", "CLIPLoader", "VAELoader", "ModelSamplingSD3", "Wan22ImageToVideoLatent", "LoraLoaderModelOnly"]


def url(knob, filename):
    """Where a missing Wan file can be fetched from."""
    return HF + FILES[knob][2] + "/" + filename

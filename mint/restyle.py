"""Regenerate card art in a set's style through ComfyUI.

    mint restyle --set sets/satoru.json [--force] [--no-upscale] ["Card Name" ...]

img2img with structure control: a ControlNet fed from the original art
(canny / lineart / depth) keeps the composition while the prompt -- and any
LoRAs -- decide how it's drawn. The whole recipe is the set file's `style`
block, so a set's look is reproducible:

    "style": {
      "name": "neon",                       -> art/<illustration_id>.neon.png
      "prompt": "...", "negative": "...",
      "control": "canny",                   canny | lineart | depth
      "control_strength": 0.8,
      "denoise": 0.85, "steps": 28, "cfg": 6, "seed": 7,
      "checkpoint": "juggernautXL_v9.safetensors",
      "loras": [{"name": "x.safetensors", "strength": 0.7}],
      "width": 1248, "height": 912          generation size (art window is 1.42:1)
    }

A card entry may add `"subject": "..."` -- what the picture is of -- which is
prepended to the prompt so the style can't drift a character into someone else.

Output is 2x the generation size (a 4x ESRGAN pass halved), ~1130 DPI on the
card. `mint render --styled` picks these up automatically.
"""
import argparse
import os
import sys
import tempfile

from . import comfy, sets, workspace
from .art import Art
from .cards import Cards
from .errors import MintError, SetError

DEFAULTS = {
    "negative": "blurry, low quality, text, watermark, signature, frame, border, deformed",
    "control": "canny", "control_strength": 0.8, "control_end": 0.9,
    "denoise": 0.85, "steps": 28, "cfg": 6.0, "seed": 7,
    "sampler": "dpmpp_2m", "scheduler": "karras",
    "checkpoint": "juggernautXL_v9.safetensors",
    "controlnet": "controlnet-union-sdxl-promax.safetensors",
    "upscaler": "4x-UltraSharp.pth",
    "loras": [], "width": 1248, "height": 912,
}

# ControlNet Union (promax) wants to be told which control it is being fed
UNION_TYPE = {"canny": "canny/lineart/anime_lineart/mlsd", "lineart": "canny/lineart/anime_lineart/mlsd", "depth": "depth"}


def preprocessor(control, src):
    """The node that turns the art into a control image; core Canny needs no extra pack."""
    if control == "canny":
        return {"class_type": "Canny", "inputs": {"image": src, "low_threshold": 0.15, "high_threshold": 0.4}}
    if control == "lineart":
        return {"class_type": "LineArtPreprocessor", "inputs": {"image": src, "coarse": "disable", "resolution": 1024}}
    if control == "depth":
        return {"class_type": "DepthAnythingV2Preprocessor",
                "inputs": {"image": src, "ckpt_name": "depth_anything_v2_vitl.pth", "resolution": 1024}}
    raise SetError(f"unknown control {control!r}")


def workflow(image_name, s, prefix, upscale=True):
    w = {
        "1": {"class_type": "LoadImage", "inputs": {"image": image_name}},
        "2": {"class_type": "ImageScale", "inputs": {"image": ["1", 0], "upscale_method": "lanczos",
                                                     "width": s["width"], "height": s["height"], "crop": "center"}},
        "3": preprocessor(s["control"], ["2", 0]),
        "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": s["checkpoint"]}},
    }
    model, clip = ["4", 0], ["4", 1]
    for i, lora in enumerate(s["loras"]):
        nid = f"lora{i}"
        w[nid] = {"class_type": "LoraLoader", "inputs": {"model": model, "clip": clip, "lora_name": lora["name"],
                                                          "strength_model": lora.get("strength", 0.7),
                                                          "strength_clip": lora.get("strength", 0.7)}}
        model, clip = [nid, 0], [nid, 1]
    w.update({
        "7": {"class_type": "CLIPTextEncode", "inputs": {"clip": clip, "text": s["prompt"]}},
        "8": {"class_type": "CLIPTextEncode", "inputs": {"clip": clip, "text": s["negative"]}},
        "9": {"class_type": "ControlNetLoader", "inputs": {"control_net_name": s["controlnet"]}},
        "10": {"class_type": "SetUnionControlNetType", "inputs": {"control_net": ["9", 0], "type": UNION_TYPE[s["control"]]}},
        "11": {"class_type": "ControlNetApplyAdvanced", "inputs": {
            "positive": ["7", 0], "negative": ["8", 0], "control_net": ["10", 0], "image": ["3", 0],
            "strength": s["control_strength"], "start_percent": 0.0, "end_percent": s["control_end"], "vae": ["4", 2]}},
        "12": {"class_type": "VAEEncode", "inputs": {"pixels": ["2", 0], "vae": ["4", 2]}},
        "13": {"class_type": "KSampler", "inputs": {
            "model": model, "positive": ["11", 0], "negative": ["11", 1], "latent_image": ["12", 0],
            "seed": s["seed"], "steps": s["steps"], "cfg": s["cfg"], "sampler_name": s["sampler"],
            "scheduler": s["scheduler"], "denoise": s["denoise"]}},
        "14": {"class_type": "VAEDecode", "inputs": {"samples": ["13", 0], "vae": ["4", 2]}},
    })
    final = ["14", 0]
    if upscale:
        w["15"] = {"class_type": "UpscaleModelLoader", "inputs": {"model_name": s["upscaler"]}}
        w["16"] = {"class_type": "ImageUpscaleWithModel", "inputs": {"upscale_model": ["15", 0], "image": final}}
        w["17"] = {"class_type": "ImageScaleBy", "inputs": {"image": ["16", 0], "upscale_method": "lanczos", "scale_by": 0.5}}
        final = ["17", 0]
    w["18"] = {"class_type": "SaveImage", "inputs": {"images": final, "filename_prefix": prefix}}
    return w


def restyle_file(server, src, dest, style, prefix="tcg-mint/restyle", upscale=True):
    """Run the style workflow on any image file into dest."""
    src = str(src)
    if style.get("grayscale_source"):
        # monochrome styles: the starting latent keeps (1 - denoise) of the source,
        # and that residue is where stray colour comes from -- remove it at the source
        from PIL import Image
        gray = os.path.join(tempfile.gettempdir(), os.path.basename(src) + ".gray.png")
        Image.open(src).convert("L").convert("RGB").save(gray)
        src = gray
    name = server.upload(src)
    return server.run_to_file(workflow(name, style, prefix, upscale), str(dest), timeout=900)


def restyle(server, art, card, style, force=False, upscale=True):
    dest = art.styled(card, style["name"])
    if dest.exists() and not force:
        return dest, False
    restyle_file(server, art.crop(card), dest, style, "tcg-mint/" + card["illustration_id"] + "." + style["name"], upscale)
    return dest, True


def load_style(st):
    if "style" not in st:
        raise SetError("this set has no `style` block")
    s = {**DEFAULTS, **st["style"]}
    for k in ("name", "prompt"):
        if k not in s:
            raise SetError(f"style block needs a `{k}`")
    return s


def card_style(style, ov, i):
    """The effective recipe for one card: its own seed off the set's, and its `subject`
    ("a gaunt long-haired man in black armour at a workbench") ahead of the prompt so
    the style can't drift it into something else."""
    s = {**style, "seed": style["seed"] * 1000 + i}
    if ov.get("subject"):
        s["prompt"] = f"{ov['subject']}, {s['prompt']}"
    return s


def main(argv=None):
    ap = argparse.ArgumentParser(prog="mint restyle", description=__doc__.split("\n\n")[0])
    ap.add_argument("names", nargs="*")
    ap.add_argument("--set", required=True)
    ap.add_argument("--force", action="store_true", help="regenerate cards that already have this style")
    ap.add_argument("--no-upscale", action="store_true", help="skip the ESRGAN pass (faster proofs)")
    a = ap.parse_args(argv)
    ws = workspace.default()
    try:
        st, _ = sets.load(a.set)
        style = load_style(st)
        names = a.names or list(st.get("cards", {}))
        if not names:
            ap.error("the set has no cards")
        server = comfy.Comfy(ws.comfy_url)
        server.require()
        cards, art = Cards(ws.cards_file), Art(ws.art)
        for i, name in enumerate(names):
            ov = sets.overrides(st, {"name": name})
            card = cards.find(name, ov.get("printing"))
            dest, did = restyle(server, art, card, card_style(style, ov, i), a.force, not a.no_upscale)
            print(f"{'restyled' if did else 'cached  '} {card['name']} -> {os.path.relpath(dest)}")
    except MintError as e:
        sys.exit(str(e))


if __name__ == "__main__":
    main()

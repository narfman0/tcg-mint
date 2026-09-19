"""Regenerate card art in a set's style through ComfyUI.

    mint restyle --set sets/satoru.json [--force] [--no-upscale] ["Card Name" ...]

img2img with structure control: a ControlNet fed from the original art
(canny / lineart / depth) keeps the composition while the prompt -- and any
LoRAs -- decide how it's drawn. The whole recipe is the set file's `style`
block, so a set's look is reproducible:

    "style": {
      "name": "neon",                       -> art/<illustration_id>/neon-<recipe hash>.png
      "prompt": "...", "negative": "...",
      "control": "canny",                   canny | lineart | depth | openpose
      "control_strength": 0.8,
      "denoise": 0.85, "steps": 28, "cfg": 6, "seed": 7,
      "checkpoint": "juggernautXL_v9.safetensors",
      "clip_skip": 2,                       Pony-family checkpoints want 2; default 1
      "remix": "restyle",                   restyle | repose | new (below); a card entry can override
      "repose_strength": 0.5, "repose_end": 0.3,   repose's own control hold (below)
      "refine": 0.4, "refine_scale": 1.5,   second pass at 1.5x size, denoise 0.4: detail; default off
      "loras": [{"name": "x.safetensors", "strength": 0.7}],
      "width": 1248, "height": 912          generation size (art window is 1.42:1)
    }

A card entry may add `"subject": "..."` -- what the picture is of -- which is
prepended to the prompt so the style can't drift a character into someone else,
and `"base": "<variant hash>"` to start from an enhanced or earlier restyled
image instead of Scryfall's crop. The set's own `"base": "spore"` does that
for every card at once, by label: each card starts from its newest spore
variant, so one style can be remixed through another. The effective recipe (sets.SetFile.recipe)
is hashed into the output name, so every change to it is a new variant and
the old ones stay for comparison.

`remix` is what the result keeps of the picture it starts from -- three modes:

    restyle  img2img from the base with the ControlNet: same picture, redrawn
    repose   an empty latent and an OpenPose skeleton (DWPose) read from the
             card's `pose` image -- else its base -- held at repose_strength
             until repose_end of the steps; the prompt and subject line are
             the rest. Only the joints are kept: body, clothes, hair and
             background are new, and a different pose image moves the joints.
             (A canny / lineart / depth map *is* the pose, whatever the
             strength, which is why restyle never moves her.)
    new      an empty latent and the prompt alone -- no base image at all.
             The card's subject line is the only thread back to the original;
             without one the card's name and type line stand in for it.

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

# ControlNet Union (promax) wants to be told which control it is being fed
UNION_TYPE = {"canny": "canny/lineart/anime_lineart/mlsd", "lineart": "canny/lineart/anime_lineart/mlsd", "depth": "depth",
              "openpose": "openpose"}


def preprocessor(control, src):
    """The node that turns the art into a control image; core Canny needs no extra pack."""
    if control == "canny":
        return {"class_type": "Canny", "inputs": {"image": src, "low_threshold": 0.15, "high_threshold": 0.4}}
    if control == "lineart":
        return {"class_type": "LineArtPreprocessor", "inputs": {"image": src, "coarse": "disable", "resolution": 1024}}
    if control == "depth":
        return {"class_type": "DepthAnythingV2Preprocessor",
                "inputs": {"image": src, "ckpt_name": "depth_anything_v2_vitl.pth", "resolution": 1024}}
    if control == "openpose":  # body, hands and face keypoints; the pack fetches its models on first use
        return {"class_type": "DWPreprocessor",
                "inputs": {"image": src, "detect_hand": "enable", "detect_body": "enable", "detect_face": "enable",
                           "resolution": 1024, "bbox_detector": "yolox_l.onnx",
                           "pose_estimator": "dw-ll_ucoco_384_bs5.torchscript.pt"}}
    raise SetError(f"unknown control {control!r}")


def workflow(image_name, s, prefix, upscale=True):
    remix = s.get("remix", "restyle")
    w = {"4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": s["checkpoint"]}}}
    if remix != "new":
        w.update({
            "1": {"class_type": "LoadImage", "inputs": {"image": image_name}},
            "2": {"class_type": "ImageScale", "inputs": {"image": ["1", 0], "upscale_method": "lanczos",
                                                         "width": s["width"], "height": s["height"], "crop": "center"}},
            "3": preprocessor(s["control"], ["2", 0]),
        })
    model, clip = ["4", 0], ["4", 1]
    for i, lora in enumerate(s["loras"]):
        nid = f"lora{i}"
        w[nid] = {"class_type": "LoraLoader", "inputs": {"model": model, "clip": clip, "lora_name": lora["name"],
                                                          "strength_model": lora.get("strength", 0.7),
                                                          "strength_clip": lora.get("strength", 0.7)}}
        model, clip = [nid, 0], [nid, 1]
    if s.get("clip_skip", 1) > 1:
        w["5"] = {"class_type": "CLIPSetLastLayer", "inputs": {"clip": clip, "stop_at_clip_layer": -s["clip_skip"]}}
        clip = ["5", 0]
    w.update({
        "7": {"class_type": "CLIPTextEncode", "inputs": {"clip": clip, "text": s["prompt"]}},
        "8": {"class_type": "CLIPTextEncode", "inputs": {"clip": clip, "text": s["negative"]}},
    })
    positive, negative = ["7", 0], ["8", 0]
    if remix != "new":
        # repose holds the layout lightly and lets go early (recipes from before the knobs fall back)
        strength, end = ((s.get("repose_strength", s["control_strength"]), s.get("repose_end", s["control_end"]))
                         if remix == "repose" else (s["control_strength"], s["control_end"]))
        w.update({
            "9": {"class_type": "ControlNetLoader", "inputs": {"control_net_name": s["controlnet"]}},
            "10": {"class_type": "SetUnionControlNetType", "inputs": {"control_net": ["9", 0], "type": UNION_TYPE[s["control"]]}},
            "11": {"class_type": "ControlNetApplyAdvanced", "inputs": {
                "positive": ["7", 0], "negative": ["8", 0], "control_net": ["10", 0], "image": ["3", 0],
                "strength": strength, "start_percent": 0.0, "end_percent": end, "vae": ["4", 2]}},
        })
        positive, negative = ["11", 0], ["11", 1]
    if remix == "restyle":
        w["12"] = {"class_type": "VAEEncode", "inputs": {"pixels": ["2", 0], "vae": ["4", 2]}}
        denoise = s["denoise"]
    else:  # a fresh picture: nothing of the base's pixels survives, only (repose) its structure
        w["12"] = {"class_type": "EmptyLatentImage", "inputs": {"width": s["width"], "height": s["height"], "batch_size": 1}}
        denoise = 1.0
    w.update({
        "13": {"class_type": "KSampler", "inputs": {
            "model": model, "positive": positive, "negative": negative, "latent_image": ["12", 0],
            "seed": s["seed"], "steps": s["steps"], "cfg": s["cfg"], "sampler_name": s["sampler"],
            "scheduler": s["scheduler"], "denoise": denoise}},
        "14": {"class_type": "VAEDecode", "inputs": {"samples": ["13", 0], "vae": ["4", 2]}},
    })
    final = ["14", 0]
    if s.get("refine"):
        # hires pass: the first result, scaled up, sampled again lightly with the bare prompt (no
        # control -- the picture is already composed; this pass only draws it in finer)
        w["20"] = {"class_type": "ImageScaleBy",
                   "inputs": {"image": final, "upscale_method": "lanczos", "scale_by": s["refine_scale"]}}
        w["21"] = {"class_type": "VAEEncode", "inputs": {"pixels": ["20", 0], "vae": ["4", 2]}}
        w["22"] = {"class_type": "KSampler", "inputs": {
            "model": model, "positive": ["7", 0], "negative": ["8", 0], "latent_image": ["21", 0],
            "seed": s["seed"] + 1, "steps": s["steps"], "cfg": s["cfg"], "sampler_name": s["sampler"],
            "scheduler": s["scheduler"], "denoise": s["refine"]}}
        w["23"] = {"class_type": "VAEDecode", "inputs": {"samples": ["22", 0], "vae": ["4", 2]}}
        final = ["23", 0]
    if upscale:
        w["15"] = {"class_type": "UpscaleModelLoader", "inputs": {"model_name": s["upscaler"]}}
        w["16"] = {"class_type": "ImageUpscaleWithModel", "inputs": {"upscale_model": ["15", 0], "image": final}}
        w["17"] = {"class_type": "ImageScaleBy", "inputs": {"image": ["16", 0], "upscale_method": "lanczos", "scale_by": 0.5}}
        final = ["17", 0]
    w["18"] = {"class_type": "SaveImage", "inputs": {"images": final, "filename_prefix": prefix}}
    return w


def restyle_file(server, src, dest, recipe, prefix="tcg-mint/restyle", upscale=True):
    """Run the style workflow with an effective recipe (sets.SetFile.recipe) on any image file into dest."""
    if recipe.get("remix") == "new":  # nothing to read: the prompt is the whole input
        os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
        return server.run_to_file(workflow(None, recipe, prefix, upscale), str(dest), timeout=900)
    src = str(src)
    if recipe.get("grayscale_source"):
        # monochrome styles: the starting latent keeps (1 - denoise) of the source,
        # and that residue is where stray colour comes from -- remove it at the source
        from PIL import Image
        gray = os.path.join(tempfile.gettempdir(), os.path.basename(src) + ".gray.png")
        Image.open(src).convert("L").convert("RGB").save(gray)
        src = gray
    name = server.upload(src)
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    return server.run_to_file(workflow(name, recipe, prefix, upscale), str(dest), timeout=900)


def restyle(server, art, card, st, style=None, force=False, upscale=True, seed=None):
    """Make (or find) the variant of `card` for the set's style (or `style`, a sets.Style,
    to try a recipe that is not the set's). `seed` forces a one-off seed. Returns (Variant, made)."""
    style = style or st.style
    if style is None:
        raise SetError(f"{st.path or st.code} has no `style` block")
    recipe = st.recipe(card, style, art, seed=seed)
    h = sets.recipe_hash(recipe)
    if not force:
        v = art.variant(card, h)
        if v:
            return v, False
    v = art.new_variant(card, style.name, "restyle", recipe, recipe["base"], h)
    src = None if recipe["base"] == "none" else art.base_path(card, recipe["base"])
    restyle_file(server, src, v.path, recipe,
                 "tcg-mint/" + card["illustration_id"] + "." + style.name, upscale)
    return art.record(v), True


def main(argv=None):
    ap = argparse.ArgumentParser(prog="mint restyle", description=__doc__.split("\n\n")[0])
    ap.add_argument("names", nargs="*")
    ap.add_argument("--set", required=True)
    ap.add_argument("--force", action="store_true", help="regenerate cards that already have this style")
    ap.add_argument("--no-upscale", action="store_true", help="skip the ESRGAN pass (faster proofs)")
    a = ap.parse_args(argv)
    ws = workspace.default()
    try:
        st = sets.load(a.set)
        if st.style is None:
            raise SetError(f"{a.set} has no `style` block")
        names = a.names or st.names()
        if not names:
            ap.error("the set has no cards")
        server = comfy.Comfy(ws.comfy_url)
        server.require()
        cards, art = Cards(ws.cards_file), Art(ws.art)
        for name in names:
            card = cards.find(name, st.card({"name": name}).printing)
            v, made = restyle(server, art, card, st, force=a.force, upscale=not a.no_upscale)
            print(f"{'restyled' if made else 'cached  '} {card['name']} -> {os.path.relpath(v.path)}")
    except MintError as e:
        sys.exit(str(e))


if __name__ == "__main__":
    main()

# Standing this up on another machine

Three layers, and they reproduce very differently. The code is a clone away,
the weights are a long download, and your sets and styles are not in git at
all — read the last section first if you are moving machines rather than
adding one.

`mint doctor` is the check at the end of every step: it walks your sets and
templates, asks the running ComfyUI what it actually has, and names each
missing file. Run it early and often; it is the executable version of this
document.

## 1. The code

```sh
git clone git@github.com:narfman0/tcg-mint.git
cd tcg-mint
pip install -e '.[dev,web,fonts]'
playwright install chromium
mint cards                      # Scryfall's oracle-cards bulk file, ~630 MB, gitignored
```

If `playwright install` times out, the README's Install section has the
curl-and-unzip fallback. `pytest -m "not render"` and `pytest -m render`
should both pass before you go further.

## 2. Fonts

`fonts/README.md` is the whole story: four faces, where each is published,
the `sha256` of each source file, and why every one of them needs
`mint fonts --repair` unless it came from the pre-repaired fork. The frame
renders without them — the packaged open fallbacks ship in `mint/fonts/` —
so this step is optional if you only want to see it work.

`mint fonts` reports face by face. A family listed as `partial` is the one
failure that looks like success: the roman is there, the italic is not, and
the browser fakes the italic rather than falling back.

## 3. ComfyUI and the weights

Nothing here is bundled and nothing is small: about **43 GB** of weights,
plus **1.7 GB** the node packs fetch for themselves. Only `mint render`
works without it; `upscale`, `restyle`, `describe --generate` and `animate`
all need it.

```sh
git clone https://github.com/comfyanonymous/ComfyUI
cd ComfyUI
python -m venv .venv && .venv/bin/pip install -r requirements.txt
#   torch for your GPU first, if the default wheel is not the one you want

cd custom_nodes
git clone https://github.com/Fannovel16/comfyui_controlnet_aux
git clone https://github.com/cubiq/ComfyUI_IPAdapter_plus
cd .. && .venv/bin/pip install -r custom_nodes/comfyui_controlnet_aux/requirements.txt

.venv/bin/python main.py --listen 127.0.0.1 --port 8188
```

`COMFY_URL` (or `comfy_url` in `mint.toml`) points mint at a server
elsewhere.

### The model files

Each goes in the `models/` subdirectory named in the first column. Every URL
below was checked, and the three marked ✓ match this machine's copies
byte for byte.

| into `models/` | file | size | from |
|---|---|---|---|
| `checkpoints/` | `juggernautXL_v9.safetensors` | 6.7 GB | Civitai "Juggernaut XL", version **v9+RDPhoto2**. Civitai needs an account and an API token, so there is no stable direct URL |
| `checkpoints/` | `ponyDiffusionV6XL.safetensors` | 6.5 GB | Civitai "Pony Diffusion V6 XL". Wants `clip_skip: 2` — see `styles/nsfw.json` |
| `checkpoints/` | `animagine-xl-3.1.safetensors` | 6.5 GB | `cagliostrolab/animagine-xl-3.1` on HF, same filename |
| `controlnet/` | `controlnet-union-sdxl-promax.safetensors` | 2.4 GB | ✓ `xinsir/controlnet-union-sdxl-1.0` → `diffusion_pytorch_model_promax.safetensors`, **renamed** |
| `ipadapter/` | `ip-adapter-plus_sdxl_vit-h.safetensors` | 809 MB | ✓ `h94/IP-Adapter` → `sdxl_models/ip-adapter-plus_sdxl_vit-h.safetensors` |
| `clip_vision/` | `CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors` | 2.4 GB | ✓ `h94/IP-Adapter` → `models/image_encoder/model.safetensors`, **renamed** |
| `upscale_models/` | `4x-UltraSharp.pth` | 64 MB | `Kim2091/UltraSharp` on HF |
| `upscale_models/` | `RealESRGAN_x4plus.pth` | 64 MB | Real-ESRGAN release `v0.1.0` |
| `diffusion_models/` | `wan2.2_ti2v_5B_fp16.safetensors` | 9.4 GB | `Comfy-Org/Wan_2.2_ComfyUI_Repackaged` → `split_files/diffusion_models/` |
| `text_encoders/` | `umt5_xxl_fp8_e4m3fn_scaled.safetensors` | 6.3 GB | same repo → `split_files/text_encoders/` |
| `vae/` | `wan2.2_vae.safetensors` | 1.4 GB | same repo → `split_files/vae/` |

A Hugging Face file is fetched as
`https://huggingface.co/<repo>/resolve/main/<path>`; `mint doctor` prints
that URL in full for any Wan file it cannot find.

Only the checkpoints your own sets and templates name are actually required.
`mint doctor` tells you which, and which set or template asks for it — on
this machine that is Juggernaut for most, Pony for `MRN` and `nsfw`, and
Animagine for `woodblock`.

### The weights the node packs fetch themselves

`comfyui_controlnet_aux` downloads its preprocessor models on first use into
`custom_nodes/comfyui_controlnet_aux/ckpts/<hf repo>/`. **These cannot be
checked over HTTP**: unlike a checkpoint loader, the preprocessor nodes offer
every model they know how to download whether or not it is on disk, so
asking the server always answers yes.

| control | file | size | HF repo |
|---|---|---|---|
| depth | `depth_anything_v2_vitl.pth` | 1.3 GB | `depth-anything/Depth-Anything-V2-Large` |
| lineart | `sk_model.pth`, `sk_model2.pth` | 17 MB each | `lllyasviel/Annotators` |
| openpose / repose | `yolox_l.onnx` | 207 MB | `yzd-v/DWPose` |
| openpose / repose | `dw-ll_ucoco_384_bs5.torchscript.pt` | 129 MB | `hr16/DWPose-TorchScript-BatchSize5` |

Letting them download on demand is fine on a connected machine. To have
`mint doctor` verify them instead, tell it where the checkout is:

```toml
# mint.toml
comfy_root = "~/workspace/ComfyUI"
```

or `COMFY_ROOT` in the environment. Unset, doctor lists what will be fetched
rather than claiming to have checked it.

## 4. Check it

```sh
mint doctor
```

Everything above shows up as one line each. A missing checkpoint or node is
a failure; a substituted font, an ageing card file and an undownloaded
preprocessor weight are warnings, because a job can still finish.

## What is *not* in the repository

This is the part a fresh clone cannot give you. `.gitignore` excludes:

- **`sets/` and `styles/`** — every set file and style template. These are
  the actual work: prompts, seeds, checkpoints, LoRA weights, per-card
  overrides. They are what makes a look reproducible, and they exist only on
  the machine that made them.
- `fonts/` — refetchable, see `fonts/README.md`
- `oracle-cards.jsonl` — refetchable with `mint cards`
- `art/`, `symbols/`, `out/`, `.cache/` — caches. Regenerable, but `art/`
  holds every restyle, enhance and clip you have ever made, and regenerating
  it means re-running the GPU over all of it.

If you are moving to another machine rather than setting up a second one,
copy `sets/`, `styles/` and `art/` across by hand, or put the first two
under version control of their own. Nothing else in this document is hard to
repeat; those are.

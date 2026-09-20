"""Carry the base picture's colours onto a restyle: the fix for palette drift.

A faithful restyle (low denoise, the ControlNet held) keeps the drawing but
lets the colours wander -- a red seal goes brown, a bright hall goes grey.
Matching the result's channel statistics to the base's brings the palette
back without touching the drawing. It is Reinhard's transfer in YCbCr:
each channel's mean and spread are moved to the base's, then the corrected
image is blended with the original by the knob's strength.
"""
from PIL import Image, ImageStat


def _lut(src_mean, src_std, ref_mean, ref_std):
    scale = (ref_std / src_std) if src_std > 1e-3 else 1.0
    return [max(0, min(255, round((v - src_mean) * scale + ref_mean))) for v in range(256)]


def match(image, reference, strength=1.0):
    """The image with its YCbCr channel means and spreads moved to the reference's, blended in
    by `strength` (0 = the image untouched, 1 = fully matched). Both are PIL images or paths."""
    im = Image.open(image) if isinstance(image, str) or hasattr(image, "__fspath__") else image
    ref = Image.open(reference) if isinstance(reference, str) or hasattr(reference, "__fspath__") else reference
    src = im.convert("RGB").convert("YCbCr")
    tgt = ref.convert("RGB").resize(src.size).convert("YCbCr")
    s_stat, t_stat = ImageStat.Stat(src), ImageStat.Stat(tgt)
    channels = [c.point(_lut(s_stat.mean[i], s_stat.stddev[i], t_stat.mean[i], t_stat.stddev[i]))
                for i, c in enumerate(src.split())]
    matched = Image.merge("YCbCr", channels).convert("RGB")
    return Image.blend(im.convert("RGB"), matched, max(0.0, min(1.0, float(strength))))


def match_file(path, reference, strength=1.0):
    """Match the image at `path` to `reference` in place."""
    match(path, reference, strength).save(path)

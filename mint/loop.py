"""From a stack of frames to something that loops.

The frame operations are pure PIL; ffmpeg only ever encodes a numbered PNG
sequence. Three loop treatments:

    pingpong   frames, then the same frames backwards -- always seamless, breathing motion
    crossfade  the last N frames dissolve into the first N -- one direction, a soft join
    none       as generated
"""
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image

from .errors import MintError


def load_frames(directory):
    paths = sorted(Path(directory).glob("*.png"))
    if not paths:
        raise MintError(f"no frames in {directory}")
    return [Image.open(p).convert("RGB") for p in paths]


def pingpong(frames):
    """A -> B -> A without repeating the turnaround frames."""
    return list(frames) + list(frames[-2:0:-1])


def crossfade(frames, n):
    """Dissolve the last n frames into the first n; the result is len(frames) - n long."""
    if n <= 0:
        return list(frames)
    if 2 * n >= len(frames):
        raise MintError(f"crossfade of {n} needs more than {2 * n} frames, have {len(frames)}")
    head, body, tail = frames[:n], frames[n:len(frames) - n], frames[len(frames) - n:]
    blended = [Image.blend(t, h, (i + 1) / (n + 1)) for i, (t, h) in enumerate(zip(tail, head))]
    return body + blended


def looped(frames, mode, n=0):
    if mode == "pingpong":
        return pingpong(frames)
    if mode == "crossfade":
        return crossfade(frames, n)
    if mode == "none":
        return list(frames)
    raise MintError(f"unknown loop mode {mode!r}")


# --- encoding ------------------------------------------------------------------

def encode_args(pattern, dest, fps, fmt, gif_width=0):
    """The ffmpeg argv for a numbered PNG sequence -> one looping file."""
    even = "scale=trunc(iw/2)*2:trunc(ih/2)*2"
    base = ["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(fps), "-i", pattern]
    if fmt == "webm":
        return base + ["-vf", even, "-c:v", "libvpx-vp9", "-pix_fmt", "yuv420p", "-b:v", "0", "-crf", "30", "-an", dest]
    if fmt == "mp4":
        return base + ["-vf", even, "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", "-movflags", "+faststart",
                       "-an", dest]
    if fmt == "gif":
        scale = f"scale={gif_width}:-1:flags=lanczos," if gif_width else ""
        vf = (f"{scale}split[a][b];[a]palettegen=stats_mode=diff[p];"
              "[b][p]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle")
        return base + ["-vf", vf, "-loop", "0", dest]
    if fmt == "apng":
        return base + ["-c:v", "apng", "-plays", "0", dest]
    raise MintError(f"unknown format {fmt!r}")


def have_ffmpeg():
    return bool(shutil.which("ffmpeg"))


def encode(frames, dest, fps, fmt, gif_width=0):
    if not have_ffmpeg():
        raise MintError("ffmpeg is not on PATH; animate needs it to encode the clip")
    with tempfile.TemporaryDirectory() as d:
        for i, f in enumerate(frames):
            f.save(os.path.join(d, f"{i:04d}.png"))
        os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
        args = encode_args(os.path.join(d, "%04d.png"), str(dest), fps, fmt, gif_width)
        proc = subprocess.run(args, capture_output=True, text=True)
        if proc.returncode:
            raise MintError(f"ffmpeg failed for {dest}: {proc.stderr.strip()}")
    return dest

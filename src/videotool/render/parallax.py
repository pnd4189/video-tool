"""Depth-based 2.5D parallax: turn a still into a subtly moving clip.

Optional feature (``enhance.parallax``). Estimates a depth map with DepthAnything V2
then warps the image per-frame so near pixels drift more than far ones — giving the
"living photo" depth the flat zoompan Ken Burns lacks. Runs offline on CPU; torch +
transformers ship only with the ``parallax`` extra, so every import is lazy and a
missing extra raises a clear message instead of an ImportError at startup.
"""
from __future__ import annotations

import hashlib
import math
import os
import subprocess
from dataclasses import replace
from pathlib import Path

from videotool.core.errors import DependencyError
from videotool.render.video_filters import is_image

PARALLAX_MISSING_MSG = (
    "enhance.parallax needs extra dependencies. Install them with: "
    "pip install -e '.[parallax]'  (torch + transformers + pillow + numpy)."
)

# POC-verified defaults. parallax_px stays modest so disocclusion stretch at depth edges
# is hidden by the zoom crop; depth runs on a downscaled copy because full-res monocular
# depth is needlessly slow on CPU (4K ~83s vs 1280px ~0.7s) for no visible gain at 1080p.
PARALLAX_PX = 45.0
ZOOM = 1.06
DEPTH_MAX_SIDE = 1280
_DEPTH_MODEL = "depth-anything/Depth-Anything-V2-Small-hf"

_pipe = None


def parallax_available() -> bool:
    """True when the parallax extra is importable (torch/transformers/numpy/PIL)."""
    try:
        import numpy  # noqa: F401
        import torch  # noqa: F401
        import transformers  # noqa: F401
        from PIL import Image  # noqa: F401
        return True
    except Exception:
        return False


def _make_pipeline(device: int, *, offline: bool):
    from transformers import AutoImageProcessor, AutoModelForDepthEstimation, pipeline

    # local_files_only avoids the HF Hub round-trips transformers makes on every build, which
    # stall ~80s on a throttled/unauthenticated connection even though the model is tiny and
    # already cached. First run (cache miss) retries online to download it once.
    model = AutoModelForDepthEstimation.from_pretrained(_DEPTH_MODEL, local_files_only=offline)
    proc = AutoImageProcessor.from_pretrained(_DEPTH_MODEL, local_files_only=offline)
    return pipeline("depth-estimation", model=model, image_processor=proc, device=device)


def _depth_pipeline():
    global _pipe
    if _pipe is None:
        import torch

        torch.set_num_threads(max(1, os.cpu_count() or 4))
        device = 0 if torch.cuda.is_available() else -1
        try:
            _pipe = _make_pipeline(device, offline=True)
        except Exception:
            _pipe = _make_pipeline(device, offline=False)  # first run: download once
    return _pipe


def _fit_crop(im, w: int, h: int):
    from PIL import Image

    iw, ih = im.size
    scale = max(w / iw, h / ih)
    im = im.resize((round(iw * scale), round(ih * scale)), Image.LANCZOS)
    iw, ih = im.size
    left, top = (iw - w) // 2, (ih - h) // 2
    return im.crop((left, top, left + w, top + h))


def _estimate_depth(pil_img, w: int, h: int):
    """Depth at WxH, 0..1 (1 = nearest). Depth is estimated on a downscaled copy for speed."""
    import numpy as np
    from PIL import Image

    small = pil_img.copy()
    small.thumbnail((DEPTH_MAX_SIDE, DEPTH_MAX_SIDE), Image.LANCZOS)
    depth = _depth_pipeline()(small)["depth"]
    depth = _fit_crop(depth.convert("L"), w, h)
    arr = np.asarray(depth, dtype=np.float32)
    return (arr - arr.min()) / (arr.max() - arr.min() + 1e-6)


def render_parallax_clip(
    image_path: Path,
    duration: float,
    fps: int,
    width: int,
    height: int,
    out_path: Path,
    *,
    parallax_px: float = PARALLAX_PX,
    zoom: float = ZOOM,
) -> Path:
    """Render one orbit-parallax clip from a still. Clip is rendered a hair longer than
    ``duration`` so the scene_filter trim never runs short (which would freeze the tail)."""
    import numpy as np
    from PIL import Image

    # Warp uses numpy inverse-mapping (clamped nearest), not torch grid_sample: on CPU the
    # vectorized numpy indexing is ~30 fps @1080p while CPU grid_sample is ~1 fps. Depth still
    # runs through torch/transformers (cheap, one-shot). Edge clamp + zoom hide disocclusion.
    pil = Image.open(image_path).convert("RGB")
    img = np.array(_fit_crop(pil, width, height))            # HxWx3 uint8
    dep = _estimate_depth(pil, width, height)                # HxW float 0..1 (1=near)
    ys, xs = np.mgrid[0:height, 0:width].astype(np.float32)
    cx, cy = width / 2.0, height / 2.0
    px_x, px_y = parallax_px, parallax_px * 0.5

    out_path.parent.mkdir(parents=True, exist_ok=True)
    ff = subprocess.Popen(
        [
            "ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
            "-s", f"{width}x{height}", "-r", str(fps), "-i", "-", "-an",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
            str(out_path),
        ],
        stdin=subprocess.PIPE,
    )
    n = max(1, int(math.ceil(duration * fps)) + 2)
    try:
        for i in range(n):
            ph = 2 * math.pi * i / n
            ox, oy = math.sin(ph) * px_x, math.cos(ph) * px_y      # orbit camera
            sx = cx + (xs - cx) / zoom + ox * dep
            sy = cy + (ys - cy) / zoom + oy * dep
            sx = np.clip(sx, 0, width - 1).astype(np.int32)
            sy = np.clip(sy, 0, height - 1).astype(np.int32)
            ff.stdin.write(img[sy, sx].tobytes())
    finally:
        ff.stdin.close()
        ff.wait()
    if ff.returncode != 0:
        raise RuntimeError(f"ffmpeg failed encoding parallax clip for {image_path}")
    return out_path


def _clip_path(cache_dir: Path, image_path: Path, duration: float, preset) -> Path:
    # Key assumes the module-default motion params; the standalone CLI command (which can
    # override them) bypasses this cache. Model id is included so swapping it invalidates clips.
    key = f"{image_path}|{image_path.stat().st_size}|{image_path.stat().st_mtime_ns}|" \
          f"{preset.width}x{preset.height}@{preset.fps}|{duration:.2f}|{PARALLAX_PX}|{ZOOM}|{_DEPTH_MODEL}"
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]
    return cache_dir / f"{image_path.stem}-{digest}.mp4"


def parallaxize_timeline(timeline, cache_dir: Path, preset):
    """Replace each still scene with a cached depth-parallax clip (rendered at ``preset``
    resolution/fps). A scene that fails depth/render keeps its original still + zoompan so
    one bad image can never break the whole render."""
    if not parallax_available():
        # DependencyError so the `render` CLI surfaces a clean exit code, not a raw traceback.
        raise DependencyError(PARALLAX_MISSING_MSG)
    cache_dir.mkdir(parents=True, exist_ok=True)
    new_scenes = []
    for scene in timeline.scenes:
        if not is_image(scene.media_path):
            new_scenes.append(scene)
            continue
        try:
            clip = _clip_path(cache_dir, scene.media_path, scene.duration, preset)
            if not clip.exists():
                render_parallax_clip(
                    scene.media_path, scene.duration, preset.fps,
                    preset.width, preset.height, clip,
                )
            new_scenes.append(replace(scene, media_path=clip, motion="static"))
        except Exception as exc:  # depth/render failure -> fall back to Ken Burns still
            print(f"[parallax] scene {scene.scene} fell back to Ken Burns: {exc}")
            new_scenes.append(scene)
    return replace(timeline, scenes=new_scenes)

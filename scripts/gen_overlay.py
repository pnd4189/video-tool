#!/usr/bin/env python3
"""Offline generator for atmosphere overlay clips (fireflies / embers / dust).

These overlays feed the render pipeline's ``enhance.atmosphere`` slot
(``inputs.particle_overlay``). The pipeline screen-blends them in RGB over black,
so an overlay must be: pure-black background, bright elements only, and a SEAMLESS
loop (the pipeline ``-stream_loop -1`` repeats it for the whole video).

This is an offline asset-authoring tool — it is NOT imported by the render pipeline.
Run it once, drop the mp4 into ~/.local/share/videotool/overlays/, and the pipeline
consumes it like any other CC0 clip.

The ffmpeg raw-frame pipe mirrors src/videotool/render/parallax.py: numpy builds each
frame as rgb24 bytes and writes them straight into a libx264 encoder.

Seamless loop: every motion is a function of the loop phase ``t = frame / N`` built from
periodic terms, so frame(t=0) is identical to frame(t=1). Wandering particles use integer
sine harmonics; lifecycle particles (embers) advance a wrapping phase and fade to zero at
both ends, so the wrap is invisible.

Usage:
    scripts/gen_overlay.py --preset fireflies            # -> overlays/fireflies-gen-01.mp4
    scripts/gen_overlay.py --preset fireflies --id 02 --seconds 20 --out /tmp/test.mp4
"""
from __future__ import annotations

import argparse
import math
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

LIBRARY_DIR = Path.home() / ".local/share/videotool/overlays"


@dataclass(frozen=True)
class Preset:
    """Parameters for one overlay look. One engine, many presets (DRY)."""

    count: int                      # number of particles
    color: tuple[int, int, int]     # base RGB of the glow
    glow_sigma: float               # gaussian sprite radius (px)
    brightness: float               # peak additive brightness (0..255)
    # Wandering (non-lifecycle) params:
    drift_amp: tuple[float, float] = (40.0, 30.0)   # x/y wander amplitude (px)
    flicker_depth: float = 0.5      # 0 = steady, 1 = fully pulsing
    # Lifecycle (embers) params:
    lifecycle: bool = False         # spawn -> rise -> fade, wrapping phase
    rise_px: float = 400.0          # vertical travel over one life
    sway_px: float = 12.0           # lateral sway amplitude over one life


PRESETS: dict[str, Preset] = {
    # Sparse warm yellow-green dots, gentle wander + soft pulse — rural summer night.
    # brightness > 255 so the tight core clips to a crisp yellow-green point on peak twinkle.
    "fireflies": Preset(
        count=80,
        color=(206, 224, 110),
        glow_sigma=4.5,
        brightness=330.0,
        drift_amp=(42.0, 30.0),
        flicker_depth=0.6,
    ),
    # Orange-red talisman sparks: spawn, rise, fade. Lifecycle path (wrapping phase).
    "ember": Preset(
        count=110,
        color=(255, 120, 42),
        glow_sigma=3.0,
        brightness=330.0,
        flicker_depth=0.0,
        lifecycle=True,
        rise_px=430.0,
        sway_px=14.0,
    ),
    # Pale, near-still motes — "suspended unnaturally still" abandoned interior. Small tight
    # specks (low sigma) so they read as sharp in-focus dust, not dim fuzz.
    "dust": Preset(
        count=190,
        color=(202, 202, 208),
        glow_sigma=2.2,
        brightness=190.0,
        drift_amp=(8.0, 8.0),
        flicker_depth=0.15,
    ),
}


def glow_sprite(sigma: float) -> np.ndarray:
    """Core+halo profile (peak 1.0): a tight bright core spike (sharp point) plus a soft wide
    halo (glow). A pure gaussian has no crisp center and reads as a fuzzy blob; the core term
    is what makes each particle a sharp dot on black. With a >255 brightness the core clips to
    a hot point while the halo stays a soft surround — the high core/halo contrast survives
    H264 far better than a flat gaussian."""
    radius = max(2, int(math.ceil(3.0 * sigma)))
    ax = np.arange(-radius, radius + 1, dtype=np.float32)
    r2 = ax[:, None] ** 2 + ax[None, :] ** 2
    halo = np.exp(-r2 / (2.0 * sigma * sigma))
    # Core ~3-4px wide (not a 1px spike): a 1px core is the highest spatial frequency and H264
    # destroys it on the first encode — and the pipeline re-encodes the whole video again. A few
    # px of over-saturated core clips to a flat bright disc that survives BOTH encodes and still
    # reads as a sharp dot.
    core_sigma = max(1.8, sigma * 0.38)
    core = np.exp(-r2 / (2.0 * core_sigma * core_sigma))
    sprite = 0.4 * halo + 0.6 * core
    return (sprite / sprite.max()).astype(np.float32)


@dataclass
class _Field:
    """Vectorized per-particle state, seeded once and reused across frames."""

    base_x: np.ndarray
    base_y: np.ndarray
    phase0: np.ndarray              # lifecycle/flicker phase offset
    freq_x: np.ndarray             # integer harmonic -> periodic over t in [0,1]
    freq_y: np.ndarray
    phi_x: np.ndarray
    phi_y: np.ndarray
    flick_freq: np.ndarray
    flick_phi: np.ndarray
    color: np.ndarray              # (count, 3) float32, per-particle jittered
    extra: dict = field(default_factory=dict)


def _make_field(preset: Preset, width: int, height: int, rng: np.random.Generator) -> _Field:
    n = preset.count
    base_color = np.array(preset.color, dtype=np.float32)
    jitter = rng.uniform(0.82, 1.0, size=(n, 1)).astype(np.float32)
    return _Field(
        base_x=rng.uniform(0, width, size=n).astype(np.float32),
        base_y=rng.uniform(0, height, size=n).astype(np.float32),
        phase0=rng.uniform(0.0, 1.0, size=n).astype(np.float32),
        freq_x=rng.integers(1, 4, size=n).astype(np.float32),
        freq_y=rng.integers(1, 4, size=n).astype(np.float32),
        phi_x=rng.uniform(0, 2 * math.pi, size=n).astype(np.float32),
        phi_y=rng.uniform(0, 2 * math.pi, size=n).astype(np.float32),
        flick_freq=rng.integers(1, 4, size=n).astype(np.float32),
        flick_phi=rng.uniform(0, 2 * math.pi, size=n).astype(np.float32),
        color=np.clip(base_color[None, :] * jitter, 0, 255),
    )


def _positions_brightness(
    preset: Preset, fld: _Field, t: float, width: int, height: int
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return (x, y, brightness_scale) arrays for loop phase t in [0,1)."""
    tau = 2.0 * math.pi * t
    if preset.lifecycle:
        ph = np.mod(fld.phase0 + t, 1.0)                       # 0..1 over one life
        x = fld.base_x + preset.sway_px * np.sin(2 * math.pi * ph)
        y = fld.base_y - preset.rise_px * ph                  # rise upward
        bright = np.sin(math.pi * ph)                          # 0 at birth and death
    else:
        x = fld.base_x + preset.drift_amp[0] * np.sin(fld.freq_x * tau + fld.phi_x)
        y = fld.base_y + preset.drift_amp[1] * np.sin(fld.freq_y * tau + fld.phi_y)
        twinkle = 0.5 + 0.5 * np.sin(fld.flick_freq * tau + fld.flick_phi)
        bright = (1.0 - preset.flicker_depth) + preset.flicker_depth * twinkle
    return x, y, bright.astype(np.float32)


def render_frame(
    preset: Preset, fld: _Field, sprite: np.ndarray, t: float, width: int, height: int
) -> np.ndarray:
    """Pure function: build one rgb24 frame for loop phase t. Black bg + additive splats."""
    buf = np.zeros((height, width, 3), dtype=np.float32)
    r = sprite.shape[0] // 2
    x, y, bright = _positions_brightness(preset, fld, t, width, height)
    for i in range(preset.count):
        cx, cy = int(round(x[i])), int(round(y[i]))
        x0, x1 = cx - r, cx + r + 1
        y0, y1 = cy - r, cy + r + 1
        # Clip the splat to the frame; skip if fully outside.
        sx0, sy0 = max(0, -x0), max(0, -y0)
        x0c, y0c = max(0, x0), max(0, y0)
        x1c, y1c = min(width, x1), min(height, y1)
        if x1c <= x0c or y1c <= y0c:
            continue
        k = sprite[sy0 : sy0 + (y1c - y0c), sx0 : sx0 + (x1c - x0c)]
        contrib = k[:, :, None] * fld.color[i][None, None, :] * (bright[i] * preset.brightness / 255.0)
        buf[y0c:y1c, x0c:x1c] += contrib
    return np.clip(buf, 0, 255).astype(np.uint8)


def generate(
    preset_name: str, out_path: Path, *, seconds: float, fps: int, width: int, height: int, seed: int
) -> Path:
    if preset_name not in PRESETS:
        raise SystemExit(f"unknown preset '{preset_name}'. Available: {', '.join(PRESETS)}")
    preset = PRESETS[preset_name]
    rng = np.random.default_rng(seed)
    fld = _make_field(preset, width, height, rng)
    sprite = glow_sprite(preset.glow_sigma)
    total = max(2, int(round(seconds * fps)))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    ff = subprocess.Popen(
        [
            "ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
            "-s", f"{width}x{height}", "-r", str(fps), "-i", "-", "-an",
            # crf 16 + slow keeps the tiny bright cores; deblock=-1,-1 stops x264 from softening
            # the sharp dot edges (safe here — flat black bg has no blocking to hide).
            "-c:v", "libx264", "-preset", "slow", "-crf", "12",
            "-x264-params", "deblock=-1,-1",
            "-pix_fmt", "yuv420p",
            str(out_path),
        ],
        stdin=subprocess.PIPE,
    )
    try:
        for i in range(total):
            frame = render_frame(preset, fld, sprite, i / total, width, height)
            ff.stdin.write(frame.tobytes())
    finally:
        ff.stdin.close()
        ff.wait()
    if ff.returncode != 0:
        raise RuntimeError(f"ffmpeg failed encoding overlay {out_path}")
    return out_path


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Generate a seamless atmosphere overlay clip.")
    p.add_argument("--preset", required=True, choices=sorted(PRESETS), help="overlay look")
    p.add_argument("--id", default="01", help="numeric id suffix (default 01)")
    p.add_argument("--out", type=Path, default=None, help="output path (default: library/<kind>-gen-<id>.mp4)")
    p.add_argument("--seconds", type=float, default=18.0)
    p.add_argument("--fps", type=int, default=30)
    p.add_argument("--width", type=int, default=1920)
    p.add_argument("--height", type=int, default=1080)
    p.add_argument("--seed", type=int, default=7)
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    out = args.out or (LIBRARY_DIR / f"{args.preset}-gen-{args.id}.mp4")
    path = generate(
        args.preset, out,
        seconds=args.seconds, fps=args.fps, width=args.width, height=args.height, seed=args.seed,
    )
    print(f"wrote {path}")


if __name__ == "__main__":
    main()

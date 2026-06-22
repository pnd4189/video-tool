# Atmosphere Overlay Generators: Local + Colab Split

**Date**: 2026-06-21 18:45
**Severity**: Medium
**Component**: Overlay FX system, generator scripts
**Status**: Resolved (GPU validation pending)

## What Happened

Shipped a custom overlay generator system to fill gaps in the fixed CC0 library. User wanted fireflies (đom đóm), embers (tàn lửa bùa), dust motes, and qi-wisps (linh khí) for moods the existing library didn't cover well. Split the work pragmatically: numpy CPU generators locally (fireflies/ember/dust — instant, pure asset authoring, no pipeline integration) + GLSL on Colab/Kaggle GPU (qi-wisps — flow-field effect where GPU matters).

## The Brutal Truth

I initially pushed back hard on Remotion/Three.js/Hyperframe, partly out of "let's use the real tools" instinct, partly because I didn't want to deal with Colab complexity. Turns out that was the wrong battle. The real reason Remotion fails on Colab is SwiftShader fallback (headless WebGL on CPU, not the GPU you paid for), which kills frame quality and speed. The solution wasn't to kill GPU work entirely — it was to use proper headless rendering (moderngl+EGL on Nvidia ICD) for effects where GPU matters, and keep the cheap stuff (sprites) local in numpy. Took a day of argument to get there, but the split is clean now.

## Technical Details

**scripts/gen_overlay.py** (local, committed):
- Three presets: `fireflies` (small gaussian-sprite additive particles, wandering path), `ember` (hot-core particles, radial falloff), `dust` (faint dense motes, larger radius)
- Output: 1920x1080 H.264 yuv420p, 18s seamless loop, black background
- Reuses ffmpeg-pipe pattern from `src/videotool/render/parallax.py` (no subprocess spawn overhead)
- Tests: seam continuity (frame t=0 equals t=1080) + black-density assertions per preset
- Confirmed: test-first at 320x180 failed (density scaling), then passed at 1920x1080 shipping res

**Colab/qi_wisps_overlay_colab.py** (committed, GPU execution pending):
- GLSL fragment shader: 5-octave FBM value-noise, domain-warped by periodic flow field
- Seamless loop driven entirely by `cos(2π·t)` and `sin(2π·t)` domain warps (no frame lookup)
- Headless render via moderngl+EGL, reusing NVIDIA ICD trick from v4_depthflow
- Verified via static analysis only (py_compile, GLSL brace/paren balance, uniform cross-check)
- **NOT RENDERED YET** — no local GPU; user must run manually on Colab or Kaggle

## What We Tried

1. WebGL-based renderers (Remotion, Three.js): abandoned (SwiftShader trap on Colab/Kaggle)
2. Hyperframe (proprietary, no open Colab story): ruled out
3. Pure numpy for everything: tested, but qi-wisps needs GPU flow-field performance
4. Settled: numpy for sprites (instant), moderngl+EGL for shaders (GPU efficiency)

## Root Cause Analysis

The original argument loop happened because I conflated "it's not GPU-heavy" (true for sprites) with "don't use GPU at all" (wrong for domain-warped noise). User was right that qi-wisps needs GPU; I was right that fireflies don't. The compromise was the right call, but we wasted time debating extremes instead of finding the threshold.

## Lessons Learned

- GPU is not binary. Some effects get 10× cheaper with it (noise, flow fields), others get 0×. Profile before rejecting or assuming.
- Colab reliability ≠ quality. Headless EGL with explicit ICD setup beats "just try WebGL and hope."
- Commit the local stuff immediately (numpy generators are done), mark GPU work as "run manually" (honest about limitations).
- Tests at shipping resolution matter: density calculations fail at preview size because distribution changes.

## Next Steps

1. User runs Colab/qi_wisps_overlay_colab.py on Colab/Kaggle, downloads qi-gen-01.mp4.
2. Place at `~/.local/share/videotool/overlays/qi-gen-01.mp4`; /make-video then suggests it for mystical moods.
3. If GPU render fails, diagnostics: is EGL available? NVIDIA ICD installed? Fallback: ship a static qi-wisps loop as a fallback asset.
4. Extend mood map in AGENTS.md (rural-night→fireflies-gen, talisman-burning→ember-gen, etc.) — already done.

**Blocking**: GPU validation. Everything else unblocked.

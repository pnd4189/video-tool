# Colab DepthFlow 2.5D Parallax Path Shipped — Parallel Strategies Coexist

**Date**: 2026-06-18 19:30
**Severity**: Medium (feature-complete, POC unverified)
**Component**: Parallax 2.5D rendering, GPU offload, CLI (`parallax-link`, `/parallax-video`)
**Status**: Shipped, POC needs real-world Colab validation

## What Happened

Merged a second 2.5D parallax strategy to `feat/parallax-2-5d`, completely isolated from the existing local-numpy path:

1. **New `/parallax-video` command** — orchestrates the full pipeline: `make-video` flow + one inserted `videotool parallax-link` step.
2. **New `parallax-link` CLI** (`src/videotool/core/parallax_link.py`, 59 lines) — reads a job's storyboard, scans a `Parallax/` folder for pre-rendered `<image-stem>.mp4` clips, swaps matching image scenes to video scenes at the data layer (missing clips stay Ken Burns).
3. **New Colab script** (`Colab/v4_depthflow_clips_colab.py`, 118 lines) — GPU + DepthFlow renders one loopable ~1080p clip *per still image*, clips only (no splice, no audio). User manually downloads `Parallax/` folder from Drive, uploads beside the asset folder locally, runs `/parallax-video`.
4. **Render unchanged** — render already handles video scenes (loop + trim to duration), so zero render-code churn. Parallax motion is burned into the clip itself; local side just pipes it through.
5. **Suite: 149 passing** (up from 114 after full-tier overlays; all new tests in `test_parallax_link.py`).

## The Brutal Truth

Two separate parallax paths now live in the same codebase — and that's *intentional, not a mess*. This decision stings because it feels like we could merge them, but the trade-off is real:

- **Local (`enhance.parallax`)**: CPU-bound, Python ecosystem (DepthAnything V2 + numpy inverse-warp), runs during render, offline, no torch dependency after model cache. POC: validated on real scenes, depth prediction works, but numpy loop kills speed on >40 scenes (segmented path saves the day).
- **Colab (`/parallax-video`)**: GPU-bound, DepthFlow (faster depth + optical flow + warp), renders isolated clips upfront, manual transport, no local torch needed. POC: script written, syntax has two fallback forms, loop trajectory (`circle`) untested on real video, clip duration heuristic unvalidated.

Merging would require choosing one, and both have merit for different user contexts. Keeping both is pragmatic — local path stays fast for light/full-tier jobs, Colab path unlocks higher-fidelity depth on GPU boxes at the cost of a manual step.

## Technical Details

**Data-layer swap** (`parallax_link.py:33–59`):
- Iterate scenes; if keyed `image` AND no existing `video`, search `clips_dir` for matching stem.
- Found → pop `image` key, set `video` to relative path, set `motion: static` (clip carries depth).
- Missing → leave scene untouched (Ken Burns).
- Already video (b-roll) → skip (re-runs no-op).
- Returns mutated scenes + counts: `{swapped, missing, skipped}`.

**Colab DepthFlow** (`v4_depthflow_clips_colab.py`):
- Mount Google Drive, set headless backends (`WINDOW_BACKEND=headless`, `SHADERFLOW_BACKEND=headless`), install portaudio + DepthFlow + gradio.
- `circle` trajectory (periodic, loop-friendly): DepthFlow synthesizes camera motion on the inferred depth map; start frame ≈ end frame for seamless loop.
- FPS + duration params; output is loopable 1080p H.264.
- CLI syntax has two fallback forms (versions of DepthFlow differ; user adjusts in the script if needed).

**Integration point** (`.claude/commands/parallax-video.md`):
```
User calls: /parallax-video <job-folder>
1. make-video flow (init → storyboard → validate)
2. videotool parallax-link <job.yaml> --clips-dir Parallax/
3. render + package (unchanged)
```

## What We Tried

- **Option A: Merge into `enhance.parallax`** — rejected because DepthFlow is incompatible with the local numpy stack (licensing, GPU-only, no easy fallback).
- **Option B: Single `/parallax-video` without `enhance.parallax`** — rejected because it breaks the fast local path for users without Colab + Drive.
- **Option C: Parallel coexistence** — shipped. `/make-video` stays the default (fast local); `/parallax-video` is an opt-in fork for Colab users.

## Root Cause Analysis

The root mistake would have been **trying to unify too early**. A 2.5D parallax landscape has fundamentally different compute models:

1. **Local inference** (CPU-friendl y, slower, no GPU needed) vs. **GPU offload** (fast, requires external compute).
2. **Integrated pipeline** (render owns the motion) vs. **pre-baked clips** (clips own the motion).

We discovered this asymmetry during phase-03 (Colab script dev) and chose to honor it instead of forcing a false abstraction. The cost is two code paths; the benefit is zero render-code churn and no torch dependency bloat on CPU-only boxes.

## Lessons Learned

1. **Two parallax paths, same codebase, no merge needed.** Feature flags and orchestration layers are cheaper than merging incompatible backends. Users never see both unless they explicitly invoke `/parallax-video`.

2. **Colab script is user-transported, not embedded.** Clip transport is a manual step (download from Drive, upload locally), but it keeps the main codebase clean — no Colab-specific runtime logic, no Drive API code, no long-download stalls during regular renders.

3. **Data-layer swap, not render-layer swap.** Rewriting `job.yaml` scenes is simpler than refactoring the render path. Video scenes already existed; we just pointed more scenes at them.

4. **Loop trajectory matters for clip reuse.** The `circle` parameterization in DepthFlow is critical — without periodic motion, the clip won't loop seamlessly when `-stream_loop` plays it. This is unvalidated and is the next POC risk.

5. **Test `parallax-link` hard.** Scene swap logic is simple but brittle (stem matching, path relativization, skipping already-video scenes). 113-line test suite covers happy path + missing clips + re-runs; that discipline paid off.

## Next Steps

**Immediate (unblocking real use):**
1. User runs real Colab DepthFlow job on a video asset folder → validates DepthFlow CLI syntax (script has fallback forms; may need `!depthflow --help` fix).
2. Download Parallax/ clips, run `/parallax-video` locally → validate clip names match image stems, partial clip sets work, render + package succeed.
3. Check seamless loop quality: does a loopable clip stay in sync when rendered at 10+ seconds? (Circular motion should hide the splice.)

**Follow-up (optional hardening):**
- Clip duration heuristic: current script tries 10s; real videos may need 8s (lighter motion) or 12s (slower depth pans). Document the trade-off if complaints arrive.
- Scene-count fallback: if a job has 100+ scenes and only 20 clips, Ken Burns fill may look choppy. Warn in the output report or auto-suggest full FX for unmatched scenes.
- DepthFlow version pinning: Colab script installs latest; if DepthFlow breaks CLI again, pin a known version or auto-test both forms at startup.

---

## Unresolved Questions

1. **Loop seamlessness**: Does the `circle` trajectory really produce seamless clips at 8–12s? Needs 1–2 real Colab runs on narrative video.
2. **DepthFlow CLI stability**: Will the script's fallback syntax forms cover future DepthFlow versions, or do we need versioning?
3. **Stem matching robustness**: If an image is named `scene-01-revised.jpg`, does parallax_link find `Parallax/scene-01-revised.mp4`? (Yes, by `.stem`; confirmed in tests.)
4. **User friction**: Manual clip transport (Drive → local) adds a step. Is this acceptable, or should we auto-download from a shared Colab notebook link?

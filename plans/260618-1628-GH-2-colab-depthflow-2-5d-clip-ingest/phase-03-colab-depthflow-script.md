# Phase 03 — Colab DepthFlow batch clip script

## Context links
- Plan overview: [plan.md](plan.md)
- Adapt from: `Colab/v3_depthflow_colab.py` (VERIFIED — current DepthFlow Gradio prototype that
  also assembles a full video; we strip assembly).
- Consumed by: [phase-02](phase-02-parallax-video-skill.md) (`Parallax/<stem>.mp4` clips).

## Overview
- Priority: P2. Status: done. Independent of phases 01/02 — produces their input.
- New Colab script `Colab/v4_depthflow_clips_colab.py`: batch every image in `Image/` (or `media/`)
  into a loopable 1080p 2.5D parallax clip, named exactly `<input-stem>.mp4`, written to a
  `Parallax/` folder. **Clips only — NO audio, NO concat, NO mux.** The user downloads `Parallax/`
  and uploads it next to the asset folder for local ingest.

## Key insights
- `v3` already wires DepthFlow on Colab GPU (headless GL, portaudio via apt) and has a working
  `depthflow_clip(img, dur, fps, out)` with two CLI-form fallbacks (`v3:48-59`). Reuse that
  function near-verbatim — it is the load-bearing GPU call.
- v3's `build()` does depth→clip then NORMALIZE→CONCAT→MUX (`v3:124-138`). We delete everything from
  normalize onward: v4 stops after producing one clip per image.
- Local render loop+trims the clip to the scene's duration (`commands.py:91` `-stream_loop -1 -t`).
  For a seamless loop the DepthFlow motion must be **periodic** (start frame == end frame). DepthFlow
  orbit presets are sinusoidal → expected periodic; POC must confirm. If not periodic, fall back to
  a ping-pong loop at export (scope-out unless POC proves it needed).
- Clip length is decoupled from voice/scene length (that is the whole loopable-contract win). A
  fixed ~8-12s clip is enough; local loops it to whatever the scene needs.
- Naming is the contract with `parallax-link`: output file MUST be `<input-image-stem>.mp4` so
  `parallax-link` matches by stem. Lowercase `.mp4`.

## Requirements
Functional:
1. Mount Drive, install deps (`depthflow`, `ffmpeg`, `portaudio19-dev`) with Drive-cached pip/HF
   like v3 (`v3:14-34`).
2. Discover images in `Image/` → fallback `media/` → fallback folder root (reuse v3 `find_assets`
   image logic, drop voice/music discovery).
3. For each image: render one DepthFlow clip at 1920x1080, fixed duration (default 10s, slider
   8-12s), periodic orbit preset, fps 30. Write to `<folder>/Parallax/<stem>.mp4`.
4. **No** audio, **no** concat, **no** mux. The output is the `Parallax/` folder of clips only.
5. Per-image progress + on-failure message pointing at `!depthflow --help` (reuse v3 pattern).
6. Idempotent-ish: skip an image whose `Parallax/<stem>.mp4` already exists (cheap re-run / resume).
7. A short Gradio UI (folder path + duration + fps + Render button) mirroring v3, OR a plain loop
   cell — keep whichever is simpler (KISS); v3's Gradio is fine to reuse.

Non-functional: keep close to v3 so the user's mental model carries over; single-cell paste.

## Architecture
```
COLAB GPU
Image/<stem>.jpg ──depthflow_clip(periodic orbit, 1080p, ~10s)──> Parallax/<stem>.mp4 (loopable, silent)
                  (skip if exists)
Output: <folder>/Parallax/  ── user downloads → uploads beside asset folder → local parallax-link
```
- No timeline knowledge on Colab. No voice. The clip is a reusable loop; timing lives local.

## Related code files
Create:
- `Colab/v4_depthflow_clips_colab.py`.
Read for context:
- `Colab/v3_depthflow_colab.py` (reuse `sh`, deps, `depthflow_clip`, image discovery).
Do NOT touch:
- v1/v2/v3 Colab scripts (kept as-is); any `src/`.

## Implementation steps
1. Copy v3 header + env/deps/mount block (`v3:1-34`).
2. Keep `sh`, `depthflow_clip` (`v3:30-59`) — verify a periodic/orbit flag exists; if a preset
   name is needed, add it to the CLI form (single line, per v3's own note).
3. Reduce `find_assets` to image discovery only (drop voice/music).
4. Replace `build()` with `make_clips(folder, dur, fps)`: ensure `Parallax/` exists; loop images;
   skip existing; call `depthflow_clip(img, dur, fps, Parallax/<stem>.mp4)`; report count + time.
5. Delete normalize/concat/mux entirely.
6. Gradio: folder path + duration slider (8-12, default 10) + fps slider (24-30, default 30) +
   Render button → `make_clips`.
7. Final log: clip count, output dir, reminder to download `Parallax/` and place it beside the
   asset folder.

## Manual / POC verification (NOT unit-testable — stated explicitly)
Runs only on Colab GPU → no local pytest. Verify by:
- (POC) Run on 3-5 images; confirm `Parallax/<stem>.mp4` files appear, 1920x1080, ~10s
  (`ffprobe`), silent.
- (POC, loop seam) Locally `-stream_loop -1 -t 40` one clip and eyeball the loop point for a jump.
  Periodic → ship as-is. Visible jump → enable ping-pong (then update scope-out + this phase).
- (POC) Confirm stems match the source images exactly so `parallax-link` (phase-01) maps them.

## Todo
- [ ] Create `Colab/v4_depthflow_clips_colab.py` from v3.
- [ ] Strip voice/music/concat/mux; keep clips-only.
- [ ] Periodic orbit preset, 1080p, fixed ~10s, fps 30, name `<stem>.mp4` → `Parallax/`.
- [ ] Skip-existing for resume.
- [ ] POC on 3-5 images; verify resolution/duration/silence + loop seam.

## Success criteria
- Script emits one loopable 1080p silent clip per image, named `<stem>.mp4`, under `Parallax/`.
- No assembly/audio in the script.
- A clip loops seamlessly under local `-stream_loop` (or ping-pong fallback documented).

## Risk assessment
| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|-----------|
| DepthFlow CLI syntax differs by version | Med | High | Keep v3's two-form fallback + `!depthflow --help` guidance. |
| Orbit not periodic → visible loop seam | Med | Med | POC loop test; ping-pong fallback (scope-out until proven). |
| Colab session/GPU flakiness on 115 images | Med | Med | Skip-existing enables resume across sessions. |
| Edge disocclusion artifacts at high amplitude | Med | Low | Keep DepthFlow amplitude modest (POC tune), like the numpy path's conservative PARALLAX_PX. |
| Clip stem ≠ image stem → no local match | Low | High | Hard-code output name to source stem; POC asserts match. |

## Security
- User-side Colab; mounts the user's own Drive. No repo secrets. No bundled copyrighted assets
  (clips are generated from the user's own images).

## Next steps
- Feeds phase-02 (clips land in `Parallax/`).
- Open questions (carry to user): periodic-loop config for DepthFlow; optimal fixed clip length
  (8/10/12s) for ~55s avg scenes; whether ping-pong is needed.

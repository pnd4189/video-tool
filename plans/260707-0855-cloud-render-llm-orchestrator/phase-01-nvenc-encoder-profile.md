---
phase: 1
title: NVENC encoder profile
status: completed
priority: P1
dependencies: []
---

# Phase 1: NVENC encoder profile

## Overview
Additive `h264_nvenc-capped` render profile so cloud T4 GPUs encode instead of 2-4 slow vCPUs. Only shared-code touch of the whole plan; local default `libx264-balanced` unchanged.

## Requirements
- Functional: `render.encoder: h264_nvenc-capped` in job.yaml produces a working ffmpeg command on a machine with NVENC; size behavior ≈ `libx264-balanced-capped` (<2.5GB long video).
- Non-functional: zero change to existing profiles/defaults; local machines without NVENC simply never select it.

## Architecture
`codec_args()` (video_filters.py:13) is already generic — `crf=None` skipped, `extra_args` appended, `-preset` flag shared. NVENC quality knob goes in `extra_args`.

**Correction (red-team M9):** `_reject_unsupported_profile` (commands.py:149) is NOT the only/primary gate. It has exactly ONE caller — `build_ffmpeg_command` (commands.py:26), the INLINE path. The **segmented** path (`build_segmented_render`, used for >40-scene jobs and forced ON for all cloud renders per Phase 3 C3) calls `codec_args` at `segmented.py:81,109` with NO gate. So the allowlist relax matters only for inline; the segmented path already accepts any encoder. The real cloud path is the segmented one — it MUST be the one tested.

## Related Code Files
- Modify: `src/videotool/render/profiles.py` — add profile:
  ```python
  "h264_nvenc-capped": RenderProfile(
      "h264_nvenc-capped", "h264_nvenc", "p5", None,
      extra_args=("-rc", "vbr", "-cq", "23", "-maxrate", "2800k", "-bufsize", "5600k"),
  ),
  ```
  (`-cq 23` starting point; phase 4 tunes against size cap.)
- Modify: `src/videotool/render/commands.py` — `_reject_unsupported_profile`: allow `h264_nvenc` alongside `libx264` (keep rejecting VAAPI/AV1/HEVC with the existing clear error).
- Modify: `tests/` — extend existing profile/command tests for BOTH paths (red-team M9):
  - inline `build_ffmpeg_command`: nvenc profile resolves, command contains `-c:v h264_nvenc`, no `-crf`, `-cq 23`, `-preset p5` token present; default profile output unchanged.
  - **segmented** `build_segmented_render` (>40 scenes): each scene-clip command AND the mux command contain `-c:v h264_nvenc`, no `-crf`. This is the actual cloud path and must be asserted, not just inline.

## Implementation Steps
1. Add profile to `PROFILES` dict.
2. Relax `_reject_unsupported_profile` allowlist to `("libx264", "h264_nvenc")` prefixes (guards the inline path only — see M9).
3. Verify `segmented.py` scene-clip (`_build_scene_clip`) and mux (`_build_mux_command`) both route through `codec_args(profile)` (light tier mux is `-c:v copy`, unaffected). The segmented scene-clip encode is where cloud NVENC actually runs.
4. Tests for BOTH inline and segmented paths (M9) + `pytest -q` full suite.

**Note (M10):** `-preset p5` requires ffmpeg ≥ 4.4 (the `p1`–`p7` namespace). `codec_args` passes the preset token verbatim (`video_filters.py:14-16`); older ffmpeg rejects `p5`. The runtime ffmpeg-version probe + legacy-preset fallback lives in Phase 3's GPU probe (step 4) — Phase 1 just asserts the emitted token so a version mismatch fails loudly, not silently.

## Success Criteria
- [x] `get_profile("h264_nvenc-capped")` works; command builder emits valid nvenc args (no `-crf`). — inline + segmented (scene-clip + full-tier mux) asserted.
- [x] `pytest -q` 193 green; no default-path diff (default profile asserted unchanged; AV1/HEVC still rejected).
- [ ] Verified on Colab T4: 60s sample render succeeds with `h264_nvenc-capped`. **NOT GPU-verified** — no GPU session available; deferred to Phase 4 E2E. Command is proven correct (no `-crf`, `-preset p5`), but real NVENC encode on a T4 is untested.

## Risk Assessment
- **`-preset p5` needs ffmpeg ≥ 4.4 (red-team M10)** — the `p1`–`p7` NVENC preset namespace does not exist before 4.4; older builds reject `p5` and every scene encode fails at the first ffmpeg call. `-rc vbr -cq` rate-control is stable since ffmpeg 4, but the preset token is the real risk. Mitigation: Phase 3 probes `ffmpeg -version` + `ffmpeg -h encoder=h264_nvenc`, requires ≥4.4 or substitutes a legacy preset name; Phase 4 pins the expected ffmpeg version in setup docs.
- Filter chain stays CPU (`format=yuv420p` pipeline untouched) — intentional; no hwupload complexity.

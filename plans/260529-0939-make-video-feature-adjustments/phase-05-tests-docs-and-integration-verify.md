---
phase: 5
title: Tests docs and integration verify
status: completed
priority: P1
effort: 3h
dependencies:
  - 1
  - 2
  - 3
  - 4
---

# Phase 5: Tests, docs, and integration verify

## Overview
Add tests for the new behavior, update the snapshot tests broken by the -28dB default,
refresh docs, write the item-6 (effects) feasibility note, and run the end-to-end smoke.

## Requirements
- Functional: full suite green (66 existing + new), no skipped/xfail to hide failures.
- Functional: docs reflect shorts opt-in, intro/ending, -28dB multi-music, gdrive staging.
- Non-functional: files stay <200 lines where touched; flag `core/services.py` if it grows.

## Related Code Files
- Modify: `tests/test_audio_db_mixer.py` — update expectations for `-28dB` default + new
  `apad=pad_dur=...` suffix when `voice_pad_seconds > 0`; add a no-pad case asserting absence.
- Modify: `tests/test_storyboard_autogen.py` — add intro-only / ending-only / both / neither
  cases asserting scene count, durations, and total == voice(+10).
- Create/Modify: `tests/test_audio_db_mixer.py` or a new `tests/test_music_bed.py` — multi-track
  concat-loop: 3 synthetic short tracks → bed == target, order preserved, single-track path.
- Modify: `tests/test_music_loop.py` — update the 4 calls to the new `prepare_seamless_music`
  list[Path] signature; add a multi-track ordering assertion.
- Add: a `static` motion render test — `scene_filter` for `motion="static"` emits scale-decrease
  + pad (letterbox), no `zoompan`.
- Modify: template tests (whichever assert `outputs`) — expect single `youtube-16x9` preset.
- Modify: `docs/codebase-summary.md` — note the new InputSpec fields, audio defaults, staging.
- Modify: `AGENTS.md` — already touched in phases 1 & 4; verify consistency.
- Create: feasibility note for item 6 — append to the brainstorm report or a short
  `plans/reports/260529-effects-feasibility.md`.

## Implementation Steps
1. Update snapshot/assertion tests for the -28dB default and single-preset templates.
2. Add storyboard tests (intro/ending permutations) using synthetic temp images + a fake
   voice duration (no real ffmpeg needed for the planner-level scene math).
3. Add music-bed tests: generate short silent tracks via ffmpeg `anullsrc` in a tmp dir,
   assert the prepared bed duration ≈ target and that all distinct inputs appear in the
   filter sequence.
4. Refresh `docs/codebase-summary.md`.
5. Write the item-6 effects feasibility note: rain/wind/particle overlay rides the per-clip
   encode in the segmented path (no extra mux pass), est. +10–20% CPU; contrast with the
   rejected waveform overlay (forced mux re-encode). Recommend looping-PNG overlay or a
   generated filter; defer implementation.
6. Run `.venv/bin/python -m pytest -q` (expect 66+ passing) and `.venv/bin/videotool doctor`.
7. End-to-end smoke on a representative Chap folder (per `AGENTS.md` verification): confirm
   intro 10s, ending 10s, music at -28dB, only youtube-16x9 output, and
   `ffprobe` shows h264 + aac + correct resolution + total ≈ voice+10.

## Success Criteria
- [ ] All tests pass; new behavior covered; no hidden xfail/skip.
- [ ] `ffprobe` on the smoke output: h264/aac, 1920x1080, duration ≈ voice+10.
- [ ] Intro/ending visible at the right spots; music audibly under voice at -28dB.
- [ ] Docs + AGENTS consistent with shipped behavior.
- [ ] Item-6 feasibility note written.

## Risk Assessment
- Snapshot churn from -28dB touches multiple assertions → grep for `-18` / `volume=-18dB`
  across tests first, update all at once.
- Smoke render of a long chapter is slow → run on a short trimmed sample for the gate, note
  full-length is unchanged in shape.
- `core/services.py` already >200 lines; if `_stage_music` growth pushes it further, extract a
  small `music staging` helper rather than inflating the file.

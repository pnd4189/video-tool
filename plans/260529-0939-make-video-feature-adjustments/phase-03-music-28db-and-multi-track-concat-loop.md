---
phase: 3
title: Music -28dB and multi-track concat-loop
status: completed
priority: P1
effort: 4h
dependencies:
  - 2
---

# Phase 3: Music -28dB and multi-track concat-loop

## Overview
Lower default music to -28 dB, and when the asset folder holds multiple instrument
tracks, concat them in order then loop the sequence to cover the full video
(including the +10s ending).

## Requirements
- Functional: `AudioSpec.music_gain_db` default = `-28.0`.
- Functional: the skill always points `inputs.music` at the `music/` **directory** → all audio
  files (natural-sorted by filename) are concatenated in order, then looped to the target.
  Document the `01-`,`02-` filename-prefix convention for controlling order.
- Functional: single-file `inputs.music` keeps working unchanged (target just grows to total).
- Functional: target duration = total video = `voice + OUTRO_SECONDS` (covers the ending).
- Non-functional: heterogeneous sample rates/channels must be normalized before concat.

## Architecture
`_stage_music` (services) resolves `inputs.music`: a file → `[file]`; a dir → sorted audio
files by extension. It computes the target as the max of voice duration and the storyboard
scene-duration sum (so the +10s ending is covered even though voice is shorter). It calls a
generalized `prepare_seamless_music` that accepts a **list** of tracks.

`prepare_seamless_music` builds an input sequence by cycling the track list until cumulative
duration ≥ target, then acrossfades the whole sequence (existing `_build_loop_command`
structure), atrims to target, and fades out. Each input is resampled/reformatted so
acrossfade joins cleanly.

<!-- Updated: Validation Session 1 - music=folder always, natural-sort order, list[Path] breaking change -->

## Related Code Files
- Modify: `src/videotool/core/job_spec.py` — `AudioSpec.music_gain_db` default `-18.0` → `-28.0`.
- Modify: `src/videotool/core/timeline.py:42` — dataclass `music_gain_db` default `-18.0` → `-28.0`
  (duplicate default; both must change to stay consistent).
- Modify: `tests/test_music_loop.py` — 4 calls (lines ~38/50/62/70) use the old
  `prepare_seamless_music(music, ...)` single-Path positional API; update to the list[Path] API.
- Modify: `src/videotool/render/music_loop.py` —
  - change `prepare_seamless_music(music_path: Path, ...)` to
    `prepare_seamless_music(music_paths: list[Path], ...)`.
  - probe each track; build the repeated sequence list to reach `target_duration`.
  - generalize `_build_loop_command` to take a list of (heterogeneous) input paths; insert
    `aformat=sample_rates=48000:channel_layouts=stereo` (or `aresample=48000`) per input
    before the acrossfade chain.
  - keep the single-track-longer-than-target trim fast path.
  - keep `MAX_PLAYS` cap on total inputs.
- Modify: `src/videotool/core/services.py` — `_stage_music`:
  - resolve dir → sorted list (reuse `discover_scene_images` pattern: natural sort by
    extension; add an audio-extension constant e.g. `.mp3 .wav .m4a .flac .ogg .aac`).
  - target = `max(voice_duration, sum(scene.duration for scene in job.storyboard))`.
  - pass the list + target to `prepare_seamless_music`.

## Implementation Steps
1. Change the `music_gain_db` default to `-28.0`.
2. Generalize `music_loop.py` to a list API (see Related Code Files). Natural-sort the file
   list when a dir is expanded (done in services, pass ordered list).
3. Add audio-extension discovery + dir expansion in `_stage_music`; compute the total-duration
   target from the storyboard sum so the ending is covered.
4. Wire `_stage_music` to the new list signature.
5. Update any caller/test referencing the old `prepare_seamless_music(music_path=...)` keyword.
6. Run pytest; finalize tests in phase 5.

## Success Criteria
- [ ] Default rendered audio mixes music at -28 dB (graph shows `volume=-28dB`).
- [ ] A `music/` dir with 3 tracks → prepared bed concatenates all 3 in order, then loops.
- [ ] Prepared bed duration == total video (voice + 10), with fade-out tail.
- [ ] Single-file music still works; bed covers the +10s ending.
- [ ] Mixed sample-rate tracks concat without ffmpeg format errors.

## Risk Assessment
- acrossfade across many heterogeneous inputs → enforce per-input `aformat`/`aresample`.
- Very short tracks vs long video → `MAX_PLAYS` cap surfaces an actionable error (keep it).
- -28 dB default changes audio-graph snapshot tests → update expectations in phase 5
  (verified-decision change per user, document in the test, not a regression).
- Ordering: rely on natural sort of filenames; document that users name tracks `01-, 02-` to
  control order.

---
phase: 1
title: "dB audio mixer (AudioSpec + _audio_graph)"
status: pending
priority: P1
effort: "0.5-1d"
dependencies: []
---

# Phase 1: dB audio mixer (AudioSpec + _audio_graph)

## Overview

Capcut-style per-track volume: independent `voice_gain_db` / `music_gain_db`,
optional auto-duck, optional final loudnorm. Replace the two hardcoded
`volume=0.5` music gains in `render/commands.py` with `volume={x}dB`, and extract
the duplicated audio filtergraph into one `_audio_graph()` helper (DRY) used by
both the single-background and storyboard command paths.

## Requirements

- Functional:
  - `audio.voice_gain_db` (float, default `0.0`) and `audio.music_gain_db`
    (float, default `-18.0`) emit `volume={x}dB`. Default music is a **gentle
    background bed** — clearly subordinate to the narration, pleasant not loud
    (user decision, supersedes the earlier "-6.0 preserve" proposal).
  - `audio.duck` (bool, default `true`): music ducks further under the voice via
    `sidechaincompress`; when `false`, skip it, plain `amix` only.
  - `audio.normalize_lufs` (float | None, default `-14.0`): when `null`, drop the
    `loudnorm` filter so dB values are absolute. With loudnorm ON, dB sets the
    voice/music *balance*; the final mix is normalized to -14 LUFS.
  - Duck + loudnorm still ON by default (existing `sidechaincompress`/`loudnorm`
    substring tests stay green); only the music *level* changes (quieter bed).
- Non-functional: `commands.py` stays <200 lines (extracting the helper removes
  the duplicated block, net neutral); no new dependency.

## Architecture

- `core/job_spec.py`: add `AudioSpec(BaseModel, extra="forbid")` with the 4 fields
  above; add `audio: AudioSpec = Field(default_factory=AudioSpec)` to `JobSpec`.
- `core/timeline.py`: thread audio settings onto `Timeline` (add
  `voice_gain_db`, `music_gain_db`, `duck`, `normalize_lufs` fields with
  defaults = current behavior) and populate them in `compile_timeline`.
- `render/commands.py`: new module-level helper
  `_audio_graph(voice_label: str, music_label: str | None, *, voice_gain_db,
  music_gain_db, duck, normalize_lufs, has_music) -> str`. It returns the
  `filter_complex` audio sub-graph string ending in `[aout]` (or the simple
  `-af` form when no music). Both `build_ffmpeg_command` (single-bg) and
  `_build_storyboard_command` call it instead of inlining the graph. Keep
  `SIDECHAIN_PARAMS` / `LOUDNORM_TARGET` constants; build `loudnorm=...` from
  `normalize_lufs` (None → omit).
- dB formatting: `f"volume={gain_db}dB"` (e.g. `volume=-18.0dB`, `volume=0.0dB`).

## Related Code Files

- Modify: `src/videotool/core/job_spec.py` (AudioSpec + JobSpec.audio)
- Modify: `src/videotool/core/timeline.py` (Timeline fields + compile_timeline)
- Modify: `src/videotool/render/commands.py` (extract `_audio_graph`, wire dB)
- Create: `tests/test_audio_db_mixer.py`

## Implementation Steps

1. **TDD lock**: in `tests/test_audio_db_mixer.py`, characterize current output —
   default job → command still contains `sidechaincompress` and
   `loudnorm=I=-14:TP=-1:LRA=11` (mirrors the existing
   `test_audio_graph_uses_sidechain_and_lufs_target`). Run; green.
2. **TDD new (red)**: add tests asserting:
   - default `music_gain_db=-18.0` → `volume=-18.0dB` present, no literal `volume=0.5`.
   - `duck: false` → command has NO `sidechaincompress`, still has `amix`.
   - `normalize_lufs: null` → command has NO `loudnorm`.
   - `voice_gain_db: 3.0` → `volume=3.0dB` on the voice branch.
   Run; red.
3. Add `AudioSpec` + `JobSpec.audio` in `job_spec.py`.
4. Add audio fields to `Timeline` + populate in `compile_timeline`.
5. Extract `_audio_graph()` in `commands.py`; replace both inlined graphs (single-bg
   lines ~52-60 and storyboard lines ~94-100) with calls to it. Map gains to
   `volume={x}dB`, gate `sidechaincompress` on `duck`, gate `loudnorm` on
   `normalize_lufs`.
6. Run full suite; green. Confirm `commands.py` < 200 lines.

## Success Criteria

- [ ] Existing `test_audio_mix_and_metadata.py` + all 43 tests stay green.
- [ ] New tests for dB mapping, duck toggle, loudnorm toggle pass.
- [ ] No `volume=0.5` literal remains; both audio paths share `_audio_graph()`.
- [ ] Default-config command byte-equivalent in the asserted substrings to before.

## Risk Assessment

- dB vs loudnorm confusion: when `normalize_lufs` stays at -14, dB only changes
  the voice/music *balance*, not absolute loudness. Documented in field comment;
  set `normalize_lufs: null` for absolute dB. Not a code risk, a usage note.
- Default music drops from old `0.5` (≈ -6 dB) to `-18 dB` → noticeably quieter
  background bed per user request. Existing renders re-run will have softer music;
  acceptable (no test asserts loudness, only filter presence). Tunable per job.

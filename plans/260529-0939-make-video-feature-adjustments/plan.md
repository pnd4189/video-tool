---
title: >-
  make-video feature adjustments: shorts opt-in, intro/ending images, -28dB
  multi-music, rclone staging
description: >-
  Five adjustments to the working /make-video pipeline: render youtube-16x9 only
  by default, embed an intro thumbnail in the first 10s + append a 10s ending
  image, lower music to -28dB and concat-loop multiple tracks, and stage gdrive
  assets locally then publish outputs back. Effects (item 6) report-only.
status: completed
priority: P1
branch: main
tags:
  - feature
  - ffmpeg
  - audio
  - storyboard
  - rclone
  - skill
blockedBy: []
blocks: []
created: '2026-05-29T03:08:53.969Z'
createdBy: 'ck:plan'
source: skill
---

# make-video feature adjustments

## Overview

Five targeted adjustments to the already-shipped `/make-video` flow (see
`plans/260527-1700-videotool-feature-expansion` = done). Brainstorm source:
`plans/reports/260529-0939-make-video-feature-adjustments-brainstorm.md`.

Confirmed `AGENTS.md` decisions stay locked (motion 0.30/1.22, no waveform, no Whisper).

### Duration model (drives phases 2 & 3)

```
total video = voice + OUTRO_SECONDS(10)
  0 .. 10s          intro thumbnail   (voice playing under it)
  10s .. voice_end  storyboard images (even-split over voice − 10)
  voice_end .. +10s  ending image     (voice silent, music continues)
audio: voice apad'd +10s silence so -shortest ends at the video (voice+10), not the voice.
music: all tracks concat in order, looped to cover total (incl. the +10s).
```

**Critical:** both render paths (`render/commands.py:_build_storyboard_command` and
`render/segmented.py:_build_mux_command`) end with `-shortest`. Without voice `apad`,
`-shortest` truncates the 10s ending. Voice padding is mandatory, not cosmetic.

## Phases

| Phase | Name | Status |
|-------|------|--------|
| 1 | [Output presets shorts opt-in](./phase-01-output-presets-shorts-opt-in.md) | Completed |
| 2 | [Intro and ending image scenes](./phase-02-intro-and-ending-image-scenes.md) | Completed |
| 3 | [Music -28dB and multi-track concat-loop](./phase-03-music-28db-and-multi-track-concat-loop.md) | Completed |
| 4 | [rclone gdrive staging workflow](./phase-04-rclone-gdrive-staging-workflow.md) | Completed |
| 5 | [Tests docs and integration verify](./phase-05-tests-docs-and-integration-verify.md) | Completed |

## Key dependencies

- Phase 2 introduces `voice_pad_seconds` on the timeline + total-duration concept.
- Phase 3 consumes the same total duration for the music target. Do phase 2 before 3.
- Phase 4 is skill/AGENTS-only (no core code); independent, can run any time.
- Phase 5 closes out: update the 2 snapshot tests broken by the -28dB default, add new
  tests, refresh docs, run the Chap-1 smoke per `AGENTS.md` verification commands.

## Out of scope

- Rain/wind/particle effects (item 6) — feasibility note only, in phase 5 docs/report.
- New presets, Whisper, waveform. INTRO/OUTRO fixed at 10s constants.

## Related plans

- `260527-1635-audio-story-autopublisher-mvp` (pending): proposes a separate
  `make-youtube` command in the same domain. Not an operational blocker; this round
  edits the existing pipeline the skill already drives. No bidirectional dependency set.

## Validation Log

### Verification Results (2026-05-29)
- Tier: Full (5 phases). Claims checked across all phases.
- Verified: file paths/symbols all exist. Failed: 0. Unverified: 0.
- Refinements found (folded into phases):
  - `music_gain_db` default lives in BOTH `core/job_spec.py:79` and `core/timeline.py:42`
    (dataclass default) — change both. (phase 3)
  - `prepare_seamless_music(music_path, ...)` is called positionally in
    `tests/test_music_loop.py` lines 38/50/62/70 + `core/services.py:237`; the list[Path]
    signature change must update all 5. (phase 3 + 5)
  - `validate_job_paths` (`core/validation.py:11`) enforces paths inside the job folder and
    must-exist; add `intro_image`/`ending_image` to its `candidates`. (phase 2)
  - `-18` snapshot assertion at `tests/test_audio_db_mixer.py:40`. (phase 5)

### Interview decisions (2026-05-29)
1. **Music source** → skill always points `inputs.music` at the `music/` folder; services
   expands a dir to all audio files. No file-count branching. (phase 3 + phase 4 skill)
2. **Multi-track order** → natural-sort by filename; document `01-`,`02-` prefix convention. (phase 3)
3. **Intro/ending motion** → STATIC (no zoompan), letterbox-safe so designed thumbnails/credits
   are never cropped. Requires a new `static` motion. (phase 2)
4. **Detect fallback** → if intro/ending image not confidently found (absent or ambiguous),
   skip it and render normally, report the skip. Not an error. (phase 4 skill)

### Whole-Plan Consistency Sweep (2026-05-29)
- Re-read plan.md + all 5 phase files after propagation. No stale terms or contradictions.
- `static` motion now consistently referenced in phase 2 (job_spec Literal + storyboard
  MOTION_CHOICES + scene_filter branch). Music "folder" framing consistent in phases 3 & 4.
- Zero unresolved contradictions → eligible for implementation.

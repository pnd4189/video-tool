---
phase: 2
title: Intro and ending image scenes
status: completed
priority: P1
effort: 4h
dependencies:
  - 1
---

# Phase 2: Intro and ending image scenes

## Overview
Embed a thumbnail-template image over the first 10s of the voice timeline (no added
time), and append a provided ending image as a real 10s outro after the voice ends.
Voice is padded with 10s silence so `-shortest` keeps the outro.

## Requirements
- Functional: when `inputs.intro_image` set → scene 1 = that image, 10s; middle storyboard
  images split `voice_duration − 10`.
- Functional: when `inputs.ending_image` set → last scene = that image, 10s; total video =
  voice + 10; during the outro the voice track is silent (padded).
- Functional: both fields optional and independent (intro-only, ending-only, neither, both).
- Non-functional: guard `voice <= INTRO_SECONDS` → skip intro with a warning.
- Non-functional: existing jobs without these fields render byte-for-byte as before
  (apad is 0, no extra scenes).

<!-- Updated: Validation Session 1 - intro/ending motion = static (no zoompan), letterbox-safe -->

## Architecture
Intro/ending are new optional `InputSpec` paths. `auto_storyboard` reads them and emits a
scene list `[intro?] + even-split(middle) + [ending?]`. The even-split base subtracts
`INTRO_SECONDS` when an intro is present; the ending is pure extension.

Intro/ending scenes use a new `static` motion (validation decision): no zoompan, the image is
scaled to fit the frame and letterboxed (pad) so a designed thumbnail or credits frame is
never cropped. This needs a `static` value added to the motion Literal + a branch in
`scene_filter`.

`compile_timeline` computes `voice_pad_seconds = max(0, sum(scene.duration) − voice_duration)`
and stores it on `Timeline`. `build_audio_graph` gains a `voice_pad_seconds` param and, when
> 0, appends `apad=pad_dur={n}` to the voice chain (duck, no-duck, and no-music branches all
covered) so the muxed audio reaches the full video length.

## Related Code Files
- Modify: `src/videotool/core/job_spec.py` — add `intro_image: Path | None = None`,
  `ending_image: Path | None = None` to `InputSpec`; add `"static"` to the
  `StoryboardSceneSpec.motion` Literal.
- Modify: `src/videotool/core/storyboard.py` — add `INTRO_SECONDS = 10`, `OUTRO_SECONDS = 10`;
  add `"static"` to `MOTION_CHOICES`; extend `build_even_split_storyboard` to accept
  `lead_seconds` (reserved for intro) and optional `intro_image` / `ending_image` so it emits
  the framed scene list with `motion="static"` on intro/ending.
- Modify: `src/videotool/render/video_filters.py` — `scene_filter` gets a `static` branch:
  `scale=W:H:force_original_aspect_ratio=decrease,pad=W:H:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=...`
  then `trim`/`setpts` (no zoompan). Letterboxes instead of cropping.
- Modify: `src/videotool/cli/storyboard_commands.py` — `auto_storyboard` reads the job's
  intro/ending fields and passes them through; relativizes their paths like scene images.
- Modify: `src/videotool/core/timeline.py` — add `voice_pad_seconds: float = 0.0`; compute in
  `compile_timeline`.
- Modify: `src/videotool/render/audio_graph.py` — `audio_settings` returns `voice_pad_seconds`;
  `build_audio_graph` applies `apad=pad_dur=...` to the voice chain when > 0.
- Modify: `src/videotool/core/validation.py` — `validate_job_paths` add `intro_image`/
  `ending_image` to `candidates` (verified: it enforces inside-folder + must-exist). The
  segmented clip builder (`render/segmented.py`) also calls `scene_filter`, so the `static`
  branch covers both render paths automatically.

## Implementation Steps
1. Add the two optional paths to `InputSpec`.
2. In `storyboard.py`, add the constants. Refactor `build_even_split_storyboard`:
   - `effective = voice_duration − (INTRO_SECONDS if intro else 0)`.
   - even-split images across `effective` (last image absorbs rounding).
   - prepend `{scene:1, image:intro, duration:INTRO_SECONDS, motion:"static", transition:"crossfade"}`
     when intro present (renumber following scenes).
   - append `{scene:last, image:ending, duration:OUTRO_SECONDS, motion:"static", transition:"crossfade"}`
     when ending present.
   - guard: if `voice_duration <= INTRO_SECONDS`, skip intro + `console` warning.
   - add `"static"` to `MOTION_CHOICES` and the `job_spec` motion Literal; add the `static`
     branch in `scene_filter` (scale-decrease + pad, no zoompan).
   - add `intro_image`/`ending_image` to `validate_job_paths` candidates.
3. In `auto_storyboard`, read `data["inputs"].get("intro_image")` / `ending_image`, resolve to
   absolute for `build_even_split_storyboard`, then relativize the emitted scene image paths
   to the job dir (reuse `_relative_or_original`).
4. In `timeline.py`, add `voice_pad_seconds` field; in `compile_timeline` set
   `voice_pad_seconds = max(0.0, sum(s.duration for s in scenes) − (duration or 0))`.
5. In `audio_graph.py`:
   - add `voice_pad_seconds: float = 0.0` to `build_audio_graph` signature and to the dict
     returned by `audio_settings`.
   - build a `pad = f",apad=pad_dur={voice_pad_seconds:g}"` suffix (empty when 0) and append it
     to the `voice_vol` chain in all three branches (duck / no-duck / no-music `-af`).
6. Verify the apad flows through both `render/commands.py` (storyboard path) and
   `render/segmented.py` (mux) — both call `build_audio_graph(**audio_settings(timeline))`, so
   no change needed there beyond the new kwarg passing automatically.
7. Run pytest; add/adjust tests in phase 5.

## Success Criteria
- [ ] intro-only, ending-only, both, neither all compile to correct scene lists + durations.
- [ ] With ending set, generated audio graph contains `apad=pad_dur=10`.
- [ ] `sum(scene durations) == voice + 10` when ending present; `== voice` when only intro.
- [ ] Jobs with neither field produce unchanged commands (apad suffix absent).
- [ ] `voice <= 10s` + intro → intro skipped, warning emitted, no crash.

## Risk Assessment
- `apad` placement: must be on the voice stream before `asplit` (duck keys off the padded
  voice; during silence the duck releases → music audible). Verify the filter parses.
- Float rounding on durations could make video/audio differ by <1 frame → acceptable;
  `-shortest` clips to the shorter, apad guarantees audio ≥ video.
- `slow-push` on a 10s static thumbnail = mild zoom; acceptable and cheap. If undesirable,
  switch intro/outro to a no-motion path later (not this round).

---
phase: 2
title: "Job Spec And Timeline Model"
status: completed
priority: P1
effort: "2d"
dependencies: [1]
---

# Phase 2: Job Spec And Timeline Model

## Context Links

- [Plan overview](./plan.md)
- [Research summary](./research/research-summary.md)

## Overview

Define the user-facing `job.yaml` format and internal timeline model. This is the contract between CLI, GUI, asset library, AI analysis, and FFmpeg renderer.

## Requirements

- Functional: validate input audio, media folders, music, output presets, captions, overlays, transitions, and package options.
- Non-functional: deterministic, human-editable, versioned schema, clear validation errors.

## Architecture

Use two layers:

```text
JobSpec (user YAML/JSON)
  -> validation and defaults
Timeline (render-ready normalized model)
  -> tracks, clips, overlays, audio plan, outputs
```

Keep render-specific FFmpeg strings out of the schema. The timeline describes intent; Phase 4 turns it into commands.

## Related Code Files

| Action | Path | Purpose | Test Impact |
|---|---|---|---|
| Create | `/home/dung/VIBE_CODING/video-tool/src/videotool/core/job_spec.py` | Pydantic job schema | Unit tests |
| Create | `/home/dung/VIBE_CODING/video-tool/src/videotool/core/timeline.py` | Normalized timeline dataclasses/models | Unit tests |
| Create | `/home/dung/VIBE_CODING/video-tool/src/videotool/core/presets.py` | `youtube-16x9`, `shorts-9x16` presets | Unit tests |
| Create | `/home/dung/VIBE_CODING/video-tool/src/videotool/core/validation.py` | Cross-field validation helpers | Unit tests |
| Create | `/home/dung/VIBE_CODING/video-tool/examples/jobs/basic-audio-first/job.yaml` | Example job | Integration tests |
| Create | `/home/dung/VIBE_CODING/video-tool/tests/test_job_spec.py` | Schema tests | New |
| Create | `/home/dung/VIBE_CODING/video-tool/tests/test_timeline.py` | Timeline compile tests | New |

## Proposed `job.yaml` Shape

```yaml
version: 1
project:
  title: "sample-video"
  language: "vi"
inputs:
  voice: "voice.wav"
  media_dir: "media"
  music: "music/background.mp3"
outputs:
  - preset: "youtube-16x9"
  - preset: "shorts-9x16"
captions:
  mode: "srt-and-burn"
assets:
  policy: "licensed-only"
render:
  encoder: "libx264-balanced"
  temp_dir: ".videotool/tmp"
```

## Implementation Steps

1. Define schema versioning and reject unknown major versions.
2. Add output presets with width, height, fps, safe area, subtitle style defaults, bitrate targets.
3. Add audio policy: BGM loop/trim to voice duration, fade in/out, duck under voice, final loudness normalization.
4. Add media selection policy: sequential, random-seeded, or tag-matched. V1 default: deterministic sequential with seed.
5. Add transition policy: none, crossfade, cut, simple zoom/pan. V1 default: simple cut/crossfade only.
6. Add package options: write SRT, thumbnail candidate, description, license report, quality report.
7. Implement `compile_timeline(job, media_probe)` returning a render-ready model.
8. Add validation tests for missing files, invalid presets, negative durations, unsupported extension, and bad license policy.

## Function Or Interface Checklist

- `JobSpec`
- `OutputPreset`
- `AudioMixSpec`
- `CaptionSpec`
- `Timeline`
- `compile_timeline(job_spec, media_index)`
- `load_job(path)`
- `validate_job(job_spec)`

## Test Scenario Matrix

| Scenario | Type | Expected |
|---|---|---|
| valid basic job | Unit | loads and compiles |
| unknown preset | Unit | clear validation error |
| BGM missing with BGM required | Unit | clear validation error |
| both output presets | Unit | two timeline outputs |
| invalid schema version | Unit | reject with migration hint |
| deterministic media order | Unit | same seed produces same timeline |

## Dependency Map

- Depends on Phase 1.
- Blocks render engine, CLI, GUI, validation, and package output.

## Success Criteria

- [x] `job.yaml` examples are human-readable and validate.
- [x] Internal timeline has no FFmpeg command strings.
- [x] Presets exist for 1920x1080 and 1080x1920.
- [x] Validation errors tell user exactly what to fix.
- [x] Unit tests cover valid, invalid, and edge-case jobs.

## Risk Assessment

- Risk: schema over-designed. Mitigation: only include fields needed by V1.
- Risk: timeline leaks FFmpeg implementation details. Mitigation: keep it intent-based.
- Risk: future migrations painful. Mitigation: include `version` from day one.

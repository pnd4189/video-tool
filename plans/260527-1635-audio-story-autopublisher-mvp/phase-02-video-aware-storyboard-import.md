---
phase: 2
title: "Video-Aware Storyboard Import"
status: pending
priority: P1
effort: "1-1.5d"
dependencies: [1]
---

# Phase 2: Video-Aware Storyboard Import

## Context Links

- Phase 1 detector: [Chap Folder Detection](./phase-01-chap-folder-detection.md)
- Current storyboard helpers: `src/videotool/core/storyboard.py`
- Current schema: `src/videotool/core/job_spec.py`
- Current timeline compile: `src/videotool/core/timeline.py`
- Current render filter: `src/videotool/render/video_filters.py`

## Overview

Build a deterministic storyboard importer that uses `.work/scene-plan.md` when available and inserts existing video clips for video-marked scenes. Keep output compatible with existing render paths and old jobs.

## Requirements

- Functional: parse scene rows from `.work/scene-plan.md` table.
- Functional: if a row is marked with `✓`, use `Video/videos/scene_NNN.mp4` when present.
- Functional: use image assets for all other scenes.
- Functional: divide voice duration across scenes; last scene absorbs rounding remainder.
- Functional: rotate image motions so every still image moves.
- Functional: default transitions should favor speed and segmented stability (`cut` or `fade`) over heavy crossfade.
- Functional: generate a mapping summary with counts: scene count, image scenes, video scenes, missing videos, missing images.
- Non-functional: backward compatibility for existing `storyboard[].image` jobs.

## Architecture

```text
ChapAssets + voice_duration
  -> parse_scene_plan()
  -> build_audio_story_storyboard()
  -> list[dict] suitable for JobSpec
```

Use the existing renderer's ability to process videos via file extension. The schema field name `image` is misleading; the plan should add a neutral `media` path while accepting old `image` input.

Backward-compatible schema option:

- Add `media: Path | None = None` to `StoryboardSceneSpec`.
- Keep `image: Path | None = None` accepted.
- Add model validation: exactly one of `media` or `image` must resolve to a path; expose a property or normalized field for timeline compile.
- Update `compile_timeline()` to use normalized media path.

If this schema change is too invasive during implementation, keep writing `image:` with video paths for MVP and document a follow-up. Preferred plan is the compatible `media` alias because it removes future confusion.

## Related Code Files

- Modify: `src/videotool/core/job_spec.py` - media alias/backward compatibility.
- Modify: `src/videotool/core/timeline.py` - compile normalized media path.
- Modify: `src/videotool/core/storyboard.py` or create `src/videotool/core/storyboard_import.py` - scene-plan parser and audio-story board builder.
- Modify: `src/videotool/cli/storyboard_commands.py` only if exposing an intermediate command.
- Create: `tests/test_audio_story_storyboard.py`.
- Update: existing storyboard/timeline/render command tests as needed.

## Implementation Steps

1. Write regression tests proving old `storyboard[].image` jobs still load and compile.
2. Write tests for new `media` field using an image and a video path.
3. Write tests for parsing `.work/scene-plan.md` rows with `✓` video markers.
4. Write tests for missing marked video fallback to image plus warning.
5. Implement scene-plan parser as a narrow Markdown table parser; do not use a full Markdown dependency.
6. Implement storyboard builder from `ChapAssets`, voice duration, and scene plan.
7. Add mapping summary data for CLI output.
8. Keep Chap 1 file naming as preferred detection only; test generic `scene_001.mp4` and natural image names.

## Tests Before

- Old schema/job tests for `image` remain green.
- New tests define expected behavior for `media` before changing schema/timeline.
- Parser tests cover table rows with and without video check marks.

## Refactor

- Carefully normalize `StoryboardSceneSpec` media path.
- Avoid broad renames across all code; use local property/helper if smaller.
- Preserve render behavior for existing prompt-generated and auto-generated storyboards.

## Tests After

- Add render-plan dry-run test proving a video scene generates `-stream_loop -1` path in segmented scene command.
- Add test that durations sum to voice duration.
- Add mapping summary test.

## Regression Gate

```bash
.venv/bin/python -m pytest tests/test_job_spec.py tests/test_timeline.py tests/test_ffmpeg_commands.py tests/test_segmented_render.py tests/test_audio_story_storyboard.py
```

## Success Criteria

- [ ] Scene-plan parser handles Chap-style Markdown tables.
- [ ] Video-marked scenes use existing video clips when present.
- [ ] Image scenes use rotating motion.
- [ ] Storyboard durations sum exactly to probed voice duration within rounding.
- [ ] Old `image` jobs remain valid.
- [ ] New `media` jobs are valid if implemented.

## Risk Assessment

- Risk: Markdown table parser is brittle.
  Mitigation: parse only known columns and degrade to image fallback with warnings.
- Risk: schema change breaks existing jobs.
  Mitigation: tests-first backward compatibility and no removal of `image`.
- Risk: scene count mismatch: plan may have 116 rows, images observed 114.
  Mitigation: mapping summary, fallback warnings, last-known/next natural image policy decided in implementation.

## Security Considerations

- Scene-plan text is local input; never execute embedded content.
- Normalize paths under the Chap folder unless user explicitly supplies overrides.

## Next Steps

- Phase 3 wires detector + storyboard builder into `make-youtube`.

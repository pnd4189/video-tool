---
phase: 4
title: "Cover Thumbnail And Package"
status: pending
priority: P1
effort: "0.5-1d"
dependencies: [1, 3]
---

# Phase 4: Cover Thumbnail And Package

## Context Links

- Package flow: `src/videotool/core/services.py`
- Thumbnail helpers: `src/videotool/package/thumbnails.py`
- YouTube package checks: `src/videotool/package/youtube.py`
- Reports: `src/videotool/package/reports.py`

## Overview

Make the upload package fit the audio-story workflow. The primary thumbnail should come from the Chap cover folder when available; generated video frame thumbnails remain fallback candidates.

## Requirements

- Functional: prefer cover image from `Ảnh bìa/` or `cover/` for `outputs/thumbnail-1280x720.jpg`.
- Functional: scale/crop cover to 1280x720.
- Functional: keep existing generated thumbnail candidates as fallback.
- Functional: package should include description, quality report, manifest, captions when available.
- Functional: description should include chapter timestamps when available from `.work/chapters_qa.json` or generated `job.project.chapters`.
- Non-functional: thumbnail generation failure should not poison render, but package should report warning/failure clearly.

## Architecture

```text
ChapAssets.cover_candidates
  -> write_cover_thumbnail()
  -> run_package()
  -> validate_package()
```

Keep cover thumbnail logic in `package/thumbnails.py` or a focused helper. `run_package()` can accept package metadata already stored in `job.yaml`; avoid passing Chap-folder-specific state through every package call if possible.

## Related Code Files

- Modify: `src/videotool/package/thumbnails.py` - cover image thumbnail helper.
- Modify: `src/videotool/core/services.py` or new audio-story service - call cover helper before fallback candidate generation.
- Modify: `src/videotool/package/youtube.py` if package validation needs a clearer thumbnail message.
- Create: `tests/test_cover_thumbnail.py`.
- Update: `tests/test_youtube_package.py` if behavior changes.

## Implementation Steps

1. Write tests for cover image scaling/cropping to 1280x720.
2. Write tests that cover thumbnail wins over generated frame fallback.
3. Write tests for fallback when cover folder is missing.
4. Implement cover thumbnail helper using FFmpeg or existing image/video approach.
5. Wire `make-youtube` package flow to pass/use detected cover.
6. Add chapter description tests if parsing `.work/chapters_qa.json` is implemented in this phase.
7. Preserve current `generate_thumbnail_candidates()` behavior for non-Chap jobs.

## Tests Before

- Existing package tests define current thumbnail expectations.
- New cover tests define priority behavior before implementation.

## Refactor

- Do not replace existing video-frame candidate generation.
- Add cover preference as a narrow branch for audio-story workflow.

## Tests After

- Add package-level test for `thumbnail-1280x720.jpg` from cover.
- Add quality/package test that still passes when only generated thumbnails exist.

## Regression Gate

```bash
.venv/bin/python -m pytest tests/test_cover_thumbnail.py tests/test_youtube_package.py tests/test_cli_commands.py
```

## Success Criteria

- [ ] Cover image is used as primary thumbnail when present.
- [ ] Fallback generated thumbnails still work.
- [ ] Package validator still expects and finds `thumbnail-1280x720.jpg`.
- [ ] Description includes chapters when chapter metadata is available.

## Risk Assessment

- Risk: FFmpeg image handling fails on unusual cover formats.
  Mitigation: support common formats only first: jpg/jpeg/png/webp; warn otherwise.
- Risk: package flow becomes Chap-specific.
  Mitigation: keep generic helpers and pass explicit cover path only from `make-youtube`.

## Security Considerations

- Use argument-list subprocess calls only.
- Do not shell-escape paths manually.
- Treat cover image as untrusted media input; failures should be typed errors.

## Next Steps

- Phase 5 verifies the complete workflow, updates docs, and records smoke commands.

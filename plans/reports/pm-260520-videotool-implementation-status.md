# VideoTool Implementation Status

Date: 2026-05-20

## Summary

- Implemented Python package skeleton, CLI, core job schema, timeline, asset license checks, FFmpeg command/render flow, subtitle utilities, silence analysis, thin GUI queue, and YouTube package checks.
- Fixed review blockers: no implicit faster-whisper model download, stricter path validation, licensed-only asset index requirement, unknown preset failure, ffprobe error mapping, stricter package validation, and removed unsupported burn-in caption mode from the V1 schema.
- Plan status remains `in-progress` because real AI transcription, full GUI workflow, and complete package with `captions.srt` are not fully verified.

## Verification

- `.venv/bin/pytest`: 26 passed.
- `.venv/bin/python -m compileall src`: passed.
- `.venv/bin/videotool doctor --json`: passed, FFmpeg and ffprobe present.
- `scripts/generate-test-media.sh`: generated tiny fixture media.
- `.venv/bin/videotool validate fixtures/generated/job.yaml`: passed.
- `.venv/bin/videotool render fixtures/generated/job.yaml --all`: rendered both 16:9 and 9:16 MP4 outputs.
- `.venv/bin/videotool render fixtures/generated/job.yaml --all --dry-run --json`: valid JSON.
- `.venv/bin/videotool package fixtures/generated/job.yaml`: expected exit 6 because fixture has no `captions.srt`; all other package artifacts passed.
- `.venv/bin/python -m pip wheel . -w /tmp/videotool-wheel`: passed.

## Remaining

- Verify `videotool transcribe` with a local faster-whisper model path.
- Add real GUI web smoke coverage after installing `.[gui]`.
- Add caption generation before package validation for a full all-pass YouTube package.
- Decide whether V1 should implement subtitle burn-in or keep it out until a later phase.

## Storyboard Update

- Added `videotool storyboard plan` to parse image/video prompt `.txt` files into editable `job.yaml` storyboard scenes.
- Scene media convention: save generated assets as `media/scene-001.png`, `media/scene-002.png`, etc.
- Render now supports multiple storyboard scenes, pan/zoom motion, fade/crossfade transitions, both 16:9 and 9:16 outputs, and `srt-and-burn` subtitle mode.

## Docs Impact

- README added with install, scope, CLI quick start, optional extras, FFmpeg requirement, and explicit no-hidden-download transcription note.

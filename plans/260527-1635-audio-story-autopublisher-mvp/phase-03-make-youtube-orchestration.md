---
phase: 3
title: "Make YouTube Orchestration"
status: pending
priority: P1
effort: "1-1.5d"
dependencies: [1, 2]
---

# Phase 3: Make YouTube Orchestration

## Context Links

- Phase 1 detector: [Chap Folder Detection](./phase-01-chap-folder-detection.md)
- Phase 2 storyboard: [Video-Aware Storyboard Import](./phase-02-video-aware-storyboard-import.md)
- CLI entry: `src/videotool/cli/main.py`
- CLI handlers: `src/videotool/cli/commands.py`
- Services: `src/videotool/core/services.py`
- Render flow: `src/videotool/render/segmented.py`

## Overview

Add the user-facing command that turns a Chap folder into a YouTube-ready long-form package. This phase connects existing render/package primitives without creating a visual editor.

## Requirements

- Functional: expose `videotool make-youtube CHAP_PATH --preset audio-story-fast`.
- Functional: create or update `job.yaml` with long-form `youtube-16x9` output only by default.
- Functional: use detected voice, script, image dir, video dir, music, cover, and scene-plan.
- Functional: support `--preview-minutes N` to render only an early preview without committing to the full 107-minute render.
- Functional: support `--dry-run` or equivalent summary mode that writes no video.
- Functional: default captions to `srt-only`, not burn-in.
- Functional: call existing render and package services where possible.
- Non-functional: keep orchestration in a focused service module, not a giant CLI function.
- Non-functional: idempotent enough to re-run after interruption.

## Architecture

```text
videotool make-youtube CHAP
  -> discover_chap_assets()
  -> build job payload
  -> build video-aware storyboard
  -> write job.yaml
  -> optional transcribe/SRT step when model is supplied or script timing exists
  -> render preview/full
  -> package
```

Important decision:

- Do not require Whisper model for MVP. If captions cannot be generated because no model is provided, command should either:
  - skip SRT with a clear warning when `--no-subtitles`, or
  - require an existing `outputs/captions.srt`, or
  - accept `--model` for transcription.

Plan default recommendation:

- For first implementation, do not auto-transcribe unless `--model` is provided.
- If script exists but no timing model exists, generate `job.yaml` and render; package can warn about missing SRT unless `--require-srt` is set.
- Keep SRT generation path using existing `transcribe --script` logic.

## Related Code Files

- Modify: `src/videotool/cli/main.py` - register `make-youtube`.
- Modify: `src/videotool/cli/commands.py` or create `src/videotool/cli/make_youtube_commands.py` - CLI boundary.
- Create: `src/videotool/core/audio_story.py` - orchestration service if needed.
- Modify: `src/videotool/core/services.py` only for shared helper extraction or thin delegation.
- Modify: `src/videotool/core/job_spec.py` if `audio-story-fast` defaults need schema support.
- Create: `tests/test_make_youtube_command.py`.

## Implementation Steps

1. Write CLI tests for `make-youtube --dry-run` on synthetic Chap folder.
2. Write tests that `job.yaml` is created with `youtube-16x9`, `srt-only`, audio defaults, and generated storyboard.
3. Write tests for `--preview-minutes` limiting generated render duration or using a preview job copy.
4. Implement command boundary with typed error handling consistent with other commands.
5. Implement orchestration service that composes Phase 1 and Phase 2 outputs.
6. Wire render/package calls only after dry-run and job creation paths are tested.
7. Ensure rerun behavior overwrites generated storyboard with a warning, not silent surprise.
8. Avoid adding Shorts output to MVP defaults.

## Tests Before

- Existing CLI smoke tests stay green.
- New dry-run tests define command output and job creation before service wiring.
- Test error boundary for missing required Chap folder inputs.

## Refactor

- Extract only the smallest service helpers needed for command orchestration.
- Do not make `run_render()` know about Chap folders; keep it job-based.
- Keep `make-youtube` as a producer of `job.yaml` plus invoker of existing services.

## Tests After

- Add dry-run render plan assertion: large storyboard routes segmented.
- Add preview mode assertion: preview output is bounded and does not mutate full job unexpectedly.
- Add package invocation test with faked existing output files where needed.

## Regression Gate

```bash
.venv/bin/python -m pytest tests/test_cli_smoke.py tests/test_cli_commands.py tests/test_make_youtube_command.py tests/test_segmented_render.py
```

## Success Criteria

- [ ] `videotool make-youtube CHAP --dry-run` reports detected assets and planned outputs.
- [ ] Command writes valid `job.yaml`.
- [ ] Command can produce preview plan/render without CapCut.
- [ ] Command defaults to long-form `youtube-16x9` only.
- [ ] Existing `render`, `package`, `storyboard auto`, and `transcribe` commands keep working.

## Risk Assessment

- Risk: SRT generation requires model path and can block one-command UX.
  Mitigation: make subtitle generation explicit with `--model` or accept pre-existing SRT; do not hide model downloads.
- Risk: preview mode mutates full job.
  Mitigation: write preview into workspace or create transient preview plan.
- Risk: command becomes too large.
  Mitigation: keep CLI boundary thin; test service functions directly.

## Security Considerations

- All subprocess execution remains through existing safe argument-list FFmpeg paths.
- No shell interpolation.
- No automatic network/model downloads.

## Next Steps

- Phase 4 improves package output by prioritizing cover thumbnail and upload artifacts.

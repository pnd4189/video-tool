---
phase: 4
title: "Media Analysis And FFmpeg Render Engine"
status: completed
priority: P1
effort: "3-4d"
dependencies: [1, 2, 3]
---

# Phase 4: Media Analysis And FFmpeg Render Engine

## Context Links

- [Research summary](./research/research-summary.md)
- FFmpeg filters: https://www.ffmpeg.org/ffmpeg-filters.html
- YouTube upload encoding: https://support.google.com/youtube/answer/1722171

## Overview

Implement media probing, render profile selection, FFmpeg command generation, execution, temp workspace handling, and logs. This is the core value of V1.

## Requirements

- Functional: probe audio/video/images, compose 16:9 and 9:16 outputs, match BGM duration, overlay media, add simple transitions, write MP4.
- Non-functional: deterministic commands, clear logs, safe subprocess usage, one final render at a time by default.

## Architecture

```text
Timeline
  -> MediaProbeIndex
  -> RenderProfile
  -> FFmpegGraph
  -> CommandPlan
  -> RenderExecutor
  -> RenderResult
```

Use `subprocess.run([...])` with argument lists. Avoid shell strings. Keep command builder pure and testable.

## Related Code Files

| Action | Path | Purpose | Test Impact |
|---|---|---|---|
| Create | `/home/dung/VIBE_CODING/video-tool/src/videotool/core/media_probe.py` | `ffprobe` wrapper and metadata | Unit/integration |
| Create | `/home/dung/VIBE_CODING/video-tool/src/videotool/render/profiles.py` | CPU/VAAPI render profiles | Unit tests |
| Create | `/home/dung/VIBE_CODING/video-tool/src/videotool/render/ffmpeg_graph.py` | Filtergraph builder | Snapshot tests |
| Create | `/home/dung/VIBE_CODING/video-tool/src/videotool/render/commands.py` | Safe command assembly | Unit tests |
| Create | `/home/dung/VIBE_CODING/video-tool/src/videotool/render/executor.py` | Run FFmpeg, capture logs | Integration |
| Create | `/home/dung/VIBE_CODING/video-tool/src/videotool/render/workspace.py` | Temp/output dirs, cleanup | Unit tests |
| Create | `/home/dung/VIBE_CODING/video-tool/tests/test_ffmpeg_commands.py` | Command tests | New |
| Create | `/home/dung/VIBE_CODING/video-tool/tests/test_render_smoke.py` | Tiny render integration | New |

## Render Profiles

| Profile | Encoder | Use | Default |
|---|---|---|---|
| `libx264-balanced` | `libx264` | reliable YouTube upload | yes |
| `libx264-fast` | `libx264` | draft renders | no |
| `h264-vaapi-draft` | `h264_vaapi` | faster local previews | no |
| `hevc-vaapi-archive` | `hevc_vaapi` | smaller archive files | no |
| `av1-vaapi-experimental` | `av1_vaapi` | future testing | no |

## Implementation Steps

1. Implement `ffprobe` JSON parsing for duration, streams, codec, dimensions, fps, sample rate.
2. Implement input normalization rules: output resolution, fps, SAR/DAR, yuv420p, audio sample rate 48k.
3. Implement background video/image track creation to match voice duration.
4. Implement B-roll/image overlays with start/duration and preset-specific fit mode: cover, contain, blur-pad.
5. Implement simple transitions with `xfade` where safe; default to cuts when durations overlap poorly.
6. Implement BGM loop/trim/fade/duck/mix/normalize chain.
7. Implement subtitle burn-in hook, but allow SRT-only output until Phase 5 exists.
8. Implement temp workspace with preflight disk check and cleanup on success/failure.
9. Add `--dry-run` support returning command plan without executing FFmpeg.
10. Add integration smoke test using synthetic 2-5 second media.

## Function Or Interface Checklist

- `probe_media(path)`
- `MediaMetadata`
- `RenderProfile`
- `build_ffmpeg_command(timeline, profile, output)`
- `RenderExecutor.run(command_plan)`
- `RenderResult`
- `Workspace`

## Test Scenario Matrix

| Scenario | Type | Expected |
|---|---|---|
| image + voice -> MP4 | Integration | playable MP4 |
| BGM shorter than voice | Integration | BGM loops to voice duration |
| BGM longer than voice | Integration | BGM trims to voice duration |
| both aspect ratios | Integration | 1920x1080 and 1080x1920 outputs |
| missing FFmpeg | Unit | clear doctor/preflight failure |
| unsafe path | Security | reject path traversal |
| dry-run | Unit | no output file, command plan returned |

## Dependency Map

- Depends on Phases 1-3.
- Blocks CLI render command, GUI queue, YouTube package validation.

## Success Criteria

- [x] Tiny smoke job renders valid MP4.
- [x] Command builder is covered by snapshot/unit tests.
- [x] Background music duration matches voice duration within acceptable tolerance.
- [x] Render logs include FFmpeg command, profile, duration, output path, and failure reason.
- [x] CPU profile works before VAAPI is considered complete.

## Risk Assessment

- Risk: FFmpeg filtergraph becomes unreadable. Mitigation: split graph builder into small pure functions and snapshot outputs.
- Risk: VAAPI behavior varies by driver. Mitigation: opt-in profiles and benchmark command.
- Risk: long jobs exhaust disk/RAM. Mitigation: preflight checks and one final render at a time.

## Security Considerations

- Use `subprocess` argument arrays, not shell strings.
- Validate paths stay under job/project roots unless user explicitly imports.
- Quote/escape drawtext/subtitle inputs through FFmpeg-safe helpers.

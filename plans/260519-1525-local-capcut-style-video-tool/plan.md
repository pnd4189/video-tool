---
title: "Local CapCut-Style Audio Video Tool"
description: "Build a local Python and FFmpeg video composer with CLI-first workflows, thin GUI, asset licensing, offline subtitles, and YouTube-ready export presets."
status: in-progress
priority: P1
effort: "12-18d"
branch: "main"
tags: [feature, cli, gui, media, ffmpeg, ai, youtube]
blockedBy: []
blocks: []
created: "2026-05-19T08:25:57.768Z"
createdBy: "ck:plan"
source: skill
---

# Local CapCut-Style Audio Video Tool

## Overview

Create a local media tool for repeatable audio-first video production. V1 is not a CapCut clone. It is a CLI-first batch composer with a thin GUI, template/job files, asset license tracking, offline subtitles, FFmpeg render profiles, and YouTube/Shorts export validation.

Primary user flow:
1. Put voice audio, B-roll/images, and background music into a job folder.
2. Generate or edit a `job.yaml` template.
3. Render both `youtube-16x9` and `shorts-9x16` outputs.
4. Produce `.mp4`, `.srt`, thumbnail candidates, render logs, quality report, and license/credits report.

## Scope Decisions

- CLI is the source of truth. GUI wraps the same job API.
- Use Python for orchestration, schemas, CLI, GUI bridge, and tests.
- Use FFmpeg directly through `subprocess`, not MoviePy, for the render core.
- Default encoder: `libx264` for quality and portability. Add VAAPI profiles after local benchmark.
- V1 offline AI: subtitles/transcript, silence detection, optional cut suggestions. Defer video background removal and semantic B-roll search.
- V1 asset policy: manual import first. API download adapters for Pexels/Pixabay/Freesound are post-V1.
- Python modules use `snake_case` because importable Python files cannot use hyphens. CLI commands, docs, templates, and folders use kebab-case where practical.

## Architecture

```text
job.yaml
  -> schema validation
  -> media probing with ffprobe
  -> asset/license index
  -> timeline model
  -> FFmpeg command builder
  -> render executor
  -> subtitle/audio analysis
  -> YouTube package validator
  -> reports and logs
```

Key packages:
- `src/videotool/core/`: job spec, timeline model, media metadata, errors.
- `src/videotool/render/`: FFmpeg graph builder, profiles, executor.
- `src/videotool/assets/`: asset index, license metadata, source adapters.
- `src/videotool/ai/`: transcription and silence detection adapters.
- `src/videotool/cli/`: Typer commands.
- `src/videotool/gui/`: thin local GUI shell.
- `tests/`: unit and integration tests with tiny generated media fixtures.

## Research Inputs

- [Research summary](./research/research-summary.md)
- [Scout report](./reports/scout-report.md)
- [Red-team review](./reports/red-team-review.md)
- [Validation notes](./reports/validation-notes.md)

## Phases

| Phase | Name | Status |
|-------|------|--------|
| 1 | [Project Foundation](./phase-01-project-foundation.md) | Complete |
| 2 | [Job Spec And Timeline Model](./phase-02-job-spec-and-timeline-model.md) | Complete |
| 3 | [Asset Library And License Metadata](./phase-03-asset-library-and-license-metadata.md) | Complete |
| 4 | [Media Analysis And FFmpeg Render Engine](./phase-04-media-analysis-and-ffmpeg-render-engine.md) | Complete |
| 5 | [Offline AI Audio And Subtitle Pipeline](./phase-05-offline-ai-audio-and-subtitle-pipeline.md) | In Progress |
| 6 | [CLI Batch Workflow](./phase-06-cli-batch-workflow.md) | Complete |
| 7 | [Thin GUI And Render Queue](./phase-07-thin-gui-and-render-queue.md) | In Progress |
| 8 | [YouTube Export Validation And Hardening](./phase-08-youtube-export-validation-and-hardening.md) | In Progress |

## Dependencies

- External runtime: FFmpeg 6.1+ and `ffprobe`.
- Python runtime: 3.12+ preferred on this machine.
- Optional AI: default to `faster-whisper` CPU int8; keep `whisper.cpp` as later optional adapter.
- Optional GUI toolkit: default to lightweight local FastAPI web UI with plain HTML.
- No cross-plan dependency detected. Project had no unfinished local or global plans.

## Acceptance Criteria

- [x] One job can render both 1920x1080 and 1080x1920 MP4 outputs from the same audio and asset folder.
- [ ] Background music loops or trims to voice duration, fades cleanly, ducks below voice, and normalizes final audio.
- [ ] Subtitle generation produces valid UTF-8 SRT and optional burn-in captions.
- [x] Asset library records source URL, license, author, commercial-use status, attribution text, and YouTube risk notes.
- [ ] YouTube package contains video, SRT, thumbnail candidate, description draft, render log, quality report, and license report.
- [x] CLI supports single-job render, batch render, dry-run, validate, probe, and package commands.
- [ ] GUI can select a job, preview metadata, start/cancel queued renders, and open output folder.
- [x] Tests cover schema validation, timeline compilation, FFmpeg command generation, asset license checks, and YouTube output validation.

## Out Of Scope For V1

- Full drag-and-drop timeline editor.
- CapCut template compatibility.
- Cloud rendering, account sync, or social auto-upload.
- Video background removal.
- Automatic semantic B-roll retrieval with CLIP/embedding search.
- Built-in TTS engine, except an integration hook for the user's existing TTS tool.

## Open Decisions Before Implementation

- Subtitle style: burn captions into video by default, or provide `.srt` only unless requested.
- Batch policy: render both 16:9 and 9:16 every job by default, or selectable presets.
- TTS integration: CLI hook path/contract for the existing TTS tool.

## Validation Log

- Deep mode selected by user.
- Scout: repo is empty except `.git`; no code patterns or unfinished project plans found.
- Hardware: current OS reports Ryzen 5 7640HS, Radeon 760M, FFmpeg with `libx264`, `h264_vaapi`, `hevc_vaapi`, `av1_vaapi`; current visible RAM is about 14GiB until added RAM is installed.
- Red-team and validation passes are documented in `reports/`.
- User decision update: choose local FastAPI web UI for simplest lightweight GUI; choose `faster-whisper` CPU int8 as subtitle default; choose manual asset import for V1.
- Whole-plan consistency sweep: all phase files use the same V1 scope above; no unresolved contradiction found after red-team/validation edits.
- Implementation pass on 2026-05-19: Python package, CLI, schema/timeline, asset library, FFmpeg render, optional AI adapters, GUI queue, package validator, examples, tests, and README added. Remaining gaps: AI transcription not installed/verified, GUI is a thin queue shell only, package validator correctly fails when captions are missing.

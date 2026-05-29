---
title: "Audio Story Autopublisher MVP"
description: "Add a one-command audio-story workflow that turns a Chap folder into a YouTube-ready long-form video package without CapCut."
status: pending
priority: P1
effort: "4-6d"
branch: "main"
tags: [feature, cli, ffmpeg, youtube, tdd]
blockedBy: []
blocks: [260519-1525-local-capcut-style-video-tool]
created: "2026-05-27T09:35:27.562Z"
createdBy: "ck:plan"
source: skill
---

# Audio Story Autopublisher MVP

## Overview

Build the shortest path from a long audio-story chapter folder to upload-ready YouTube artifacts. The workflow should prioritize narration quality, music bed, thumbnail, deterministic storyboard mapping, and enough visual movement to avoid a static-image presentation. It should not try to become CapCut or a cinematic effects engine.

Target command:

```bash
videotool make-youtube "/path/to/Chap 1" --preset audio-story-fast
```

Primary output:

```text
Chap 1/
├── job.yaml
├── outputs/
│   ├── youtube-16x9.mp4
│   ├── captions.srt
│   ├── thumbnail-1280x720.jpg
│   ├── description.txt
│   ├── quality-report.json
│   └── package-manifest.json
└── .videotool/tmp/
```

## Context Links

- Brainstorm: [Audio Story Autopublisher Brainstorm](../reports/260527-1620-audio-story-autopublisher-brainstorm.md)
- Current summary: [Codebase Summary](../../docs/codebase-summary.md)
- Parent plan: [Local CapCut-Style Audio Video Tool](../260519-1525-local-capcut-style-video-tool/plan.md)
- Completed prerequisite: [videotool P0 feature expansion](../260527-1700-videotool-feature-expansion/plan.md)

## Scope Decisions

- IN: long-form YouTube 16:9 first.
- IN: deterministic Chap folder detection and media mapping.
- IN: image motion, existing video clip insertion, simple fades.
- IN: SRT subtitles, not styled/burned captions by default.
- IN: cover-folder thumbnail preference.
- OUT: CapCut project compatibility.
- OUT: cinematic mưa/gió/sương effects engine.
- OUT: AI image-to-video and semantic B-roll retrieval.
- OUT: Shorts output in the first pass unless explicitly promoted later.
- OUT: monetization guarantee.

## Architecture

```text
Chap folder
  -> chap_folder detector
  -> job.yaml defaults (audio-story-fast)
  -> scene-plan importer / image fallback
  -> video-aware storyboard
  -> existing render pipeline (segmented when large)
  -> cover thumbnail + package
  -> outputs ready for upload
```

Keep the new workflow as orchestration over existing primitives. Add focused modules for folder detection and scene-plan import instead of growing `core/services.py` further.

## Cross-Plan Dependencies

| Relationship | Plan | Status | Reason |
|---|---|---|---|
| Relies on | `260527-1700-videotool-feature-expansion` | Done | Provides dB audio mixer, script SRT, auto storyboard, segmented render |
| Blocks | `260519-1525-local-capcut-style-video-tool` | In progress | Completes the real-input feedback loop for audio-story production |

## Phases

| Phase | Name | Status |
|-------|------|--------|
| 1 | [Chap Folder Detection](./phase-01-chap-folder-detection.md) | Pending |
| 2 | [Video-Aware Storyboard Import](./phase-02-video-aware-storyboard-import.md) | Pending |
| 3 | [Make YouTube Orchestration](./phase-03-make-youtube-orchestration.md) | Pending |
| 4 | [Cover Thumbnail And Package](./phase-04-cover-thumbnail-and-package.md) | Pending |
| 5 | [Validation Docs And Smoke](./phase-05-validation-docs-and-smoke.md) | Pending |

## Dependencies

- FFmpeg and ffprobe available on PATH.
- Existing tests remain green: `.venv/bin/python -m pytest`.
- Real acceptance sample: `/home/dung/cloud/gdrive/YOUTUBE AUDIO/BÌNH THIÊN SÁCH/BINH THIEN SACH - VO TOI/BẢN DỊCH/Chap 1/`.
- No network calls or automatic model downloads.

## Success Criteria

- Chap 1 can be processed with one CLI workflow.
- The command detects voice, script, image folder, video folder, music folder, cover folder.
- The generated storyboard uses scene videos when `.work/scene-plan.md` marks them.
- Image scenes always have visible pan/zoom motion.
- Final long-form video duration matches voice within 1-2 seconds.
- Audio voice is clear; music is lower and ducked.
- `captions.srt`, thumbnail, description, quality report, and manifest are written.
- Full workflow can run without CapCut.

## Validation Strategy

- Tests first in every phase.
- Synthetic temp-dir fixtures for generic Chap folders.
- Chap 1 only used for smoke/manual acceptance, not as a hard unit-test fixture.
- Dry-run command assertions before real render assertions.
- Preview render before full render.

## Risk Notes

- Gdrive mount can stall probing/render. Prefer local staging if smoke shows I/O problems.
- Existing schema field `storyboard[].image` is misleading for video paths. Plan must keep backward compatibility.
- Visual motion reduces static presentation risk but does not guarantee YouTube monetization.
- `core/services.py` is already large; avoid dumping all new orchestration there.

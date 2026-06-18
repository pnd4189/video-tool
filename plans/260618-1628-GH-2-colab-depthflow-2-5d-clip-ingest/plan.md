---
title: "Colab DepthFlow 2.5D clip ingest (parallax-link)"
description: "GPU-rendered loopable 2.5D clips ingested locally via a data-layer scene swap, reusing the render pipeline untouched."
status: done
priority: P2
effort: 6h
branch: feat/parallax-2-5d
tags: [parallax, colab, depthflow, cli, skill, tdd]
created: 2026-06-18
---

# Colab DepthFlow → local 2.5D clip ingest

Render one loopable 2.5D clip per still on Colab (DepthFlow GPU). User downloads → uploads to
`<job>/Parallax/<image-stem>.mp4`. Local `parallax-link` rewrites job.yaml scenes (image → matching
clip) at the **data layer** — zero render-code change. A new `/parallax-video` skill orchestrates the
end-to-end run. `/make-video` and the existing numpy `enhance.parallax` path stay 100% untouched.

## Why this is isolated (verified)
- Render already loop+trims a video scene: `commands.py:91` (`-stream_loop -1 -t`) and `segmented.py:72`. So swapping a scene's media to a video clip needs **no render change**.
- `StoryboardSceneSpec` already accepts `image` OR `video` (`job_spec.py:79-80`); swapped media validates.
- `auto_storyboard` already writes scenes into `data["storyboard"]` with relativized paths (`storyboard_commands.py:83-94`) — `parallax-link` mirrors that exact rewrite shape.

## Phases

| # | Phase | Status | TDD | Link |
|---|-------|--------|-----|------|
| 01 | `parallax-link` CLI (data-layer scene swap) | done | yes (tests-first) | [phase-01](phase-01-parallax-link-cli.md) |
| 02 | `/parallax-video` orchestration skill | done | smoke/manual | [phase-02](phase-02-parallax-video-skill.md) |
| 03 | Colab DepthFlow batch clip script | done | manual (Colab) | [phase-03](phase-03-colab-depthflow-script.md) |
| 04 | Docs + memory update | done | n/a | [phase-04](phase-04-docs-and-memory.md) |

## Dependency graph
- 01 is the only Python core; standalone, no blockers. Tests-first (--tdd).
- 02 depends on 01 (skill calls the new CLI command).
- 03 independent of 01/02 (produces the input clips); can run in parallel.
- 04 depends on 01+02+03 (documents the final command names/contract).

## Scope OUT (explicit)
- Auto rclone sync of clips (transport stays manual: user downloads from Colab → uploads to gdrive).
- GPU `grid_sample` port of the repo's numpy warp (DepthFlow owns GPU warp instead).
- Duration-baked per-scene manifest (loop+trim handles timing; no coupling to voice length).
- Ping-pong loop (only added later if DepthFlow orbit proves non-periodic — POC decides).
- Any change to `enhance.parallax` / `parallaxize_timeline` (separate numpy-local path, left as-is).

## Success criteria (whole plan)
- `videotool parallax-link <job> --clips-dir Parallax` swaps each image scene with a matching clip, leaves missing ones as stills, never crashes, idempotent.
- Existing 141-test suite still green; new tests cover the swap matrix.
- `/parallax-video <folder>` produces a 16:9 h264/aac mp4 at correct resolution, subtitles/showwaves/atmosphere intact.
- Colab script emits loopable 1080p clips named `<stem>.mp4`, clips-only (no assemble).

## Key files
- New: `src/videotool/core/parallax_link.py` (core), CLI wiring in `cli/main.py` + `cli/commands.py`, tests in `tests/test_parallax_link.py`.
- New: `/parallax-video` skill (sibling of the video skill — see phase-02 for located path).
- New: `Colab/v4_depthflow_clips_colab.py`.
- Edit: `CLAUDE.md` (AGENTS.md) + planner memory (phase-04).

## Unresolved questions
See each phase's "Next steps"; consolidated in phase-03 (DepthFlow loop-seamlessness, clip length).

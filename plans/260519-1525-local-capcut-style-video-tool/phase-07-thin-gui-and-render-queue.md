---
phase: 7
title: "Thin GUI And Render Queue"
status: in-progress
priority: P2
effort: "2-3d"
dependencies: [1, 2, 6]
---

# Phase 7: Thin GUI And Render Queue

## Context Links

- FastAPI docs: https://fastapi.tiangolo.com/

## Overview

Add a thin GUI for selecting jobs, previewing metadata, starting/canceling renders, and viewing logs. The GUI must not become a separate editor in V1.

## Requirements

- Functional: choose job folder, validate, show media summary, choose presets, render queue, cancel, open output folder, show logs.
- Non-functional: reuses CLI/services, no duplicate render logic, responsive during FFmpeg runs.

## Architecture Decision

Use local FastAPI web UI with plain HTML templates. This is lighter to iterate than PySide6, avoids large Qt wheels, and fits the CLI-first model because the UI only calls existing services.

## Related Code Files

| Action | Path | Purpose | Test Impact |
|---|---|---|---|
| Create | `/home/dung/VIBE_CODING/video-tool/src/videotool/gui/app.py` | GUI entry point | Smoke test |
| Create | `/home/dung/VIBE_CODING/video-tool/src/videotool/gui/queue.py` | Render queue adapter | Unit tests |
| Create | `/home/dung/VIBE_CODING/video-tool/src/videotool/gui/state.py` | Job/UI state model | Unit tests |
| Create | `/home/dung/VIBE_CODING/video-tool/tests/test_gui_queue.py` | Queue tests | New |
| Modify | `/home/dung/VIBE_CODING/video-tool/pyproject.toml` | Optional `gui` deps | Install test |

Create:
- `src/videotool/gui/web_app.py`
- `src/videotool/gui/static/`
- `src/videotool/gui/templates/`

## Implementation Steps

1. Add optional `gui` dependency group with FastAPI/Uvicorn/Jinja only.
2. Add `videotool gui` command to launch localhost UI.
3. Implement job picker and job validation display.
4. Show media/asset/license summary before render.
5. Implement render queue with one active render, pending jobs, cancel request, and status log tail.
6. Add buttons for render all presets, dry-run, open output folder.
7. Add error display that maps service errors to actionable messages.
8. Add smoke tests for queue state transitions.

## Function Or Interface Checklist

- `launch_gui()`
- `RenderQueue`
- `RenderJobState`
- `enqueue_job(job_path, presets)`
- `cancel_job(job_id)`
- `get_job_status(job_id)`

## Test Scenario Matrix

| Scenario | Type | Expected |
|---|---|---|
| enqueue one job | Unit | state pending -> running -> completed |
| cancel pending job | Unit | state canceled |
| render failure | Unit | state failed with error |
| invalid job selected | UI/service | validation shown, render disabled |
| GUI optional deps missing | CLI | actionable install message |

## Dependency Map

- Depends on CLI/services from Phase 6.
- Does not block YouTube validation, but makes local workflow easier.

## Success Criteria

- [ ] GUI launches from CLI.
- [ ] User can select existing job and run validation.
- [x] User can enqueue render for both presets.
- [ ] GUI displays render progress/log tail and final output location.
- [x] No render/business logic is duplicated in GUI layer.

## Risk Assessment

- Risk: GUI scope expands into timeline editor. Mitigation: no timeline editing in V1.
- Risk: GUI blocks during FFmpeg. Mitigation: background process/thread and status polling.
- Risk: packaging optional deps complicates CLI. Mitigation: separate `gui` extra.

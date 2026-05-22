---
phase: 1
title: "Project Foundation"
status: completed
priority: P1
effort: "1.5-2d"
dependencies: []
---

# Phase 1: Project Foundation

## Context Links

- [Plan overview](./plan.md)
- [Scout report](./reports/scout-report.md)
- [Research summary](./research/research-summary.md)

## Overview

Create the minimal Python project skeleton, developer commands, docs baseline, and generated media test fixtures. This phase creates the ground rules without committing to heavy UI or AI dependencies.

## Requirements

- Functional: installable local Python package, CLI entry point placeholder, test runner, lint/type check command, generated media fixtures.
- Non-functional: no large binary media in git, no secrets, reproducible commands, Python 3.12 compatible.

## Architecture

Use a small package layout:

```text
src/videotool/
  __init__.py
  cli/
  core/
  render/
  assets/
  ai/
  gui/
tests/
examples/
docs/
scripts/
```

Do not add render logic here. Only make the project runnable and testable.

## Related Code Files

| Action | Path | Purpose | Test Impact |
|---|---|---|---|
| Create | `/home/dung/VIBE_CODING/video-tool/pyproject.toml` | Package metadata, dependencies, scripts | Enables all tests |
| Create | `/home/dung/VIBE_CODING/video-tool/README.md` | Quick start and V1 scope | Docs check |
| Create | `/home/dung/VIBE_CODING/video-tool/src/videotool/__init__.py` | Package marker/version | Import test |
| Create | `/home/dung/VIBE_CODING/video-tool/src/videotool/cli/__init__.py` | CLI package marker | Import test |
| Create | `/home/dung/VIBE_CODING/video-tool/src/videotool/cli/main.py` | Typer app stub | CLI smoke test |
| Create | `/home/dung/VIBE_CODING/video-tool/tests/test_cli_smoke.py` | Minimal CLI test | New |
| Create | `/home/dung/VIBE_CODING/video-tool/scripts/generate-test-media.sh` | Tiny FFmpeg fixture generator | Integration fixtures |
| Create | `/home/dung/VIBE_CODING/video-tool/.gitignore` | Ignore outputs, temp files, venvs | Prevents media churn |

## Implementation Steps

1. Create `pyproject.toml` with minimal dependencies: `typer`, `pydantic`, `rich`, `pytest`. Do not add AI/GUI deps yet.
2. Add optional dependency groups: `ai`, `gui`, `dev` instead of installing everything by default.
3. Create package folders and a CLI stub: `videotool --help`, `videotool version`, `videotool doctor`.
4. Add `doctor` checks for Python version, FFmpeg, ffprobe, available encoders, disk space, and RAM.
5. Add `.gitignore` for `.venv/`, `outputs/`, `tmp/`, generated media, logs, cache, model files.
6. Add `scripts/generate-test-media.sh` to create tiny synthetic audio/video fixtures with FFmpeg.
7. Add README with V1 scope, install commands, and first CLI examples.
8. Add initial tests for package import and CLI smoke.

## Function Or Interface Checklist

- `videotool.cli.main.app`
- `videotool.cli.main.version`
- `videotool.cli.main.doctor`
- `scripts/generate-test-media.sh`

## Test Scenario Matrix

| Scenario | Type | Expected |
|---|---|---|
| `videotool --help` | CLI smoke | exits 0 |
| `videotool version` | CLI smoke | prints package version |
| `videotool doctor` with FFmpeg installed | CLI integration | reports FFmpeg/ffprobe status |
| generated fixtures | Script integration | creates tiny files under ignored fixture dir |

## Dependency Map

- Blocks all later phases.
- No dependency on AI, GUI, or asset APIs.

## Success Criteria

- [x] Project installs in a local venv.
- [x] `videotool --help`, `videotool version`, and `videotool doctor` run.
- [x] `pytest tests/test_cli_smoke.py` passes.
- [x] Generated fixture script creates small media and leaves no tracked binary files.
- [x] README states V1 boundaries and hardware assumptions.

## Risk Assessment

- Risk: adding too many dependencies at the foundation. Mitigation: optional groups only.
- Risk: generated fixtures accidentally committed. Mitigation: `.gitignore` and tests use temp dirs.
- Risk: global kebab-case rule conflicts with Python imports. Mitigation: document snake_case exception for importable modules.

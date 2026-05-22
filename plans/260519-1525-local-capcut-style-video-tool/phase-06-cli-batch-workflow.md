---
phase: 6
title: "CLI Batch Workflow"
status: completed
priority: P1
effort: "2d"
dependencies: [1, 2, 3, 4, 5]
---

# Phase 6: CLI Batch Workflow

## Context Links

- Typer docs: https://typer.tiangolo.com/
- [Plan overview](./plan.md)

## Overview

Expose the core engine through a scriptable CLI. This is the primary interface for V1 and the contract the GUI must reuse.

## Requirements

- Functional: create/init job, validate, probe, transcribe, render, batch render, package, doctor, benchmark.
- Non-functional: stable exit codes, useful logs, dry-run mode, no hidden GUI dependency.

## Architecture

```text
videotool
  doctor
  init-job
  validate
  probe
  transcribe
  analyze-audio
  render
  batch
  package
  benchmark
```

All commands call service functions. Commands should contain argument parsing and output formatting only.

## Related Code Files

| Action | Path | Purpose | Test Impact |
|---|---|---|---|
| Modify | `/home/dung/VIBE_CODING/video-tool/src/videotool/cli/main.py` | Root command registration | CLI tests |
| Create | `/home/dung/VIBE_CODING/video-tool/src/videotool/cli/commands.py` | Command handlers | CLI tests |
| Create | `/home/dung/VIBE_CODING/video-tool/src/videotool/core/services.py` | Reusable orchestration services | Unit tests |
| Create | `/home/dung/VIBE_CODING/video-tool/src/videotool/core/logging.py` | Structured console/log output | Unit tests |
| Create | `/home/dung/VIBE_CODING/video-tool/tests/test_cli_commands.py` | CLI behavior tests | New |
| Create | `/home/dung/VIBE_CODING/video-tool/tests/test_batch_workflow.py` | Batch tests | New |

## CLI Contract Draft

```bash
videotool doctor
videotool init-job ./jobs/video-001 --voice voice.wav --media ./media --music bgm.mp3
videotool validate ./jobs/video-001/job.yaml
videotool probe ./jobs/video-001/job.yaml
videotool transcribe ./jobs/video-001/job.yaml --model small
videotool render ./jobs/video-001/job.yaml --preset youtube-16x9 --dry-run
videotool render ./jobs/video-001/job.yaml --all
videotool batch ./jobs --all --jobs 1
videotool package ./jobs/video-001/job.yaml
videotool benchmark ./jobs/video-001/job.yaml --profiles libx264-balanced,h264-vaapi-draft
```

## Implementation Steps

1. Implement command structure with Typer and Rich output.
2. Define exit codes: config error, missing dependency, render failure, license block, validation failure.
3. Implement `init-job` to create job folder and template without copying large assets unless requested.
4. Implement `validate` as a non-rendering preflight.
5. Implement `render` with `--preset`, `--all`, `--dry-run`, `--overwrite`, `--output-dir`.
6. Implement `batch` with default `--jobs 1` for final renders and resumable status files.
7. Implement `benchmark` for CPU vs VAAPI profiles using a short segment.
8. Add machine-readable `--json` output for automation.

## Function Or Interface Checklist

- `run_validate(job_path)`
- `run_probe(job_path)`
- `run_render(job_path, presets, dry_run)`
- `run_batch(root, jobs)`
- `run_package(job_path)`
- CLI exit code constants

## Test Scenario Matrix

| Scenario | Type | Expected |
|---|---|---|
| valid job dry-run | CLI | exits 0, prints command plan |
| invalid job | CLI | non-zero and useful message |
| license blocked | CLI | non-zero with blocked asset ids |
| render all presets | CLI integration | creates both outputs |
| batch with one failed job | CLI | continues or stops per flag |
| `--json` output | Unit | valid JSON |

## Dependency Map

- Depends on Phases 1-5.
- Blocks GUI, because GUI must call the same services.

## Success Criteria

- [x] CLI can run full job flow without GUI.
- [x] Batch render is deterministic and logs per job.
- [x] Dry-run works without writing output media.
- [x] Exit codes distinguish validation, license, dependency, and render failures.
- [x] CLI tests cover happy path and failures.

## Risk Assessment

- Risk: CLI commands become business logic. Mitigation: keep services separate.
- Risk: batch rendering overwhelms machine. Mitigation: default final render concurrency is 1.
- Risk: output overwrite destroys previous work. Mitigation: require `--overwrite` or timestamped output folders.

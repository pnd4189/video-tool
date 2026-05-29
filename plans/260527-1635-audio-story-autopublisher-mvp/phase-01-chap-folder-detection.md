---
phase: 1
title: "Chap Folder Detection"
status: pending
priority: P1
effort: "1d"
dependencies: []
---

# Phase 1: Chap Folder Detection

## Context Links

- Brainstorm: [Audio Story Autopublisher Brainstorm](../reports/260527-1620-audio-story-autopublisher-brainstorm.md)
- Codebase: [Codebase Summary](../../docs/codebase-summary.md)
- Current CLI: `src/videotool/cli/main.py`
- Current services: `src/videotool/core/services.py`
- Current job schema: `src/videotool/core/job_spec.py`

## Overview

Add a small detector that turns a Chap folder into a structured set of source assets. This phase does not render; it only identifies files and exposes predictable data for later phases.

## Requirements

- Functional: detect voice, script, image directory, video directory, music candidates, cover candidates, outro candidates, `.work/scene-plan.md`, and `.work/chapters_qa.json`.
- Functional: prefer `*_qa.wav`, then largest `.wav`, then `*_qa.mp3`, then largest audio outside `Instrument/`.
- Functional: prefer `Image/`, `Video/videos/`, `Instrument/`, `Ảnh bìa/`, `Ảnh end video/` when present.
- Functional: return warnings for optional missing assets; fail only when voice or images are missing.
- Non-functional: no network calls, no media decoding beyond cheap metadata needed later.
- Non-functional: deterministic natural sort and stable output for tests.

## Architecture

Create a focused detector module rather than growing `core/services.py`.

```text
chap_path
  -> discover_chap_assets()
  -> ChapAssets dataclass
  -> later phases create job/storyboard/package
```

`ChapAssets` should contain paths relative or absolute enough for downstream job creation. Keep path decisions explicit in the plan implementation: use absolute paths for inspection output, relativize when writing `job.yaml`.

## Related Code Files

- Create: `src/videotool/core/chap_folder.py` - detection dataclasses and heuristics.
- Modify: `src/videotool/cli/main.py` - later command hook placeholder only if needed by phase sequencing.
- Modify: `src/videotool/cli/commands.py` - later command handler hook placeholder only if needed.
- Create: `tests/test_chap_folder_detection.py` - synthetic folder tests.

## Implementation Steps

1. Write tests for a synthetic Chap folder with `Image/`, `Video/videos/`, `Instrument/`, `Ảnh bìa/`, voice/script, and `.work` files.
2. Write tests for fallback order: `*_qa.wav`, largest `.wav`, `*_qa.mp3`, largest non-instrument audio.
3. Write tests for missing optional directories producing warnings, not failures.
4. Implement `ChapAssets` and `discover_chap_assets(chap_path: Path)`.
5. Reuse existing natural sort logic if practical; otherwise add a tiny local helper and avoid broad refactors.
6. Keep path handling compatible with folder names containing spaces and Vietnamese characters.
7. Add a no-render inspection helper for later CLI use.

## Tests Before

- Add tests that describe expected detection output before wiring command behavior.
- Add tests for generic folder names, not only `Chap 1`.
- Add tests for tie/fallback order without reading real gdrive media.

## Refactor

- Do not refactor existing render services in this phase.
- If natural sort helper is moved or reused, preserve existing `storyboard auto` tests.

## Tests After

- Add edge tests for empty image folder and missing voice.
- Add test that `Video/videos/scene_001.mp4` is detected even though top-level depth differs.

## Regression Gate

```bash
.venv/bin/python -m pytest tests/test_chap_folder_detection.py tests/test_storyboard_autogen.py
```

## Success Criteria

- [ ] `discover_chap_assets()` detects all Chap 1-style asset categories on synthetic fixtures.
- [ ] Missing voice or images returns typed validation failure.
- [ ] Missing music/video/cover/outro returns warnings or empty lists.
- [ ] Existing storyboard auto tests still pass.

## Risk Assessment

- Risk: detector hardcodes Chap 1 names too tightly.
  Mitigation: tests use generic names and only use Chap 1 conventions as preferred patterns.
- Risk: gdrive mount makes probing slow.
  Mitigation: phase only inspects names/sizes; delay heavy ffprobe to existing render/probe paths.

## Security Considerations

- Treat all folder paths as local filesystem input.
- Do not execute or shell-parse discovered paths.
- Avoid logging huge file lists by default.

## Next Steps

- Phase 2 consumes `ChapAssets` to build video-aware storyboard entries.

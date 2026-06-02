---
phase: 1
title: Music gain default -30
status: completed
priority: P2
effort: 20m
dependencies: []
---

# Phase 1: Music gain default -30

## Overview
Lower the default background-music bed from −28 dB to −30 dB so the gentle bed sits further under
narration. Global default change (applies to every job that does not override `music_gain_db`).

## Requirements
- Functional: `AudioSpec.music_gain_db` default = `-30.0`.
- Non-functional: zero behavior change for jobs that explicitly set `music_gain_db`.

## Architecture
Single source of truth = the pydantic default at `core/job_spec.py:87`. The value flows through
`audio_settings()` → `build_audio_graph()` → `volume={x}dB`. No other code path hardcodes −28.

## Related Code Files
- Modify: `src/videotool/core/job_spec.py` (line 87 default + comment)
- Modify: `tests/test_audio_db_mixer.py` (assertion + test name)
- Modify: `tests/test_segmented_render.py` (line 148 assertion)

## Implementation Steps
1. TDD (red): update `tests/test_audio_db_mixer.py::test_default_music_gain_is_minus_28_db` →
   rename to `_minus_30_db`, assert `"volume=-30.0dB" in command`. Update
   `tests/test_segmented_render.py:148` to `"[2:a]volume=-30.0dB"`. Run → fail.
2. Change `music_gain_db: float = -28.0` → `-30.0`; reword comment to mention −30 dB.
3. Run full suite → green.

## Success Criteria
- [ ] `grep -rn "\-28\.0dB\|minus_28" tests/ src/` returns nothing.
- [ ] `pytest -q` passes.
- [ ] Jobs overriding `music_gain_db` still emit their own value (no regression).

## Risk Assessment
Trivial. Only risk = a stale −28 assertion elsewhere; mitigated by the grep gate in Success Criteria.

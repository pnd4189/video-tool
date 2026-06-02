---
phase: 1
title: "Enhance schema and tier-light lock"
status: done
priority: P1
effort: "3-4h"
dependencies: []
---

# Phase 1: Enhance schema and tier-light lock

## Overview
Add the `enhance` block (master `tier` switch) to the job schema and thread it into the Timeline, changing **nothing** about render output for `tier: light`. TDD: lock current behavior first so phases 3-4 cannot regress it.

## Requirements
- Functional: `enhance.tier: light | full` parses; default `light`. Optional per-feature overrides `subtitles/particles/progress_bar/visualizer: bool | None` (None = follow tier).
- Non-functional: `tier: light` produces byte-identical ffmpeg commands to today (inline + segmented). `extra="forbid"` preserved.

## Architecture
- New `EnhanceSpec(BaseModel)` in `core/job_spec.py` mirroring sibling specs (`model_config = ConfigDict(extra="forbid")`). Field `tier: Literal["light","full"] = "light"`; four `bool | None = None` overrides.
- `JobSpec` gets `enhance: EnhanceSpec = Field(default_factory=EnhanceSpec)`.
- A small resolver `EnhanceSpec.is_on(feature) -> bool`: returns override if set, else `tier == "full"`.
- `Timeline` (`core/timeline.py`) gains `enhance_tier: str = "light"` + resolved booleans (or carry the EnhanceSpec). Keep frozen dataclass; populate in `Timeline.from_job`.
- Master template (`job_spec.py:160` write_job_template) stays unchanged (no enhance key written → default light).

## Related Code Files
- Modify: `src/videotool/core/job_spec.py` (add EnhanceSpec + field)
- Modify: `src/videotool/core/timeline.py` (carry enhance flags into Timeline.from_job)
- Create: `tests/test_enhance_tier.py` (lock light == current)
- Modify: `tests/test_job_spec.py` (default tier light, override parsing, forbid-extra)

## Implementation Steps
1. **Test first (lock):** in `test_enhance_tier.py`, build a job with >40 scenes, assert `build_segmented_render(...).mux_command` contains `-c:v copy` and has no `subtitles=`/`-filter_complex` video map. Build a small job, assert inline command unchanged vs a captured baseline. Run — must pass on current code (no enhance yet → default light).
2. Add `EnhanceSpec` + `JobSpec.enhance` + `is_on()` resolver.
3. Thread into `Timeline.from_job` (store `enhance_tier` + resolved flags; default light).
4. Add `test_job_spec.py` cases: default tier == "light"; explicit overrides; unknown key under `enhance` rejected (forbid-extra).
5. Run full suite — all 66+ existing tests + new must pass, output identical for light.

## Success Criteria
- [x] `enhance` block parses; default `tier: light`; overrides honored by `is_on()`
- [x] tier-light inline + segmented commands byte-identical to pre-change baseline (locked by test)
- [x] forbid-extra still rejects unknown keys
- [x] full suite green (86 passed)

## Risk Assessment
- Risk: Timeline is frozen → adding fields needs default values to avoid breaking other constructors. Mitigation: default `enhance_tier="light"` + flags False.
- Risk: hidden coupling where Timeline built without from_job. Mitigation: grep constructors; give every new field a safe default.

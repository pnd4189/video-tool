---
phase: 1
title: Output presets shorts opt-in
status: completed
priority: P1
effort: 1h
dependencies: []
---

# Phase 1: Output presets shorts opt-in

## Overview
Stop auto-producing `shorts-9x16`. Default outputs = `youtube-16x9` only; Shorts is
added only when the user explicitly asks.

## Requirements
- Functional: a default `/make-video` run produces only `youtube-16x9.mp4`; no shorts file.
- Functional: Shorts appears only when a hint contains `shorts` / `9x16` / `--all`.
- Non-functional: no behavior change for jobs that already list `shorts-9x16` in `outputs`.

## Architecture
Two template writers seed `outputs` with both presets today; the skill then renders
`--all`. Fix both seed points + the skill instruction. The render CLI already supports
per-preset selection (`--preset`), so no CLI change is needed.

## Related Code Files
- Modify: `src/videotool/core/job_spec.py` — `write_job_template` (line ~158) `outputs` seed.
- Modify: `src/videotool/cli/storyboard_commands.py` — `plan_storyboard` (line ~28) `outputs` seed.
- Modify: `.claude/commands/make-video.md` — step 4 default render = `--preset youtube-16x9`;
  shorts only on hint.
- Modify: `AGENTS.md` — "Standard pipeline" render step + a note under decisions.

## Implementation Steps
1. In `write_job_template`, change `outputs` from
   `[{"preset": "youtube-16x9"}, {"preset": "shorts-9x16"}]` to `[{"preset": "youtube-16x9"}]`.
2. In `plan_storyboard`, change the `outputs` list the same way.
3. In `make-video.md`: replace `render "$JOB" --all` with `render "$JOB" --preset youtube-16x9`.
   Add a rule: if the user hint contains shorts/9x16/all, append `{preset: shorts-9x16}` to
   `outputs` in job.yaml AND render that preset too.
4. In `AGENTS.md` "Standard pipeline" step 4, mirror the render change; add a one-line
   "Confirmed decision (2026-05-29): no auto Shorts — youtube-16x9 only unless asked".
5. Run `.venv/bin/python -m pytest -q` — fix any template-snapshot test asserting two presets
   (update expectation to single preset; this is the intended change, not a regression).

## Success Criteria
- [ ] `init-job` + `storyboard plan` emit `outputs: [youtube-16x9]` only.
- [ ] Skill renders only youtube-16x9 by default; documented shorts opt-in path.
- [ ] Full test suite green.

## Risk Assessment
- Template snapshot tests may assert both presets → update them. Low risk.
- A user relying on automatic Shorts loses it silently → mitigated by the documented hint.

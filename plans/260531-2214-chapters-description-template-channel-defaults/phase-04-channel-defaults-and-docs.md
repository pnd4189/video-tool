---
phase: 4
title: Channel defaults and docs
status: completed
priority: P2
effort: 2h
dependencies:
  - 1
  - 2
  - 3
---

# Phase 4: Channel defaults and docs

## Overview
Make the audio-story flow produce full output by default: seed `enhance` (showwaves + subtitles,
no progress bar), wire `description_template` + `script` (vi.txt), and run `transcribe` before
`render` when captions are missing. Document the agent-authored recap/summary step and the
confirmed-decision changes.

## Requirements
- Functional: `/make-video` for an audio-story folder seeds job.yaml with
  `enhance: {visualizer: true, subtitles: true, progress_bar: false}`, `inputs.script` → detected
  `*_vi.txt`, `inputs.description_template` → channel template when present.
- Functional: flow runs `transcribe` (whisper `base`) before `render` whenever `enhance.subtitles`
  is on and `outputs/captions.srt` is missing (otherwise render raises).
- Functional: agent (Claude) authors `project.recap_previous` (from previous tập vi.txt) and
  `project.description` (this tập summary) before package.
- Non-functional: global `EnhanceSpec` defaults UNCHANGED (other users keep tier-light); only the
  make-video seeding turns features on. Music −30 already global from Phase 1.

## Architecture
- `.claude/commands/make-video.md` (+ mirror `.gemini/commands/make-video.toml`): extend the
  documented pipeline — seed enhance block, detect `*_vi.txt` as `inputs.script`, detect channel
  `_DESCRIPTION_TEMPLATE.txt` as `inputs.description_template`, insert `transcribe` step before
  `render`, and the recap/summary authoring step (Claude reads prev+current vi.txt → fills fields).
- `CLAUDE.md`/`AGENTS.md` (symlinked): update "Standard pipeline", "Confirmed project decisions"
  (music −30dB; channel default = showwaves+subtitles, progress bar dropped; chapters from
  transcript W1), and "Known pitfalls" (description-template placeholders must exist;
  chapters.json emitted by transcribe).
- `docs/project-changelog.md` + `docs/project-roadmap.md`: add entries.
- The user inserts `{{CHAPTERS}}` / `{{RECAP_PREV}}` / `{{SUMMARY}}` into their
  `_DESCRIPTION_TEMPLATE.txt` once (documented in make-video.md); not a code change.

## Related Code Files
- Modify: `.claude/commands/make-video.md`
- Modify: `.gemini/commands/make-video.toml`
- Modify: `CLAUDE.md` (== AGENTS.md)
- Modify: `docs/project-changelog.md`
- Modify: `docs/project-roadmap.md`

## Implementation Steps
1. Update `make-video.md` pipeline: enhance seeding, vi.txt/template detection, transcribe-before-
   render, recap/summary authoring. Mirror essentials into the `.toml`.
2. Update `CLAUDE.md` decisions + pitfalls + pipeline (keep under ~150 lines per its own rule).
3. Add changelog + roadmap entries.
4. Smoke check: run `videotool validate` on a seeded sample job (allow-missing-local) → passes;
   `videotool doctor` OK. Run full `pytest -q` → green.

## Success Criteria
- [ ] `/make-video` doc produces a job.yaml that renders showwaves+subtitles, no progress bar.
- [ ] transcribe runs before render when subtitles on + srt missing (no render raise).
- [ ] CLAUDE.md reflects music −30, channel default, chapters-from-transcript; ≤150 lines.
- [ ] Changelog + roadmap updated.
- [ ] `pytest -q` green; `videotool validate` on sample passes.

## Risk Assessment
- Doc/config only (no new runtime code) → low risk. Main risk = drift between `make-video.md` and
  `.toml`; mitigate by mirroring the same steps.
- Long-audio whisper is slow; flow should state this so the user expects render time (not a bug).

---
phase: 5
title: "Validation Docs And Smoke"
status: pending
priority: P1
effort: "0.5-1d"
dependencies: [1, 2, 3, 4]
---

# Phase 5: Validation Docs And Smoke

## Context Links

- README: `README.md`
- Codebase summary: `docs/codebase-summary.md`
- Roadmap: `docs/project-roadmap.md`
- Changelog: `docs/project-changelog.md`
- Brainstorm: [Audio Story Autopublisher Brainstorm](../reports/260527-1620-audio-story-autopublisher-brainstorm.md)

## Overview

Verify the complete audio-story workflow, document the new command, and run a real preview smoke on Chap 1 before any full 107-minute render.

## Requirements

- Functional: full test suite passes.
- Functional: CLI help documents `make-youtube`.
- Functional: README includes the audio-story fast workflow.
- Functional: docs mention no CapCut requirement for MVP.
- Functional: Chap 1 preview smoke command is documented with exact path.
- Non-functional: do not run full 107-minute render as a mandatory automated test.
- Non-functional: report any unverified parts honestly.

## Architecture

Validation sits at three levels:

```text
unit tests -> dry-run/preview smoke -> optional full Chap 1 render
```

Use synthetic fixtures for automated tests. Use Chap 1 only as manual/acceptance smoke because it lives on gdrive and is large.

## Related Code Files

- Modify: `README.md`.
- Modify: `docs/codebase-summary.md`.
- Modify: `docs/project-roadmap.md`.
- Modify: `docs/project-changelog.md`.
- Optional create: `plans/reports/*audio-story-smoke*.md` after smoke.
- No source changes unless earlier phases missed doc-visible behavior.

## Implementation Steps

1. Run targeted phase tests.
2. Run full test suite.
3. Run `videotool make-youtube --help` or Typer test equivalent.
4. Run dry-run on synthetic Chap fixture.
5. Run preview smoke on Chap 1 for 3-5 minutes if assets are locally accessible.
6. Inspect output artifacts: video duration, SRT existence, thumbnail, package files, quality report.
7. Update README with shortest production command.
8. Update docs/codebase-summary with new modules and flow.
9. Update roadmap/changelog to reflect promoted/deferred items.
10. Write smoke report if any real render was run.

## Tests Before

- Capture current full suite state before final docs/smoke.
- Confirm no pending failing tests are hidden.

## Refactor

- No planned refactor in this phase.
- If docs reveal command naming mismatch, fix command docs or command name, not both ad hoc.

## Tests After

- Full suite:

```bash
.venv/bin/python -m pytest
```

- CLI smoke:

```bash
.venv/bin/videotool make-youtube --help
```

- Chap 1 preview smoke, exact flags decided after implementation:

```bash
.venv/bin/videotool make-youtube "/home/dung/cloud/gdrive/YOUTUBE AUDIO/BÌNH THIÊN SÁCH/BINH THIEN SACH - VO TOI/BẢN DỊCH/Chap 1" --preset audio-story-fast --preview-minutes 5
```

## Regression Gate

```bash
.venv/bin/python -m pytest
```

## Success Criteria

- [ ] Full suite passes.
- [ ] README documents `make-youtube`.
- [ ] `docs/codebase-summary.md` matches implemented flow.
- [ ] Roadmap/changelog updated for the new promoted workflow.
- [ ] Preview smoke result is recorded, or inability to run it is explicitly reported.
- [ ] Final implementation report states what changed, what is left, and what is uncertain.

## Risk Assessment

- Risk: full Chap 1 render takes hours and blocks validation.
  Mitigation: preview smoke is required; full render is manual acceptance unless user asks to run it.
- Risk: docs overpromise no YouTube policy risk.
  Mitigation: state that motion reduces static presentation risk but cannot guarantee monetization.
- Risk: README and docs drift.
  Mitigation: update docs only after final CLI behavior is known.

## Security Considerations

- Do not commit generated media, `.env`, credentials, or model files.
- Do not include private gdrive file contents in public docs; use path examples carefully.

## Next Steps

- If plan is approved, implement with `/ck:cook /home/dung/VIBE_CODING/video-tool/plans/260527-1635-audio-story-autopublisher-mvp/plan.md --tdd`.

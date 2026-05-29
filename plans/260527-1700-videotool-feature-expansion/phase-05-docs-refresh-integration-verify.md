---
phase: 5
title: "Docs refresh + integration verify"
status: done
priority: P2
effort: "0.5d"
dependencies: [1, 2, 3, 4]
---

# Phase 5: Docs refresh + integration verify

## Overview

Close out P0: refresh the stale `docs/codebase-summary.md`, run the full test
suite green, and run the brainstorm's acceptance commands against the Chap 1
folder (dry-run for the heavy render) to confirm the four features work together.

## Requirements

- `docs/codebase-summary.md` reflects reality: it must list `core/storyboard.py`
  (prompt + new auto-gen), the new `AudioSpec`/`inputs.script`, segmented render
  (`render/segmented.py` if created) + `run_segmented`, `ai/align_script.py`,
  `gui/app.py` (exists, FastAPI stub), and the CLI surface (`storyboard plan`,
  `storyboard auto`, `transcribe --script`, `gui`).
- All tests green (43 existing + new from P1–P4).
- Acceptance dry-runs pass on Chap 1.

## Architecture

Docs-only + verification phase. No production code changes (bug fixes surfaced
here loop back to the owning phase, not patched ad hoc).

## Related Code Files

- Modify: `docs/codebase-summary.md`
- (Verify only) entire `src/videotool/**`, `tests/**`

## Implementation Steps

1. Run `pytest` — confirm all green.
2. Update `docs/codebase-summary.md`: module map, CLI commands, job.yaml schema
   (new `audio:` block, `inputs.script`), render paths (inline vs segmented),
   subtitle-from-script flow. Remove stale claims.
3. Acceptance on Chap 1 (set `assets.policy: allow-missing-local`, job.yaml inside
   the chapter folder):
   - `storyboard auto job.yaml --images-dir Image` → ~114 scenes, Σduration ≈ voice.
   - `transcribe job.yaml --model … --script …_qa.txt` → `outputs/captions.srt`,
     `validate_srt == []`.
   - `render job.yaml --dry-run` → segmented plan (114 clips + mux), audio graph
     shows configured dB/duck/loudnorm.
   - (optional, time-permitting) a real short render of a 2–3 scene trimmed job to
     confirm the segmented executor end-to-end.
4. If any acceptance step fails → fix in the owning phase (1–4), re-run, then
   resume here. Do not patch around failures in this phase.

## Success Criteria

- [ ] `docs/codebase-summary.md` matches the shipped code (no stale entries).
- [ ] Full suite green.
- [ ] All four Chap 1 acceptance commands succeed (render via dry-run).
- [ ] No `_v2`/duplicate modules introduced; all touched files <200 lines.

## Risk Assessment

- Acceptance render is long (107-min real-time); rely on `--dry-run` for the full
  chapter and a trimmed job for a real end-to-end smoke. Full render is a manual
  user step, not a CI gate.

# Phase 04 — Docs + memory update

## Context links
- Plan overview: [plan.md](plan.md)
- Depends on: phases 01-03 (documents the final command names + clip contract).
- Targets: `CLAUDE.md` (== `AGENTS.md`, symlinked), `docs/project-changelog.md`,
  `docs/project-roadmap.md`, planner agent memory.

## Overview
- Priority: P3. Status: done.
- Record the new `parallax-video` flow + `parallax-link` command + Colab v4 clip contract as a
  CONFIRMED DECISION in AGENTS.md, and add a changelog entry + a planner memory pointer. Keep
  edits minimal (AGENTS.md must stay ~150 lines per its own rule).

## Key insights
- AGENTS.md is symlinked to `CLAUDE.md`/`GEMINI.md` — edit one, all three see it. Edit `CLAUDE.md`.
- The existing 2.5D parallax decision (2026-06-15, numpy-local `enhance.parallax`) is separate and
  MUST be left intact. The new entry is an ADDITION describing the Colab-clip path, not a reversal.
- Decision entries in AGENTS.md carry a date — use 2026-06-18.

## Requirements
1. AGENTS.md "Confirmed project decisions": add ONE concise entry describing:
   - Colab DepthFlow GPU renders loopable 1080p clips → `Parallax/<stem>.mp4` (manual transport).
   - `videotool parallax-link <job> --clips-dir Parallax` swaps image scenes → matching clips at
     the data layer (missing → Ken Burns); render reuses existing loop+trim.
   - `/parallax-video` is the orchestrating command; `/make-video` + numpy `enhance.parallax`
     unchanged.
   - Date 2026-06-18.
2. Optionally add a one-line pitfall if relevant (e.g. clips must be named `<image-stem>.mp4` to
   match) — only if it does not push AGENTS.md over its length budget.
3. `docs/project-changelog.md`: add a dated feat entry.
4. `docs/project-roadmap.md`: tick the parallax/Colab item if one exists (read first).
5. Planner memory: add a `project`-type memory file + MEMORY.md pointer noting this isolated
   Colab-ingest path exists (so future sessions don't confuse it with `enhance.parallax`).

## Related code files
Modify:
- `CLAUDE.md` (AGENTS.md).
- `docs/project-changelog.md`, `docs/project-roadmap.md` (read first; tick only real items).
- Planner memory: `.claude/agent-memory/planner/MEMORY.md` + a new topic file
  (e.g. `colab-depthflow-clip-ingest.md`).
Do NOT touch: `src/`, `make-video.md`, the 2026-06-15 numpy-parallax decision text.

## Implementation steps
1. Read current AGENTS.md "Confirmed project decisions" + line count.
2. Append the new dated decision entry (3-4 lines max). Trim elsewhere only if over budget.
3. Add changelog entry under the current date.
4. Read roadmap; tick a matching item only if it genuinely exists.
5. Write planner project-memory file + MEMORY.md index line. Distinguish from `enhance.parallax`.

## Manual verification (NOT unit-testable — stated explicitly)
- Docs/memory only → no pytest. Verify by re-reading: AGENTS.md still ~150 lines, new entry dated
  2026-06-18, the 2026-06-15 numpy entry untouched, changelog/roadmap consistent.

## Todo
- [ ] AGENTS.md decision entry (2026-06-18).
- [ ] Changelog feat entry.
- [ ] Roadmap tick (only if a real item exists).
- [ ] Planner memory file + MEMORY.md pointer.

## Success criteria
- A future session reading AGENTS.md learns the Colab-clip path exists, how to invoke it, and that
  it is distinct from `enhance.parallax`. Docs internally consistent; AGENTS.md within budget.

## Risk assessment
| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|-----------|
| AGENTS.md exceeds ~150 lines | Med | Low | Keep entry to 3-4 lines; push detail to this plan/docs. |
| Future agent conflates the two parallax paths | Med | Med | Explicitly contrast Colab-clip vs numpy `enhance.parallax` in both AGENTS.md and memory. |
| Roadmap tick for a non-existent item | Low | Low | Read roadmap first; tick only real items. |

## Security
- Docs only; no secrets, no code paths affected.

## Next steps
- Final phase — closes the plan once 01-03 land.
- No follow-ups beyond the POC open questions tracked in phase-03.

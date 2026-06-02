---
phase: 3
title: Description template renderer
status: completed
priority: P2
effort: 3h
dependencies:
  - 2
---

# Phase 3: Description template renderer

## Overview
Render `outputs/description.txt` from the channel's fixed template via simple placeholder
substitution: `{{CHAPTERS}}` (timestamps from Phase 2), `{{RECAP_PREV}}` and `{{SUMMARY}}`
(agent-authored prose). Keep the existing generic `write_description` for non-template jobs.

## Requirements
- Functional: when `inputs.description_template` is set, read it, substitute the three placeholders,
  write `outputs/description.txt`. Unset placeholders → replaced with empty string (no leftover `{{…}}`).
- Functional: `{{CHAPTERS}}` block = lines `MM:SS Title` (or `HH:MM:SS` past 1h), sourced from
  `outputs/chapters.json` when present, else `job.project.chapters`.
- Functional: when `inputs.description_template` unset → existing `write_description` path unchanged.
- Non-functional: no LLM in tool; recap/summary are plain inputs.

## Architecture
- `core/job_spec.py`:
  - `InputSpec`: add `description_template: Path | None = None`.
  - `ProjectSpec`: add `recap_previous: str = ""`. Reuse existing `description` for this-tập summary.
  - Placeholder→source map (validated): `{{RECAP_PREV}}` ← `project.recap_previous` (NEW template
    section "TÓM TẮT TẬP TRƯỚC"); `{{SUMMARY}}` ← `project.description` (existing "TÓM TẮT TẬP"
    section); `{{CHAPTERS}}` ← chapters block. Both recap fields authored by agent from vi.txt.
- `package/youtube.py`:
  - `format_chapters_block(chapters: list[tuple[float,str]]) -> str` — reuse `_format_chapter_timestamp`.
  - `render_description_template(template_text: str, *, chapters_block: str, recap_prev: str, summary: str) -> str`
    — literal `str.replace` of `{{CHAPTERS}}`/`{{RECAP_PREV}}`/`{{SUMMARY}}`.
- `core/services.py` `run_package`:
  - Load chapters: prefer `outputs/chapters.json`, else `job.project.chapters`.
  - If `job.inputs.description_template` set → read template (resolve vs job dir), render, write
    `outputs/description.txt`. Else keep current `write_description(...)` call.
- `core/validation.py`: add `inputs.description_template` to existing-path candidates so a missing
  template fails validation early (consistent with intro/ending/particle handling).

## Related Code Files
- Modify: `src/videotool/core/job_spec.py` (InputSpec + ProjectSpec fields)
- Modify: `src/videotool/package/youtube.py` (renderer + chapters block helper)
- Modify: `src/videotool/core/services.py` (`run_package` template branch + chapters.json load)
- Modify: `src/videotool/core/validation.py` (template path candidate)
- Create: `tests/test_description_template.py`

## Implementation Steps
1. Tests (red) in `tests/test_description_template.py`:
   - `render_description_template` replaces all 3 placeholders; missing value → empty; no `{{` left.
   - `format_chapters_block` formats `00:00`/`HH:MM:SS` correctly, one line per chapter.
   - Integration: job with `inputs.description_template` + a `chapters.json` → `run_package` writes
     description.txt containing first line `00:00`, recap text, summary text.
   - Job WITHOUT `description_template` → output identical to current `write_description` (back-compat).
2. Add job_spec fields; add validation candidate.
3. Implement helpers in `youtube.py`; branch `run_package`.
4. Run full suite → green.

## Success Criteria
- [ ] Template job → description.txt with timestamp block, recap, summary; zero leftover `{{…}}`.
- [ ] chapters.json takes precedence over `project.chapters`; falls back when absent.
- [ ] Non-template jobs byte-identical to current description output.
- [ ] Missing template path fails `validate` with a clear error.
- [ ] `pytest -q` passes.

## Risk Assessment
- Placeholder names must match what the user inserts into `_DESCRIPTION_TEMPLATE.txt`; confirm exact
  tokens with the real template during implementation (open question carried from brainstorm).
- `str.replace` is dumb by design (KISS); no nested/templating engine — acceptable for fixed template.

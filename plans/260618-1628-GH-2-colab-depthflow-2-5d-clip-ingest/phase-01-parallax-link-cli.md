# Phase 01 — `parallax-link` CLI (data-layer scene swap) — TDD

## Context links
- Plan overview: [plan.md](plan.md)
- Brainstorm spec: `plans/reports/from-brainstorm-to-planner-260618-1628-GH-2-colab-depthflow-2-5d-clip-ingest-report.md`
- Verified code: `src/videotool/core/job_spec.py:73-100`, `src/videotool/cli/storyboard_commands.py:51-114`, `src/videotool/render/commands.py:85-91`, `src/videotool/render/video_filters.py:9-10`.

## Overview
- Priority: P1 (only Python core; everything else depends on it).
- Status: done.
- Add a CLI command `videotool parallax-link <job> --clips-dir Parallax` that rewrites the job's
  storyboard at the data layer: each scene whose media is an **image** with a matching
  `<clips-dir>/<stem>.<videoext>` is swapped to use that video clip; scenes with no match (or that
  are already video) are left untouched. Render code is NOT touched — `commands.py:91` already
  loop+trims a video scene to its `duration`, so the swapped clip auto-loops/trims.

## Key insights
- Storyboard scenes are YAML mappings with an `image` OR `video` key (`job_spec.py:79-80`,
  `require_media` at `:96-100`). Swapping replaces the `image` key with a `video` key.
- `auto_storyboard` already shows the rewrite pattern: load YAML → mutate `data["storyboard"]` →
  `JobSpec.model_validate(data)` → write back with `yaml.safe_dump(..., sort_keys=False,
  allow_unicode=True)` (`storyboard_commands.py:64-95`). Mirror that exactly for consistency.
- Paths in scenes are stored **relative to the job dir** (`_relative_or_original`,
  `storyboard_commands.py:110-114`). The clip path must be relativized the same way so the
  emitted job.yaml stays portable and `validate` resolves it.
- `is_image` keys off suffix in `{.jpg,.jpeg,.png,.webp}` (`video_filters.py:9-10`). Stem match
  must be **case-insensitive on extension** and use the file stem only.
- Idempotency: a re-run must be a no-op once swapped. Because a swapped scene now has a `video`
  key (no `image`), the "image scene" filter naturally skips it — so re-runs are inherently safe;
  a test must lock this.

## Requirements
Functional:
1. For each storyboard scene with an `image` key, compute `stem = Path(image).stem`; if
   `<clips-dir>/<stem>.<ext>` exists for any video ext (`.mp4 .mov .mkv .webm`), replace the
   scene's `image` key with `video` pointing at that clip (relativized to job dir). Keep
   `scene`, `duration`, `transition`, `caption`. Force `motion: static` (clip carries its own
   motion — matches how `auto_storyboard`/`parallaxize_timeline` treat clips).
2. Missing clip → scene unchanged (renders as Ken Burns still).
3. Scene already keyed `video` (existing b-roll) → untouched, never double-processed.
4. `--clips-dir` resolves relative to the job dir when not absolute (mirror `_job_input_path`).
5. Re-validate via `JobSpec.model_validate(data)` before writing; write back preserving all other
   keys, `sort_keys=False`, `allow_unicode=True`.
6. Print a one-line summary: swapped N, missing M, skipped-video K.
7. Missing `clips-dir` → clear error (non-zero exit), not a traceback.

Non-functional: ~30-50 lines core in a new module; no new deps; no torch needed locally.

## Architecture
Data flow:
```
job.yaml ──load──> dict ──link_parallax_clips(data, clips_dir, job_dir)──> dict' ──validate──> job.yaml
                          │  for scene in data["storyboard"]:
                          │    if "image" in scene and clip_for(stem) exists:
                          │       scene = {scene, video: rel(clip), duration, motion:"static", transition, caption}
                          │    else: leave as-is
```
- Core fn lives in `src/videotool/core/parallax_link.py` (pure-ish: takes loaded dict + dirs,
  returns new list + counts). Keeps it unit-testable without touching disk for the YAML round-trip
  logic, while a thin wrapper in `cli/storyboard_commands.py` (or a new `cli` fn) does file IO.
- CLI surface: register `@app.command("parallax-link")` in `cli/main.py` delegating to a
  `commands.parallax_link(...)` that returns an int exit code (match existing pattern at
  `main.py:49-51`, `commands.py:53`).

## Related code files
Create:
- `src/videotool/core/parallax_link.py` — `link_parallax_clips(scenes, clips_dir, job_dir)` core +
  clip-lookup helper.
- `tests/test_parallax_link.py` — TDD tests (written FIRST, see below).
Modify:
- `src/videotool/cli/main.py` — add `parallax-link` command (~5 lines, mirror `validate`).
- `src/videotool/cli/commands.py` — add `parallax_link(job_path, clips_dir)` returning exit code.
- `src/videotool/cli/storyboard_commands.py` — house the file-IO wrapper (reuse
  `_relative_or_original` / `_job_input_path` there to avoid DRY violation), OR import them.
Do NOT touch: `render/parallax.py`, `render/commands.py`, `render/segmented.py`, `core/storyboard.py`.

## Implementation steps (TESTS FIRST)
1. **Write `tests/test_parallax_link.py` before any impl.** Cases (all use `tmp_path`, write a
   minimal job.yaml + fake clip files with `write_bytes(b"x")`, mirror style of
   `test_storyboard_autogen.py`):
   - (a) **image scene + matching clip → swapped**: scene gains `video: Parallax/<stem>.mp4`,
     loses `image`, `motion == "static"`, `duration`/`transition` preserved; result validates.
   - (b) **missing clip → unchanged**: image scene with no matching clip keeps its `image` key.
   - (c) **non-image scene → untouched**: a scene already keyed `video` (b-roll) is byte-identical
     after the run.
   - (d) **stem match rules**: clip `<stem>.MP4` (uppercase ext) still matches; clip with a
     different stem does NOT match; an image `foo.jpg` matches `foo.mp4` not `foobar.mp4`.
   - (e) **idempotent**: run twice; second run swaps 0, output identical to first run.
   - (f) **path stays relative to job dir** (assert emitted `video` is `Parallax/<stem>.mp4`, not
     absolute) — locks portability.
   - (g) **missing clips-dir → non-zero exit / clear error** (via the CLI-level fn).
2. Run the suite; confirm the new tests FAIL (red) for the right reason (ImportError / missing fn).
3. Implement `link_parallax_clips` core to make (a)-(f) pass.
4. Wire `cli/commands.py` + `cli/main.py`; make (g) pass.
5. Run full suite — 141 existing + new must all pass. No regressions.

## Todo
- [ ] Write `tests/test_parallax_link.py` (cases a-g) — FIRST.
- [ ] Confirm red.
- [ ] Implement `core/parallax_link.py` core fn + clip lookup.
- [ ] Add `commands.parallax_link` (exit codes mirror `CONFIG_ERROR=2`).
- [ ] Register `parallax-link` in `main.py`.
- [ ] Full `pytest -q` green (141 + new).

## Success criteria
- All 7 test cases pass; existing 141 unaffected.
- `videotool parallax-link <job> --clips-dir Parallax` produces a valid job.yaml whose image scenes
  with matching clips now reference the clips, others unchanged. Idempotent. No crash on
  missing/misnamed clips.

## Risk assessment
| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|-----------|
| Swapped scene fails `require_media` (both keys present) | Low | High | Build a fresh scene dict with only `video` (drop `image`); test (a) asserts no `image` key. |
| Relative-path mismatch breaks `validate` | Med | Med | Reuse `_relative_or_original`; test (f) locks relative output. |
| Double-swap on re-run | Low | Med | Swapped scenes carry `video` not `image` → skipped; test (e). |
| Clip ext case / stem collision | Med | Low | Case-insensitive ext, exact-stem match; test (d). |

## Security
- Pure local file path manipulation; no network, no torch, no shell. Only reads clip existence and
  rewrites a YAML the user owns. No secret handling.

## Next steps
- Unblocks phase-02 (skill calls this command).
- Code comments/test names describe behavior only (no plan/phase/finding references), per repo rule.

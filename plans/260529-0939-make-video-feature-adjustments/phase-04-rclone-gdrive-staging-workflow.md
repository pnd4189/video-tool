---
phase: 4
title: rclone gdrive staging workflow
status: completed
priority: P1
effort: 2h
dependencies: []
---

# Phase 4: rclone gdrive staging workflow

## Overview
When the asset folder lives on a gdrive **mount**, copy it to a local staging dir, run the
pipeline locally (fast disk), publish outputs back to an `Output/` subfolder of the original
gdrive folder, then delete the local staging copy. Never delete anything on the mount.

This is skill/AGENTS orchestration only — no core Python changes.

## Requirements
- Functional: detect a gdrive mount path (e.g. under `/home/dung/cloud/gdrive/...`).
- Functional: stage assets to a local dir, render there, then copy `outputs/` →
  `<original-gdrive-folder>/Output/`.
- Functional: delete ONLY the local staging dir afterward; report freed space + final paths.
- Non-functional (SAFETY): never run `rm`/delete against the mount path. Staging dir must be
  outside the mount.

## Architecture
The `make-video` skill gains a staging pre/post-amble around the existing 4-step pipeline.
Detection: if the input folder path starts with the known mount root (or is on a fuse/rclone
mount), treat it as remote-staged. Staging root: `~/.cache/videotool/<job-name>/`.

```
detect mount → cp -a "<gdrive folder>"/. "<staging>"/   (assets to local)
run pipeline on <staging> (init→storyboard→validate→render→package)
mkdir -p "<gdrive folder>/Output"
cp -a "<staging>/outputs"/. "<gdrive folder>/Output"/    (publish back)
rm -rf "<staging>"                                       (local only)
report: gdrive Output path + bytes reclaimed
```

## Related Code Files
- Modify: `.claude/commands/make-video.md` — add the staging workflow + safety rules.
- Modify: `AGENTS.md` — document the gdrive-staging flow under "Standard pipeline" (or a new
  "When assets live on gdrive" section) + a confirmed-decision line dated 2026-05-29.
- No `src/` changes.

<!-- Updated: Validation Session 1 - asset auto-detect (intro/ending/music folder) lives in skill -->

## Asset auto-detection (skill, runs on the staged local copy)
The skill inspects the folder and writes resolved paths into `job.yaml` before storyboard:
- **intro thumbnail** → filename/subfolder matching `thumb*` (no-text template).
- **ending image** → matching `*end*` / `outro` / "ảnh end".
- **music** → always point `inputs.music` at the `music/` folder (validation decision); all
  tracks inside get concatenated + looped (phase 3).
- **Fallback (validation decision):** if intro/ending is absent OR multiple ambiguous
  candidates, SKIP that image, render normally, and note the skip in the final report.
  Not an error, no prompt.

## Implementation Steps
1. In `make-video.md`, add a "Staging (gdrive mount)" section:
   - Detect: input path under the gdrive mount root → staged mode; else run in place.
   - Stage with `cp -a` (or `rclone copy` if a remote syntax is ever used) to
     `~/.cache/videotool/<job-name>/`. Use absolute paths.
   - Run the 4-step pipeline against the staging dir.
   - Publish: `mkdir -p "<original>/Output"` then copy the whole `outputs/` into it.
   - Cleanup: `rm -rf` the staging dir ONLY. Explicit rule: never `rm` under the mount.
   - Report: final gdrive `Output/` path, list of artifacts, local bytes reclaimed.
2. In `AGENTS.md`, mirror the workflow + add a "Known pitfall": never delete on the mount;
   `Output/` is a sibling of the asset subfolders, not mixed into them.
3. Manually validate the cp/rm command shapes against a representative path with spaces and
   Vietnamese characters (quote every path).

## Success Criteria
- [ ] Skill copies a gdrive job to local staging before rendering.
- [ ] Outputs land in `<original-gdrive-folder>/Output/` after render.
- [ ] Local staging dir removed; report states freed space + final paths.
- [ ] No delete command ever targets the mount (documented + reviewed).

## Risk Assessment
- Paths with spaces / Vietnamese diacritics → always quote; use `cp -a` to preserve names.
- Disk space for staging large jobs (100+ 4K images + audio) → note in skill; stage under
  `~/.cache` (local fast disk), assume sufficient space, surface ENOSPC clearly.
- Accidental mount deletion is the highest-severity risk → hard rule + only `rm -rf` the
  computed staging path, never a path derived from the input folder.

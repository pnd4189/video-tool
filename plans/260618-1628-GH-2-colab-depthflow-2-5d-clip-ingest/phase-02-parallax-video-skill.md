# Phase 02 — `/parallax-video` orchestration skill

## Context links
- Plan overview: [plan.md](plan.md)
- Depends on: [phase-01](phase-01-parallax-link-cli.md) (the new `parallax-link` command).
- Mirror source: `/home/dung/VIBE_CODING/video-tool/.claude/commands/make-video.md` (the project-level slash command — VERIFIED location).
- Pipeline reference: `AGENTS.md` "Standard pipeline" + "When assets live on gdrive".

## Overview
- Priority: P2. Status: done.
- A new project slash command `/parallax-video <folder>` that runs the SAME 4-step pipeline as
  `/make-video` plus one inserted step: `parallax-link` after `storyboard auto`. It is a sibling
  file `/home/dung/VIBE_CODING/video-tool/.claude/commands/parallax-video.md`. `make-video.md`
  itself is NOT edited.

## Key insights
- `/make-video` is a markdown command file (not a Python skill); it reads `AGENTS.md` and runs the
  CLI. `/parallax-video` is the same shape — only the step list differs by one line.
- The ONLY pipeline difference: after `storyboard auto` writes scenes, call
  `videotool parallax-link "$JOB" --clips-dir Parallax`. Everything downstream (validate, render,
  package, CTA, subtitles, showwaves, atmosphere, gdrive staging) is reused verbatim.
- Render needs NO torch because the clips are pre-rendered on Colab — local just loop+trims them
  (`commands.py:91`). This is the whole point of the isolated design.
- The user must have already placed clips in `<job>/Parallax/<stem>.mp4` (manual transport from
  Colab). The skill should detect the `Parallax/` folder; if absent, it still runs (every scene
  falls back to Ken Burns) and warns that no clips were found.

## Requirements
Functional:
1. Same folder inspection + gdrive staging rules as `make-video.md` (reuse the text; gdrive
   staging uses `rclone copy` per memory, not `cp -r` — see Risk).
2. Steps: stage → `init-job` → patch job.yaml (same channel defaults) → `storyboard auto`
   (`--images-dir Image [--videos-dir Video]`) → **`parallax-link "$JOB" --clips-dir Parallax`** →
   transcribe (if subtitles on) → `validate` → `render --preset youtube-16x9` → `package`.
3. Detect `<job>/Parallax/`; if missing or empty, warn ("no parallax clips found — rendering
   stills as Ken Burns") and continue. Never block.
4. Report: which scenes used a parallax clip vs fell back (from `parallax-link` summary line),
   plus the standard make-video report (mp4 path, thumbnail, description, chapter count, codec
   check).
5. Frontmatter `name: parallax-video`, a `description` and `argument-hint` mirroring make-video.

Non-functional: keep the file lean (~40 lines); defer detail to AGENTS.md like make-video does.

## Architecture
Orchestration flow (only the bolded step is new vs make-video):
```
folder → [stage if gdrive] → init-job → patch job.yaml → storyboard auto
        → ** parallax-link --clips-dir Parallax **        (image scene → matching Parallax/<stem>.mp4)
        → [transcribe] → validate → render → package → report
```
- Clips contract is owned by phase-03 (Colab). The skill assumes clips are already on disk under
  `Parallax/` (manual upload). No clip generation happens locally.

## Related code files
Create:
- `/home/dung/VIBE_CODING/video-tool/.claude/commands/parallax-video.md`.
Read for context (do not edit):
- `.claude/commands/make-video.md`, `AGENTS.md`.
Do NOT edit:
- `make-video.md`, any `src/`.

## Implementation steps
1. Copy `make-video.md` structure; rename frontmatter to `parallax-video`; adjust `description`
   to mention 2.5D parallax-clip ingest.
2. In the execution-rules step list, insert after `storyboard auto`:
   `Run \`videotool parallax-link "$JOB" --clips-dir Parallax\` — swaps each image scene for a
   matching \`Parallax/<stem>.mp4\` clip; missing clips stay as Ken Burns stills.`
3. Add a "Parallax clips" note: clips come from the Colab DepthFlow script (phase-03), uploaded
   manually to `<folder>/Parallax/`. If the folder is missing, warn + continue.
4. Keep the gdrive-staging block but use `rclone copy` (per memory `gdrive-staging-use-rclone-not-cp`).
5. Add `Parallax/` to the list of staged subfolders so clips travel with assets when staging.

## Smoke / manual verification (NOT unit-testable — stated explicitly)
This phase ships a markdown command, not code → no pytest. Verify by:
- (smoke) On a tiny folder with 2 images + 1 hand-made `Parallax/<stem>.mp4` (any short clip),
  run the steps manually; confirm `parallax-link` swaps that one scene and `render` produces a
  16:9 h264/aac mp4 (`ffprobe ... codec_name,width,height`).
- (manual) Confirm the missing-`Parallax/` path warns and still renders (all stills).
- Confirm `/make-video` on the same folder is byte-for-byte unaffected (it never calls
  `parallax-link`).

## Todo
- [ ] Create `.claude/commands/parallax-video.md` mirroring make-video.
- [ ] Insert the `parallax-link` step after `storyboard auto`.
- [ ] Document the `Parallax/` clip contract + missing-folder fallback.
- [ ] Use `rclone copy` for gdrive staging; include `Parallax/` in staged subfolders.
- [ ] Smoke-run on a 2-image folder + 1 fake clip.

## Success criteria
- `/parallax-video <folder>` runs end-to-end, swaps image scenes with present clips, falls back
  for missing ones, produces a correct-resolution h264/aac mp4 with subtitles/showwaves/atmosphere
  intact.
- `/make-video` output unchanged.

## Risk assessment
| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|-----------|
| User forgets to upload clips | Med | Low | Missing-folder warning + Ken Burns fallback; documented. |
| gdrive `cp -r` 60× slower than rclone | High if cp used | Med | Use `rclone copy` per memory; stage `Parallax/` too. |
| Skill drifts from make-video as that file evolves | Med | Low | Both defer to AGENTS.md; only the inserted step is skill-specific. |
| Stem mismatch (Colab names clip differently) | Med | Med | Phase-03 fixes clip name = `<input-stem>.mp4`; `parallax-link` summary surfaces misses. |

## Security
- No new secrets. gdrive staging only ever `rm -rf` the LOCAL cache path (never the mount) — carry
  over the non-negotiable safety rule from make-video/AGENTS.md verbatim.

## Next steps
- Depends on phase-01 command existing.
- Clip naming contract is set in phase-03; keep the two in sync (stem-based match).
- Documented in phase-04.

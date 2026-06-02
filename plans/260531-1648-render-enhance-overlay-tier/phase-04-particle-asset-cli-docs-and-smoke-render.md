---
phase: 4
title: "Particle asset CLI docs and smoke render"
status: done
priority: P2
effort: "4-6h"
dependencies: [3]
---

# Phase 4: Particle asset CLI docs and smoke render

## Overview
Make tier-full usable end-to-end: resolve the particle source, expose the tier flag on the CLI, prove a real render works (ffprobe + eyeball), and update CLAUDE.md so the reversed decisions are documented as tier-scoped.

## Requirements
- Functional: `videotool render <job> --enhance full` (or `enhance.tier: full` in job.yaml) produces an mp4 with visible burned subs, particle motion, progress bar.
- Functional: particle source resolves with zero required binary asset by default.
- Non-functional: real h264 + aac + correct resolution (ffprobe-verified).

## Architecture
<!-- Updated: Validation Session 1 - particle = bundled real CC0 loops (not procedural); whisper default model = base -->
- **Particle source:** bundle a small license-safe default overlay loop in repo under `src/videotool/assets/overlays/dust.mp4`, scaled to preset at render. Record source+license in `src/videotool/assets/overlays/SOURCES.md`. Override via `inputs.particle_overlay: <path>`.
- **CLI:** add `--enhance light|full` to the `render` command in `cli/main.py`; precedence = CLI flag > job `enhance.tier` > default light.
- **Docs:** update `CLAUDE.md` "Confirmed project decisions": no-whisper / no-waveform now apply to **tier light only**; tier full opts into Whisper-aligned subs + visualizer. Add a tier-full line to "Standard pipeline". Keep file < 150 lines.
- **Smoke:** a short fixture job (few images, ~30s voice, tiny txt) rendered at tier full.

## Related Code Files
- Modify: `src/videotool/render/overlay_graph.py` + `src/videotool/core/services.py` (particle source resolution)
- Modify: `src/videotool/core/job_spec.py` (`inputs.particle_overlay: str | None = None`)
- Modify: `src/videotool/cli/main.py` (`--enhance` flag)
- Modify: `CLAUDE.md` (tier-scoped decisions + pipeline note)
- Modify: `tests/test_cli_commands.py` / `tests/test_cli_smoke.py` (flag plumbs to tier)

## Implementation Steps
1. **Test first:** assert `--enhance full` sets `enhance.tier=full` on the loaded job / render path; default keeps light. Assert `inputs.particle_overlay` optional + forbid-extra safe.
2. Implement particle source resolution (bundled default; honor `inputs.particle_overlay` when set).
3. Add `--enhance` CLI flag with documented precedence.
4. Build the fixture job; run `.venv/bin/videotool render <job> --enhance full --preset youtube-16x9`.
5. Verify: `ffprobe -v error -show_entries stream=codec_name,width,height -of csv=p=0 <out.mp4>` → h264 + aac + correct res; open frame to confirm subs + particle + bar visible.
6. Benchmark whisper model size on a longer clip; note recommended `--model` in docs. Deferred: no local model installed; `base` remains the documented default.
7. Update `CLAUDE.md`; run full suite.

## Success Criteria
- [x] `--enhance full` renders an mp4: ffprobe h264 + aac + correct resolution
- [x] burned subtitles + particle motion + progress bar visibly present
- [x] particle works with no user-supplied asset (bundled CC0 loop default; `SOURCES.md` records license)
- [x] CLAUDE.md documents tier-scoped no-whisper/no-waveform + tier-full pipeline step
- [x] full test suite green (`.venv/bin/python -m pytest -q`)

## Implementation Notes (done 2026-05-31)
- Added `inputs.particle_overlay` and validation; unset jobs use bundled `src/videotool/assets/overlays/dust.mp4`.
- Added render CLI `--enhance light|full`; CLI flag overrides the job tier for that render only.
- Smoke rendered `/tmp/videotool-phase4-smoke-QU9Odf/outputs/youtube-16x9.mp4`; ffprobe: `h264,1920,1080` + `aac`; extracted frame confirmed burned subtitle, grain/particle texture, and progress bar.
- Verified targeted render/CLI/schema tests (`42 passed`) and full suite (`103 passed`).
- Preserved per-feature override contract: resolved feature flags can force overlay rendering even when `tier: light`; default light remains unchanged.

## Risk Assessment
- Risk: procedural particles look cheap / wrong. Mitigation: keep subtle (low opacity); `inputs.particle_overlay` escape hatch for a real loop.
- Risk: tier-full smoke render slow on dev machine. Mitigation: tiny fixture (few scenes, short voice); long-form timing only documented, not gated in CI.
- Risk: ffmpeg filter typo only surfaces at real render (unit tests check strings, not execution). Mitigation: this phase's smoke render is the execution gate before marking the plan done.

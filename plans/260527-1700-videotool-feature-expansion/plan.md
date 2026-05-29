---
title: "videotool P0 — dB mixer, storyboard auto-gen, segmented render, script subtitles"
description: "Make videotool render long-form audio chapters end-to-end: per-track dB mixing, auto storyboard from audio duration, segmented render that scales to 100+ scenes, and subtitles aligned from a known script. TDD: lock existing behavior first."
status: done
priority: P1
branch: "main"
tags: [feature, ffmpeg, audio, storyboard, subtitles, tdd]
blockedBy: []
blocks: [260519-1525-local-capcut-style-video-tool]
created: "2026-05-27T06:55:57.378Z"
createdBy: "ck:plan"
source: skill
---

# videotool P0 — dB mixer, storyboard auto-gen, segmented render, script subtitles

## Overview

Four P0 features so the existing audio-first builder can render a real chapter
(107-min narration, 114 scene images, music, polished script). TDD throughout:
each phase writes characterization tests that lock current command/behavior
BEFORE refactoring, then adds tests for new behavior. The 43 existing tests must
stay green. Files stay <200 lines; extend existing modules (no `_v2` copies).

Triggering case: `…/BẢN DỊCH/Chap 1/` — `Image/scene_001_4K.jpg … scene_115_4K.jpg`,
`…_translated_qa.wav` voice, `…_translated_qa.txt` script, music in `Instrument/`.

## Generalization principle (CRITICAL)

Chap 1 is **only a representative test sample**. Build for the general shape of
input — *a long voice track + an arbitrary folder of scene images + optional
music + a prose script file* — NOT for that folder's specific names. Concretely:
- No hardcoded image-name pattern (`scene_NNN_4K.jpg`), folder names (`Image/`,
  `Instrument/`, `Video/`), file suffixes (`_translated_qa`), or scene count.
  All come from CLI args / `job.yaml` paths and from globbing by extension.
- Script parser handles generic prose; no `Chương N:` regex, no fixed filename.
- Regression guards are synthetic temp-dir fixtures (any naming, any N, any
  duration). Chap 1 is exercised once as an end-to-end acceptance smoke (Phase 5),
  never as a unit-test dependency.

## Phases

| Phase | Name | Status |
|-------|------|--------|
| 1 | [dB audio mixer (AudioSpec + _audio_graph)](./phase-01-db-audio-mixer-audiospec-audio-graph.md) | Done |
| 2 | [Storyboard auto-gen (even-split to audio)](./phase-02-storyboard-auto-gen-even-split-to-audio.md) | Done |
| 3 | [Segmented render (scene to clip to concat)](./phase-03-segmented-render-scene-to-clip-to-concat.md) | Done |
| 4 | [Subtitle from script (approach A)](./phase-04-subtitle-from-script-approach-a.md) | Done |
| 5 | [Docs refresh + integration verify](./phase-05-docs-refresh-integration-verify.md) | Done |

## Completion Log

### Session 2 — 2026-05-27 (implementation, TDD)

All 5 phases shipped. Test suite 43 → 66 (+23). Files <200 lines except pre-existing
`core/services.py` (254 → 294; flagged for a future split, not introduced fresh).

- **P1**: `AudioSpec` (voice_gain_db 0 / music_gain_db -18.0 / duck / normalize_lufs -14.0|None);
  audio filtergraph extracted to `render/audio_graph.py`, reused by inline + segmented.
- **P2**: `core/storyboard.py` natural-sort + even-split generator; `storyboard auto` CLI
  writes the block into job.yaml (overwrite-with-warning). Naming-agnostic.
- **P3**: `render/segmented.py` (clip-per-scene + concat demuxer + audio-mux), `run_segmented`
  resumable executor, routing by `render.max_inline_scenes` (default 40). Shared helpers in
  `render/video_filters.py`. Inline xfade path unchanged.
- **P4**: `ai/align_script.py` (model-free parse + align script wording onto whisper timing);
  `inputs.script` + `transcribe --script`.
- **P5**: docs/codebase-summary.md refreshed; acceptance verified end-to-end through the real
  CLI — 50-image storyboard auto (Σduration == voice), 50-scene segmented dry-run (audio graph
  honors dB/duck/loudnorm), and a real 3-scene segmented render (3 clips + muxed output).

Gates: tester DONE (66/66), code-reviewer DONE_WITH_CONCERNS (fixed the one minor — a
plan-phase reference in a code comment; remaining items non-blocking / intentional).

## Build order & dependencies

- **P1 → P3**: segmented render reuses the `_audio_graph()` helper extracted in P1.
- **P2 → P3**: a 114-scene storyboard is what forces the segmented path; build the
  generator first so P3 has a real large timeline to route and test against.
- **P4** is independent of P1–P3 (subtitle pipeline), can land in parallel.
- **P5** runs last: refresh stale `docs/codebase-summary.md`, full green test run,
  acceptance dry-runs on Chap 1.

## Cross-plan dependencies

- `blocks: 260519-1525-local-capcut-style-video-tool` — this P0 delivers the dB
  mixer, scalable render, and script-subtitle pieces that the older plan's
  in-progress Phase 5 (subtitles) / 7 (GUI) / 8 (hardening) build on. The older
  plan is marked `blockedBy` this one. GUI / effects engine / `/video-tool` skill
  remain in that plan (P1–P3 of the brainstorm), out of scope here.

## Scope

- IN: 4 features above + docs refresh + tests.
- OUT (deferred): effects engine, `/video-tool` skill, Web GUI producer panel,
  AI image-to-video, true N-way crossfade across the segmented path.

Source design: `./brainstorm-summary.md`.

## Validation Log

### Session 1 — 2026-05-27

**Verification Results** (Full tier, 5 phases)
- Claims checked: ~12 key claims across phases. Verified: 12 | Failed: 0 | Unverified: 0
- `AudioSpec` absent in `core/job_spec.py` → dB mixer genuinely missing ✓
- `volume=0.5` hardcoded twice (`render/commands.py:54,97`); audio graph duplicated
  (lines 52-60 vs 94-100) → `_audio_graph()` extraction valid ✓
- `core/storyboard.py` exists (`build_storyboard`/`select_effects`/`find_scene_media`)
  → extend, don't recreate ✓
- `validate_job_paths` builds a `candidates` list (`core/validation.py:11-15`) →
  clean insert point for `inputs.script` ✓
- `test_storyboard_ffmpeg_command_uses_zoompan_and_xfade` asserts `xfade` on a
  small board (`tests/test_ffmpeg_commands.py:53`) → routing threshold keeps it
  on the inline path, stays green ✓
- No test asserts `volume=` → safe to change music default ✓
- 43 existing test functions confirmed (`grep def test_`) ✓

**Decisions confirmed (interview)**
1. **Segment routing** → add `render.max_inline_scenes: int = 40` to `RenderSpec`
   (configurable per job), route to segmented when scenes exceed it. *(Phase 3)*
2. **Music default** → `music_gain_db = -18.0` — gentle, clearly subordinate
   background bed (NOT the earlier `-6.0 preserve`); duck + loudnorm stay on.
   *(Phase 1)*
3. **Segment transitions** → hard cut + soft per-clip fade; true N-way crossfade
   deferred. *(Phase 3, already specified)*
4. **`storyboard auto` on existing block** → overwrite + warning naming old scene
   count; no `--force` gate. *(Phase 2)*

**Whole-Plan Consistency Sweep**
- Propagated all 4 decisions into phase-01 (music default -18.0 + test assert),
  phase-02 (overwrite+warning), phase-03 (max_inline_scenes field + file list).
- Re-read plan.md + 5 phase files: no stale `-6.0`/`SEGMENT_THRESHOLD` references
  remain in spec text; generalization principle consistent across phases.
- Unresolved contradictions: none. Eligible for implementation (Failed: 0).

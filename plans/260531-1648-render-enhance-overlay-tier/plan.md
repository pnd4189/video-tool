---
title: "Render Enhance — Overlay Tier (YouTube anti-strike)"
description: "Add a job-level enhance.tier flag (light=current fast path, full=overlay package) so the tool serves both low-RPM VN jobs and YPP-strict English jobs. Full tier burns subtitles from the existing txt, layers particle/grain + progress bar + optional audio visualizer, re-encoding the segmented mux once. TDD: lock tier-light behavior before adding tier-full."
status: done
priority: P2
branch: "main"
tags: [feature, ffmpeg, render, subtitles, overlay, whisper, tdd]
blockedBy: []
blocks: []
created: "2026-05-31T10:00:26.485Z"
createdBy: "ck:plan"
source: skill
---

# Render Enhance — Overlay Tier (YouTube anti-strike)

## Overview

One master switch `enhance.tier: light | full` in job.yaml.
- **light** (default) = exact current behavior: zoompan + concat-BGM + duck, segmented mux `-c:v copy`. Fast. For VN tiên hiệp / low-RPM jobs. **Zero regression.**
- **full** = overlay package in one re-encode pass (segmented mux drops `-c:v copy`): burned subtitles from the polished txt, particle/grain overlay, progress/chapter bar, optional `showwaves` visualizer. For English Tier-1 / YPP-strict jobs.

Reverses the 2026-05-28 *no-whisper* / *no-waveform* decisions **for tier full only**; tier light keeps them. Impact-SFX (gươm/chưởng) intentionally **out of scope** (highest cost, lowest anti-strike value, hurts sleep-listener AVD).

Honest caveat carried from brainstorm: overlays only fix the *static-slideshow + editing-value* strike signals. AI-voice footprint + non-transformative script remain bigger strike risks and are **out of this tool's scope**.

Source brainstorm: `plans/reports/from-brainstorm-to-planner-260531-1648-render-enhance-overlay-tier-report.md`

## Phases

| Phase | Name | Status |
|-------|------|--------|
| 1 | [Enhance schema and tier-light lock](./phase-01-enhance-schema-and-tier-light-lock.md) | Done |
| 2 | [Whisper sub-from-txt re-enable](./phase-02-whisper-sub-from-txt-re-enable.md) | Done (ai-extra install deferred to P4) |
| 3 | [Full-tier overlay filtergraph](./phase-03-full-tier-overlay-filtergraph.md) | Done |
| 4 | [Particle asset CLI docs and smoke render](./phase-04-particle-asset-cli-docs-and-smoke-render.md) | Done |

## Key architecture facts (verified)

- Segmented path (`render/segmented.py:85 _build_mux_command`) joins pre-encoded clips with `-c:v copy`; **no subtitle/overlay burn there today**. Any full-duration overlay forces this mux to re-encode (~2x). This is the cost the tier flag gates.
- Inline path already burns subtitles via `render/commands.py:153 _caption_filter` when `caption_mode=srt-and-burn`. tier-full reuses this filter on both paths.
- Sub-from-txt infra exists: `ai/align_script.py` (re-time txt onto audio timing) + `ai/faster_whisper_adapter.py` + `services.run_transcribe`. Only blocked by the uninstalled `ai` extra (`pyproject.toml:19 faster-whisper>=1.0`).
- `model_config = ConfigDict(extra="forbid")` on all specs → new `enhance` block is additive-safe.

## Dependencies

- Builds on render pipeline delivered by `260527-1700-videotool-feature-expansion` (status: done). No hard blocker.
- Related umbrella `260519-1525-local-capcut-style-video-tool` (in-progress) — additive; not blocking.

## Validation Log

### Verification Results (Standard tier — Fact Checker + Contract Verifier)
- Claims checked: 9 | Verified: 9 | Failed: 0 | Unverified: 0
- Evidence: `timeline.caption_mode` (timeline.py:33) + `root` (:29) ✓; `InputSpec.script` exists with matching comment "subtitles use its wording with whisper timing" ✓; `_caption_filter` callsites commands.py:44-46/84-86 ✓ (inline burn lives in commands.py, NOT ffmpeg_graph — Phase 3 corrected); `segmented._build_mux_command` `-c:v copy` at :98 ✓; `pyproject.toml:19 ai=faster-whisper` ✓.

### Validation Session 1 — decisions confirmed
1. **Subtitle style** = sentence-level SRT burn (reuse `_caption_filter`). ASS/word-kinetic deferred (needs word-level whisper timestamps `align_script` lacks). → Phase 3.
2. **Particle source** = bundled real CC0/Mixkit loops in `assets/overlays/` + `inputs.particle_overlay` override; procedural dropped. Sourcing: Pexels/Mixkit/Pixabay or Veo. → Phase 4.
3. **Whisper default model** = `base` (timing-only, balance speed). → Phase 2/4.

### Whole-Plan Consistency Sweep
- Re-read plan.md + 4 phase files. No stale terms: procedural-particle removed from Phase 4; ffmpeg_graph inline-injection claim corrected to commands.py in Phase 3; whisper `tiny/base` narrowed to `base` default in Phase 2. SRT-sentence (not ASS) consistent across Phase 3. No unresolved contradictions.

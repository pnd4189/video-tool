---
title: Cloud render on Colab/Kaggle with LLM orchestrator
description: >-
  Parallel cloud render path: full /make-video pipeline on Colab/Kaggle free
  tier (NVENC + LLM-authored job.yaml), local pipeline untouched
status: pending
priority: P2
branch: main
tags:
  - cloud
  - colab
  - kaggle
  - render
  - llm-orchestrator
blockedBy: []
blocks: []
created: '2026-07-07T02:27:47.123Z'
createdBy: 'ck:plan'
source: skill
---

# Cloud render on Colab/Kaggle with LLM orchestrator

## Overview

Second, parallel render system on Colab/Kaggle free tier as hardware-risk backup for the local `/make-video` flow. Notebook takes a Drive asset folder → LLM orchestrator (`cloud_director.py`) authors job.yaml (music_schedule, SFX cues, description/recap, chapters) → NVENC render with segment checkpoints on Drive → sfx → package → `Output/` on Drive. Local pipeline behavior unchanged.

Brainstorm: `plans/reports/brainstorm-260707-0855-cloud-render-llm-orchestrator-report.md`
Reverses "render stays local" (2026-06) — user-driven, pain = heat/machine occupation.

## Hard constraints (user)

1. All new code/notebooks live in `Colab/` subfolder (user's "COLAB").
2. Zero behavior change to local `/make-video`; two systems run in parallel.
3. Only shared-code exception: additive NVENC profile in `src/videotool/render/profiles.py` (+ allowlist relax in `commands.py`); default stays `libx264-balanced`.
4. LLM: Colab → GLM coding plan; Kaggle → configurable free model (Gemini Flash / Claude Haiku / other). Keys via Colab/Kaggle Secrets only.
5. Parallax = pre-rendered `Parallax/` folder + `parallax-link`; NOT generated in this flow.

## Key facts (verified in code — corrected after red-team)

- `video_filters.py:codec_args` is generic (`crf=None` skipped, `extra_args` appended), so NVENC slots into the profile. BUT `_reject_unsupported_profile` (commands.py:149) guards only the INLINE path (its sole caller, commands.py:26); the SEGMENTED path (`segmented.py:81,109`) is ungated. Cloud renders take the segmented path → Phase 1 tests must cover segmented, not just inline (finding M9).
- Segmented render is resumable (executor.py:34) but resume is NOT "pure file sync": (a) clips live at `.videotool/tmp/clips/<preset>/scene-NNNN.mp4` (services.py:189), not flat `tmp/`; (b) the in-progress temp is `scene-NNNN.part.mp4`, still `.mp4`-suffixed (executor.py:48-50); (c) `_is_complete` trusts `size>0` only (executor.py:107-108) → a truncated clip from a lossy Drive copy is accepted. Checkpoint needs correct nested paths + atomic Drive upload + ffprobe verify (findings C1/C2).
- Resume exists ONLY when `len(storyboard) > max_inline_scenes` (default 40, services.py:218). A ≤40-scene episode renders inline (one ffmpeg call, no resume). Cloud job.yaml must set `max_inline_scenes: 0` (finding C3).
- `videotool validate` does NOT validate `render.encoder` (bare str, job_spec.py:259) or `enhance.sfx.cues` (omitted from validation.py candidates) → cloud_director must pre-validate both before render (finding H8).
- `videotool_cloud.py` (gdrive:_VIDEOTOOL_SHARED) has setup/wheelhouse/job-yaml-harden, validated for whisper. Reuses `@main` (unpinned) + shared-Drive wheelhouse + `curl|sudo bash` → pin repo_ref to a SHA on the key-bearing runner (finding L13).
- NVENC removes encode cost only; zoompan/scale filters stay CPU → 2 vCPU Colab may bottleneck. Measure in phase 4. Kaggle 4 vCPU better. T4 required (P100 has no NVENC). `-preset p5` needs ffmpeg ≥4.4 — probe before render (finding M10).
- Colab `drive.mount` is FUSE (~60× slower than rclone, memory `gdrive-staging-use-rclone-not-cp`) → use rclone for stage + checkpoint on Colab too, not just Kaggle (finding H7).

## Phases

| Phase | Name | Status |
|-------|------|--------|
| 1 | [NVENC encoder profile](./phase-01-nvenc-encoder-profile.md) | Completed |
| 2 | [Cloud director LLM orchestrator](./phase-02-cloud-director-llm-orchestrator.md) | Completed (code + local logic tests; live-LLM run pending user keys) |
| 3 | [Cloud runner notebooks + Drive checkpoint](./phase-03-cloud-runner-notebooks-drive-checkpoint.md) | Completed (code + local logic tests; GPU run pending phase 4) |
| 4 | [E2E validation + docs](./phase-04-e2e-validation-docs.md) | Docs done; GPU E2E + NVENC tuning pending user Colab session |

**Schema deviation (both phase 2 & 3):** plan says `render.max_inline_scenes: 0` but `job_spec.py:264` is `gt=0`. Used **`1`** — forces the segmented resumable path for any ≥2-scene episode, same intent, no `src/` change (respects constraint #2/#3). `docs/cloud-render-setup.md` + AGENTS.md reflect this.

Dependency chain: 1 → 3, 2 → 3, 3 → 4. Phases 1 and 2 are independent of each other.

## Acceptance criteria (whole plan)

- One real episode renders end-to-end on Colab free: input = Drive folder path, output = mp4 + description.txt + captions(.youtube).srt in `Output/`; zero local CPU used.
- Kill session mid-render on a **forced-segmented (`max_inline_scenes: 0`)** job → rerun cell → resumes from **ffprobe-verified** checkpointed segments; completed clips not re-rendered, no stale/truncated-clip reuse, resume makes no LLM calls.
- A size>0-but-truncated clip planted on Drive is rejected on restore (not welded into the output).
- No-NVENC / wrong-GPU path aborts with a clear message (does not silently CPU-render to a 6h timeout).
- Publish verified before checkpoint deletion; no API key in any Drive-synced log.
- `pytest -q` green (66+); local render output byte-path unchanged (default profile untouched).
- SFX cues pass ear-audit sample; description usable with light edits.

## Unresolved questions

- GLM coding plan ToS/quota for raw API calls — verify in phase 2.
- NVENC `-cq` value to hold <2.5GB/long video — measure in phase 4.
- Kaggle rclone token flow — phase 3, secondary path only.
- Representative episode scene count — does a real 45-min board clear 40 scenes? Determines how often the inline-vs-segmented gap (C3) would have bitten before the `max_inline_scenes: 0` fix. Confirm on a real board in phase 4.
- Is `_VIDEOTOOL_SHARED` truly single-owner (this user only) or shared with other people? Security findings (L13, M11) are right-sized to solo use; revisit if it becomes multi-tenant.

## Red Team Review

### Session — 2026-07-07
**Findings:** 13 (13 accepted, 0 rejected) — deduped from 20 raw across 3 hostile reviewers (Security Adversary, Assumption Destroyer, Failure Mode Analyst).
**Severity breakdown:** 3 Critical, 5 High, 3 Medium, 2 Low.
**Threat-model note:** security cluster right-sized to a solo operator (own Drive/Colab/keys, no second principal); data-loss/correctness cluster accepted at full severity — those are what will actually bite.

| # | Finding | Severity | Disposition | Applied To |
|---|---------|----------|-------------|------------|
| C1 | Checkpoint glob/path flat `tmp/*.mp4`, clips actually at `tmp/clips/<preset>/` → resume no-op | Critical | Accept | Phase 3 |
| C2 | `.part.mp4` filter wrong + non-atomic Drive copy + `_is_complete` size>0 → truncated clip welded into output | Critical | Accept | Phase 3 |
| C3 | ≤40-scene episodes render inline → no resume at all | Critical | Accept | Phase 2 (`max_inline_scenes:0`), Phase 3 |
| H4 | Rerun re-authors job.yaml; index-addressed clips + mixed encoder → stale/desynced clip reuse | High | Accept | Phase 2 (idempotent), Phase 3 (pin job.yaml) |
| H5 | No-NVENC silent uncapped `libx264-fast` fallback can hit 6h timeout → total loss | High | Accept | Phase 3 (probe+abort) |
| H6 | Publish unverified + checkpoint deleted "on success"; rclone VFS stall loses video | High | Accept | Phase 3 (verified publish) |
| H7 | Colab primary uses FUSE mount (~60× slower) for stage + checkpoint | High | Accept | Phase 3 (rclone) |
| H8 | `videotool validate` doesn't validate encoder or SFX cue paths → fails after render | High | Accept | Phase 2 (pre-render checks) |
| M9 | Phase 1 "only gate" claim false; segmented path ungated + untested | Medium | Accept | Phase 1 (segmented tests) |
| M10 | `-preset p5` needs ffmpeg ≥4.4, never probed | Medium | Accept | Phase 1 (assert), Phase 3 (probe) |
| M11 | LLM key / unreleased script may leak to Drive-synced logs | Medium | Accept | Phase 2/3 (redact, ephemeral logs) |
| L12 | Reused `shell=True` + interpolated path → injection / VN apostrophe bug | Low | Accept | Phase 3 (list-form subprocess) |
| L13 | Supply chain: unpinned `@main`, shared-Drive wheelhouse, `curl\|sudo bash` | Low | Accept | Phase 3 (pin SHA, document) |

### Whole-Plan Consistency Sweep
- Files reread: plan.md, phase-01, phase-02, phase-03, phase-04.
- Decision deltas checked: 6 (segmented-forced resume, correct checkpoint path, atomic+verified checkpoint, idempotent cloud_director, probe-before-render, rclone-not-FUSE).
- Reconciled stale references: plan.md Key facts (2 false claims corrected), acceptance criteria (resume precondition), Phase 1 arch/tests/risk, Phase 2 requirements/gate/steps/risk, Phase 3 full redesign. Phase 4 already references disconnect-resume drill + NVENC tuning + throughput report — consistent with the hardened design; its drill must now use a >40-scene job (noted in C3, Phase 3 success criteria).
- Unresolved contradictions: 0.

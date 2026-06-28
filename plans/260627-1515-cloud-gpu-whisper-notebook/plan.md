---
title: "Cloud GPU pre-compute notebook (Kaggle whisper-large-v3)"
description: "Whisper-only GPU pre-compute on Kaggle (primary) + Colab (backup), driven from a Drive job-folder path; render stays local. Expose --device/--compute-type on transcribe, a shared cloud core, two runner notebooks, and setup docs. Model = large-v3 (turbo dropped, validated 2026-06-27)."
status: completed
priority: P2
branch: "main"
tags: [cloud, gpu, whisper, kaggle, colab, notebook]
blockedBy: []
blocks: []
created: "2026-06-27T08:42:49.468Z"
createdBy: "ck:plan"
source: skill
---

# Cloud GPU pre-compute notebook (Kaggle whisper-large-v3)

## Overview

Offload only the GPU-worthwhile step — Vietnamese transcription at `large-v3` quality — to
free Kaggle/Colab GPU, driven from a Google Drive job-folder path. Output `captions.srt` +
`chapters.json` back to Drive; the local Ryzen still runs `videotool render` (CPU-bound, faster
than cloud CPU — confirmed in the brainstorm). Creative decisions (mood/overlay/SFX cues/
description) stay with Claude locally; the notebook is LLM-free. Parallax keeps its existing Kaggle
flow (`/home/dung/VIBE_CODING/2. COLAB`).

Source brainstorm: `plans/reports/brainstorm-cloud-gpu-precompute-260627-1515-kaggle-whisper-notebook-report.md`

## Phases

| Phase | Name | Status |
|-------|------|--------|
| 1 | [CLI device flags](./phase-01-cli-device-flags.md) | Done |
| 2 | [Cloud core module](./phase-02-cloud-core-module.md) | Done |
| 3 | [Kaggle runner notebook](./phase-03-kaggle-runner-notebook.md) | Done |
| 4 | [Colab runner notebook](./phase-04-colab-runner-notebook.md) | Done |
| 5 | [Shared Drive deps + setup doc](./phase-05-shared-drive-deps-setup-doc.md) | Done |

## Acceptance criteria (whole plan)
- From a Drive job-folder path, the Kaggle notebook produces `captions.srt` (+ `chapters.json` when
  the script has ≥3 `Chương` markers) via `large-v3` on T4 GPU, written back to the folder.
- Colab notebook does the same via `drive.mount`; either platform interchangeable on the same job.
- Local `videotool transcribe` (no flags) behaves exactly as before (`cpu`/`int8`, explicit local
  model path); `pytest -q` stays green (66+).
- No 50-file gdown failure (rclone remote, whisper-only pulls voice + `*_vi.txt` only).

## Out of scope
ffmpeg render on cloud; NVENC; parallax notebook rebuild; in-notebook LLM; overlay/sfx upload
(deferred until render moves to cloud).

## Dependencies
Phase order is linear: 1 (tool change) → 2 (core uses it) → 3 & 4 (notebooks use core, parallel) →
5 (docs/deps wrap-up). No cross-plan blockers (parallax plan 260618 is unrelated clip-ingest).

## Key risks (carried into phases)
- **Kaggle has no Drive mount** — rclone.conf via Kaggle Secrets; never gdown a 119-file folder. (P3)
- **Adapter guard blocks model ids** — `large-v3` is a name, not a path, so Phase 1 must relax the
  `model_path.exists()` guard (still required even though turbo was dropped). (P1)

## Validation Log

### Verification Results (2026-06-27, Full tier — 5 phases)
- Claims checked: 6. Verified: 5. Failed: 0. Unverified: 1 (faster-whisper model-id behaviour, external).
- VERIFIED: adapter `model_path.exists()` guard (`ai/faster_whisper_adapter.py`); `run_transcribe`
  signature (`core/services.py:235`); `transcribe` CLI (`cli/main.py:85`); init-job defaults
  `licensed-only`/`srt-only` (`core/job_spec.py:260-261`); hatchling wheel-buildable; git remote
  `https://github.com/pnd4189/video-tool`.

### Session 1 decisions (interview)
- **Whisper model = `large-v3` (turbo DROPPED).** Removes the turbo-id risk and the faster-whisper
  version concern (`>=1.0` already supports large-v3, public HF repo, no token). Guard relaxation in
  Phase 1 still required (`large-v3` is a name).
- **Install = `pip install "git+https://github.com/pnd4189/video-tool@<tag>"` (PRIMARY).** Identical
  one-liner on Kaggle + Colab, no wheel rebuild per change. Requires the repo (or a release) be
  PUBLIC. Fallback when private: prebuilt wheel staged on `_VIDEOTOOL_SHARED/`. ACTION: confirm/flip
  repo visibility or tag a public release.
- **HF token = NOT needed.** `large-v3` (Systran/faster-whisper-large-v3) is public; token doesn't
  speed bandwidth. If anonymous rate-limits ever bite, add `HF_TOKEN` as a per-account secret
  (Kaggle Secret / Colab userdata) set once per account — deferred.
- **Model download = runtime HF each session** (KISS); no Drive model cache (rclone-down isn't faster).
- **job.yaml = prefer `_creative/job.yaml` (Claude seed), else notebook `init-job`.**

### Whole-Plan Consistency Sweep
Re-read plan.md + all 5 phase files. No stale `large-v3-turbo` model id remains; all model refs =
`large-v3`; install refs = `git+https@<tag>` primary / wheel fallback; HF-token = deferred
consistently. Zero unresolved contradictions. Plan eligible for implementation (Failed: 0).

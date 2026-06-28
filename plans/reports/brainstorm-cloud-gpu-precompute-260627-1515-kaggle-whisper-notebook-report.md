---
title: Cloud GPU pre-compute notebook (Kaggle whisper-large) for the video pipeline
date: 2026-06-27 15:15
type: brainstorm-report
modes: []
status: approved-pending-plan
related:
  - AGENTS.md
  - /home/dung/VIBE_CODING/2. COLAB (existing parallax + kaggle infra)
  - src/videotool/ai/faster_whisper_adapter.py
---

# Brainstorm — Cloud GPU pre-compute notebook (Kaggle primary, Colab backup)

## Problem statement
User wants to offload the GPU-heavy parts of the audio-story render pipeline to free Kaggle/Colab
GPU, driven from a Google Drive folder link, rotating between the two platforms for quota. Open
questions raised: what to upload to Drive for auto-detect; whisper input + how to get higher
quality than local CPU; overlays; which LLM (Ollama free vs GLM Coding plan) orchestrates.

## Scout findings (ground truth)
- **Encoder = libx264 (CPU) only.** `render/profiles.py` + `render/commands.py:151` state NVENC/
  VAAPI/HEVC are NOT wired. The whole render (zoompan + overlay screen-blend + libass subtitle
  burn + encode) is CPU-bound.
- **Local box = Ryzen 7640HS, 12 threads**, rendered the 49-min CHAP 3 ~realtime. **Colab free
  ~2 vCPU, Kaggle ~4 vCPU** — both materially weaker CPU. ⇒ moving ffmpeg render to cloud would be
  SLOWER, not faster.
- **GPU is used only by** `render/parallax.py` (DepthAnything, `cuda.is_available()`) and
  `faster-whisper` (`ai` extra). ffmpeg never touches GPU.
- `ai/faster_whisper_adapter.py` **already accepts `device` + `compute_type`**, but the CLI
  `transcribe` (`cli/main.py:85`) exposes only `--model`/`--script` → GPU path needs a ~5-line CLI
  flag addition, no new logic.
- Subtitle burn uses libass `force_style` with **no shipped font** → Vietnamese tofu risk *at render
  time* (local in this design, so not a notebook concern now).
- Tool is pip-installable (hatchling). Shared libs (overlays, sfx, models, font) live on the local
  machine, unreachable from a notebook.
- User already has stable Kaggle parallax infra at `/home/dung/VIBE_CODING/2. COLAB`
  (`parallax-depthflow-v5-cell.py`, parallax-out, cloud-GPU comparison report).

## Core reframe (the brutal truth)
"Render on GPU for speed" is a misconception: the bottleneck is **CPU ffmpeg**, and cloud CPU is
**weaker** than the user's laptop. GPU only pays off for **parallax + whisper**. So do NOT move the
render to the cloud; move only the GPU pre-compute. Creative decisions stay with Claude (user
trusts that more), so the notebook needs **no LLM** for this scope.

## Decisions captured
- **Goal:** speed up GPU parts, **render stays local** (option B/C, not A).
- **Platforms:** **both** — Kaggle PRIMARY (30h/week GPU), Colab BACKUP (Drive mount). Rotate for quota.
- **LLM:** creative (mood/overlay/SFX cues/recap/description) done by **Claude locally**; notebook
  LLM-free this round. GLM (Coding-plan key) reserved behind a flag for future unattended batch glue.
- **Whisper model:** **large-v3-turbo** (best speed/quality on T4 for Vietnamese; 49-min ~3-6 min).
- **Scope this round:** **whisper-only** notebook. Parallax keeps its existing Kaggle flow.
- **Kaggle Drive access:** via **rclone remote** (token in Kaggle Secrets), NOT gdown public link
  (gdown folder cap = 50 files breaks `Image/`). Whisper-only ⇒ only pulls voice + `*_vi.txt` (~70MB).

## Approaches evaluated
- **A. Full cloud notebook (incl. ffmpeg render).** Rejected: CPU-bound encode on weak cloud CPU →
  slower + 12h-timeout risk; needs NVENC work and stays filtergraph-CPU-bound anyway.
- **B. Hybrid: GPU notebook pre-compute → local render.** CHOSEN direction. GPU where it pays,
  render where CPU is strong.
- **C. Thin orchestrator over existing /Colab scripts.** Effectively the MVP of B; this round's
  whisper-only notebook is exactly this.

## Final design — "GPU pre-compute service" (whisper-only this round)

Pipeline stages / where each runs:
| Stage | Where | Does |
|---|---|---|
| 1. Prep + creative | Local (Claude) | detect assets, job.yaml (mood/overlay/enhance), curate SFX cues, recap/description → push Drive |
| 2. GPU pre-compute | **Kaggle/Colab notebook** | `videotool transcribe --device cuda --compute-type float16 --model large-v3-turbo` on voice+script → `captions.srt` + `chapters.json` back to Drive |
| 3. Render + SFX + package | Local Ryzen | `videotool render` (consumes Parallax/ + captions) → SFX burn → `Output/` |

Two notebooks, one shared core (DRY):
- `videotool_cloud.py` — pip-install videotool, resolve job folder by the existing CLI convention,
  run transcribe on GPU, write outputs. Platform-agnostic.
- `kaggle_runner.ipynb` — I/O via **rclone** (Kaggle Secrets holds `rclone.conf`). PRIMARY.
- `colab_runner.ipynb` — I/O via `drive.mount`. BACKUP.
- Rotate quota: same Drive job folder, run whichever notebook.

### Drive layout the notebook auto-detects
```
gdrive:/_VIDEOTOOL_SHARED/          (upload ONCE)
  overlays/                          CC0 atmosphere library (4K-H264)   [render-time, local]
  sfx/dao-si/  sfx/binh-thien/       SFX packs (masters already on Drive — consolidate)
  fonts/<vn-font>.ttf                only needed if render ever moves to cloud
  models/                            optional cache: faster-whisper-large-v3-turbo, DepthAnything

gdrive:/.../CHAP N/                   (per job — mostly exists)
  voice.* , *_vi.txt                 ← whisper-only notebook pulls THESE
  Image/ Video/ Music/ "CTA voice/" thumbnail ending
  Parallax/        filled by existing Kaggle parallax flow
  _creative/       NEW: Claude writes job.yaml seed + sfx_cues.json + description seed
  outputs/ → Output/
```

### Required tool change (small)
Expose `--device` + `--compute-type` on `transcribe` (CLI → `run_transcribe` → adapter). Adapter
already supports them; ~5 lines + default stays `cpu/int8` for local back-compat.

## Risks / mitigations
- **Kaggle has no Drive mount** → rclone token in Kaggle Secrets (one-time). gdown rejected (50-file
  cap). Whisper-only keeps transfer tiny (voice+script).
- **large-v3-turbo VRAM/availability** on T4 → fallback `medium` flag; turbo fits T4 fine.
- **Model cold-download** on each fresh session → optional `_SHARED/models/` cache; or accept ~1-min
  HF pull (notebook has internet).
- **Script lacks `Chương N` markers** (seen on CHAP 3) → chapters approximate; unchanged by this work,
  separate content fix.
- **Scope creep to render-on-cloud** → explicitly out of scope; revisit only with NVENC + measurement.

## Success criteria
- From a Drive job-folder path, Kaggle notebook produces `captions.srt` + `chapters.json` via
  large-v3-turbo and writes them back, with no manual file shuffling.
- Local `videotool render` consumes them unchanged; subtitle/chapter quality visibly better than `base`.
- Colab notebook does the same via `drive.mount`; either platform interchangeable on the same job.
- `transcribe --device cpu` local path unchanged (back-compat).

## Out of scope (this round)
ffmpeg render on cloud; NVENC; parallax notebook rebuild; in-notebook LLM creative; overlay generation.

## Next steps
- `/ck:plan` to phase: (1) CLI `--device/--compute-type`, (2) `videotool_cloud.py` core,
  (3) `kaggle_runner.ipynb` (rclone+Secrets), (4) `colab_runner.ipynb` (drive.mount),
  (5) `_VIDEOTOOL_SHARED` upload + one-time rclone-Secrets setup doc.

## Unresolved questions
- Exact GLM model id for the future batch-glue flag (user said "GLM 5.2"; confirm current id on their
  Coding plan before wiring) — deferred, not needed this round.
- Whether to cache the turbo model in `_SHARED/models/` (cold-start speed vs Drive space) — decide at plan time.

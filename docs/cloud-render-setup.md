# Cloud render (parallel system) — setup

Run the **whole** `/make-video` pipeline on a free Kaggle/Colab T4 GPU. **Claude Code CLI is the
director**: it reads the Drive folder, authors a `creative.yaml` (music schedule, SFX cues, mood,
atmosphere overlay, description/recap) — the same intelligent work as local `/make-video` — and
stages it on Drive. The render box then just runs the deterministic pre-steps + `apply_creative` +
NVENC render with resumable Drive checkpoints, and publishes the mp4 + package to the source
folder's `Output/`. **No LLM runs on the render box. Zero local CPU used.**

This is a **second, parallel system** — it does not change the local `/make-video` flow. Use it
when the pain is machine occupation / heat, not raw speed: a T4's 2–4 vCPU bottlenecks the CPU
filter graph (subtitle burn + showwaves + overlay blend); NVENC only removes the encode cost, so
wall-time is ~realtime, not faster than a strong local CPU.

**Validated 2026-07-11** — ĐẠO SĨ 51-min episode on Kaggle T4: **~41 min wall (~0.8× realtime)**,
`youtube-16x9.mp4` **1.085 GiB** (under the 2.5 GB cap), h264/1920×1080/aac/48k/−13.5 LUFS, 127
scenes (120 parallax clips + 7 b-roll), yellow subs + visualizer + 8 SFX + 4 music + CTA spliced,
all QA-pass, checkpoint auto-purged after verified publish.

**Kaggle = primary** (4 vCPU > Colab's 2; T4×2 gives **no** render speedup — one ffmpeg uses one
GPU). **Colab = fallback** on quota. Distinct from `cloud-gpu-whisper-setup.md` (transcription only).

## Pieces

| File | Role |
|------|------|
| `creative.yaml` (Claude-authored, staged on Drive) | music_schedule + SFX cues + mood + overlay + description; the intelligent layer |
| `Colab/cloud_director.py` | `apply_creative()` merges creative.yaml into a deterministic, pinned `job.yaml` (no LLM). `autonomous=True` = on-box-LLM fallback |
| `Colab/cloud_render_runner.py` | Runner: rclone stage-in → apply_creative/resume → NVENC render + checkpoint → sfx → package → verified publish |
| `Colab/videotool_cloud.py` | Shared install/setup core (also used by the whisper runners) |
| `Colab/videotool-render.ipynb` | Dedicated render-only kernel template (NO whisper cells — those would break "Run All") |

Re-upload edited modules to the shared Drive so the render kernel picks them up:

```bash
rclone copy Colab/cloud_director.py       gdrive:_VIDEOTOOL_SHARED/
rclone copy Colab/cloud_render_runner.py  gdrive:_VIDEOTOOL_SHARED/
rclone copy Colab/videotool_cloud.py      gdrive:_VIDEOTOOL_SHARED/
```

## One-time setup

1. **GPU runtime.** Colab: Runtime → Change runtime type → **T4** (P100 has no NVENC and will
   abort). Kaggle: turn on the T4 accelerator.
2. **rclone remote → `RCLONE_CONF` secret (base64).** The runner uses rclone for all bulk I/O (the
   FUSE mount is ~60× slower). On Kaggle store the config as a **base64** secret — a raw multi-line
   paste drops the `[gdrive]` header and rclone then can't find the remote:
   ```bash
   base64 -w0 ~/.config/rclone/rclone.conf   # paste this one line as Kaggle Secret RCLONE_CONF, Attached
   ```
   The setup cell decodes it (accepts base64 or raw) and asserts a `gdrive:` remote exists.
3. **Library mirrors on the shared Drive** (one-time; the render kernel copies them locally):
   ```bash
   rclone copy ~/.local/share/videotool/sfx      gdrive:_VIDEOTOOL_SHARED/sfx
   rclone copy ~/.local/share/videotool/overlays gdrive:_VIDEOTOOL_SHARED/overlays
   ```
   No LLM key needed on the render box — Claude authored `creative.yaml` locally.

## Run (Claude Code CLI-driven)

Per episode, Claude Code CLI does the intelligent + orchestration work; the user does two Kaggle-UI
clicks that the CLI can't automate (set the secret, pick the GPU).

1. **Claude authors `creative.yaml`** (reads the SRT + `*_vi_qa.txt` + `*_music_prompts.txt` via
   rclone; picks music spans, SFX cues, optional mood/overlay, description) and stages it:
   `rclone copyto creative.yaml gdrive:_VIDEOTOOL_SHARED/creative/<episode>.yaml`.
2. **Claude fills + pushes `videotool-render.ipynb`** with the episode paths and a **pushed** SHA:
   ```python
   SOURCE     = 'gdrive,root_folder_id=<FOLDER_ID>:'          # connection string for a u/1 account folder
   OUTPUT     = 'gdrive,root_folder_id=<FOLDER_ID>:Output'
   CHECKPOINT = 'gdrive:_VIDEOTOOL_SHARED/checkpoints/<episode>'
   CREATIVE   = 'gdrive:_VIDEOTOOL_SHARED/creative/<episode>.yaml'
   REPO_REF   = 'git+https://github.com/pnd4189/video-tool@<PUSHED_SHA>'
   rr.render_job(SOURCE, OUTPUT, CHECKPOINT, creative_remote=CREATIVE, repo_ref=REPO_REF, local_job='/tmp/job')
   ```
   then `kaggle kernels push -p <dir>`.
3. **User (Kaggle UI):** add the `RCLONE_CONF` base64 secret (one-time, persists) → Accelerator =
   **GPU T4 x2** → Save & Run All (Commit).
4. **Claude monitors:** `kaggle kernels status` (poll) → on COMPLETE pull `quality-report.json` +
   confirm the artifacts in `Output/`.

The source folder must contain what `/make-video` expects: `voice.*`, `Image/`, optional `Video/`,
`Parallax/`, `Music/`, `*_vi_qa.srt` (provided — **no whisper** in this flow), `*_music_prompts.txt`,
optional `*_DESCRIPTION_TEMPLATE.txt`, `CTA voice/`.

**Fallback with no Claude in the loop:** drop `creative_remote`, pass `autonomous=True`, and add
`kaggle benchmarks init -y` to the setup so the on-box LLM (Model Proxy) authors it — see *Autonomous
fallback* below. Lower quality; use only when not driving via Claude.

## Music bed wiring (regression 2026-07-21)

The runner calls `init-job` without `--music`, so `cloud_director` must fill `inputs.music`
itself — `services._stage_music` drops the whole bed *and* any `audio.music_schedule` when that
key is empty, silently and with no error. `_seed_audio_story_defaults` now points it at
`Music/` (or `music/`) and `pre_render_checks` aborts when tracks exist but the key is unset.
Renders made before this fix have no background music.

## Resume after a disconnect

**Rerun the same cell.** The runner restores the pinned `job.yaml` + checkpointed clips from
Drive, ffprobe-verifies each clip's duration, re-renders only what's missing, and **makes no LLM
call** on resume. Completed clips are never re-encoded; a truncated clip is dropped and redone.

Every job is forced onto the resumable segmented path (`render.max_inline_scenes: 1`), so resume
works even for short episodes. The checkpoint is purged only **after** publish is verified (each
artifact re-listed with size > 0 from a fresh rclone call), so a stalled write-back keeps the
checkpoint for a retry instead of losing the render.

## Safety / limits

- The runner writes to the source folder's `Output/` **only**; the checkpoint lives on the shared
  Drive, never inside the source folder. Nothing else under the source is touched.
- No NVENC / wrong GPU / old ffmpeg → **abort with a message**, never a silent 6-hour CPU render.
  Pass `allow_cpu=True` to opt into a capped x264 render when no T4 is available (slower).
- Pin `repo_ref` to a commit SHA on the key-bearing render runner for a reproducible install.
- LLM output is never trusted blind: SFX density/spacing/CTA-skip caps and music-cue coverage are
  enforced in code; a hallucinated encoder or an SFX path escaping the job folder aborts before
  any GPU time is spent.

## Autonomous fallback — on-box LLM (only when NOT driving via Claude)

Default path is Claude-authored `creative.yaml` (above). The on-box LLM survives only for running
the notebook with no Claude in the loop (`autonomous=True`). Kaggle's LLM credit is the Benchmarks
**Model Proxy** — `kaggle benchmarks init -y` writes a `.env` with an OpenAI-compatible
`MODEL_PROXY_URL` + short-lived `MODEL_PROXY_API_KEY` (no personal key); `cloud_director`'s `kaggle`
provider calls `google/gemini-3.5-flash` (override `KAGGLE_PROXY_MODEL`).

**Empirical probe on this Kaggle account (2026-07-11)** — Model Proxy, Vietnamese homograph SFX
task ("kiếm" sword-clash vs "kiếm tiền" earn-money):

| Model (proxy slug) | Result |
|--------------------|--------|
| `google/gemini-3.5-flash` | ✅ 200, homograph correct, ~1.1s |
| `google/gemini-3-flash-preview` | 200 but JSON truncated |
| `anthropic/claude-haiku-4-5`, `claude-sonnet-4-6` | 503 (not reachable) |
| `google/gemini-2.5-flash`, `zai/glm-5`, `qwen3-235b` | 503 |
| `deepseek-v3.2` | 429 (heavy load) |

→ **`google/gemini-3.5-flash` via the Kaggle Model Proxy is the pick.** Flagship slugs (Opus 4.8,
GPT-5.5, Gemini-Pro) 503 on this proxy today; re-probe with the notebook's probe cell if that changes.

- **kaggle** (Model Proxy, `google/gemini-3.5-flash`) — **default on Kaggle.** Provisioned by
  `kaggle benchmarks init`; no personal key. Override the model with `KAGGLE_PROXY_MODEL`.
- **gemini** (`gemini-2.5-flash`, `generativelanguage.googleapis.com`) — Colab option, free via
  Google AI Studio (`GEMINI_API_KEY`). The retired `gemini-2.0` is not used.
- **anthropic** (`claude-haiku-4-5`) / **glm** (`glm-4-flash`) — direct-key fallbacks; set the
  matching Secret and pass `provider=`. (Both 503 on the Kaggle proxy right now.)

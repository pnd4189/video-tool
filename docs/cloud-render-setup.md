# Cloud render (parallel system) — setup

Run the **whole** `/make-video` pipeline on a free Colab/Kaggle T4 GPU, driven from a Google
Drive folder path: an LLM authors `job.yaml` in the notebook (music schedule, SFX cues,
description/recap, chapter fallback), NVENC renders with resumable Drive checkpoints, and the
finished mp4 + package land in the source folder's `Output/`. **Zero local CPU used.**

This is a **second, parallel system** — it does not change the local `/make-video` flow. Use it
when the pain is machine occupation / heat, not when you need the fastest wall-clock (a T4's 2–4
vCPU can bottleneck the CPU zoompan/scale filters; NVENC only removes encode cost). See the
throughput report from phase-4 validation for go/no-go numbers.

**Kaggle is the primary render platform** (no separate LLM key to source — it ships an Anthropic
credit, and its 4 vCPU beats Colab's 2 for the CPU filter graph). Colab is the backup. Both share
the same modules and Drive folders.

Distinct from `cloud-gpu-whisper-setup.md`, which offloads **only** transcription. This offloads
the entire render.

## Pieces

| File | Role |
|------|------|
| `Colab/cloud_director.py` | LLM orchestrator: deterministic pre-steps + 4 LLM tasks → validated, pinned `job.yaml` |
| `Colab/cloud_render_runner.py` | Runner: rclone stage-in → director/resume → NVENC render + checkpoint → sfx → package → verified publish |
| `Colab/videotool_cloud.py` | Shared install/setup core (also used by the whisper runners) |
| `Colab/colab_runner.ipynb` / `kaggle_runner.ipynb` | "Full cloud render" section wires the above |

Re-upload edited modules to the shared Drive so the notebooks pick them up:

```bash
rclone copy Colab/cloud_director.py       gdrive:_VIDEOTOOL_SHARED/
rclone copy Colab/cloud_render_runner.py  gdrive:_VIDEOTOOL_SHARED/
rclone copy Colab/videotool_cloud.py      gdrive:_VIDEOTOOL_SHARED/
```

## One-time setup

1. **GPU runtime.** Colab: Runtime → Change runtime type → **T4** (P100 has no NVENC and will
   abort). Kaggle: turn on the T4 accelerator.
2. **rclone remote.** The runner uses rclone for all bulk I/O (the FUSE mount is ~60× slower).
   Configure a `gdrive:` remote once (`rclone config`) and stage the config on the shared Drive:
   ```bash
   rclone copy ~/.config/rclone/rclone.conf gdrive:_VIDEOTOOL_SHARED/
   ```
   The Colab cell copies it back into place; on Kaggle store the whole `rclone.conf` body as a
   Secret named `RCLONE_CONF` (it is written to session disk at runtime — ephemeral, scope the
   remote to your channel Drive subtree).
3. **LLM access.** On Kaggle (primary) the credit is the **Benchmarks Model Proxy** — no personal
   key. The runner cell runs `kaggle benchmarks init -y`, which writes a `.env` with an
   OpenAI-compatible `MODEL_PROXY_URL` + short-lived `MODEL_PROXY_API_KEY`; cloud_director's
   `kaggle` provider reads it and calls `google/gemini-3.5-flash` (override via `KAGGLE_PROXY_MODEL`).
   On Colab (no proxy) add a `GEMINI_API_KEY` (or `ANTHROPIC_API_KEY` / `GLM_API_KEY`) to `userdata`.
   `choose_provider()` prefers the Kaggle proxy, then direct keys. The proxy key + any Secret stay
   in memory, are never written to Drive, and are redacted from logs.
4. **SFX library mirror.** Stage the local packs to the shared Drive once so the director can copy
   chosen cues into the job:
   ```bash
   rclone copy ~/.local/share/videotool/sfx gdrive:_VIDEOTOOL_SHARED/sfx
   ```

## Run

Open `kaggle_runner.ipynb` (primary; or `colab_runner.ipynb`), run the whisper cells if you still
need a fresh SRT, then the **"Full cloud render"** section: edit the three rclone paths and run.

```python
rr.render_job(
    'gdrive:.../CHAP N',                            # source asset folder
    'gdrive:.../CHAP N/Output',                     # only-Output write target
    'gdrive:_VIDEOTOOL_SHARED/checkpoints/CHAP-N',  # transient checkpoint
    provider=None,                                  # None = platform default
    repo_ref='git+https://github.com/pnd4189/video-tool@main',
)
```

The source folder must already contain what `/make-video` expects: `voice.*`, `Image/`,
optional `Video/`, `Music/`, `*_vi_qa.txt` + `*_vi_qa.srt`, `*_music_prompts.txt`, an optional
`*_DESCRIPTION_TEMPLATE.txt`, and an optional `CTA voice/` folder. Provide the SRT (no whisper
in this flow — run the whisper cells first if you don't have one).

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

## Provider notes

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

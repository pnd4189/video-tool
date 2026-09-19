# Kaggle render runbook

The render box runs NO LLM. The agent authors `creative.yaml` locally, stages three files, the user
clicks **Save & Run All**, the box renders and publishes to `<source>/outputs/`. Detail on the
architecture: `docs/cloud-render-setup.md`. Sources: memories `render-on-kaggle-runbook`,
`kaggle-gpu-vs-tpu-kernel-routing`, `kaggle-tpu-vs-gpu-render-benchmark`.

## Two kernels — never mix them up

| User says | Kernel | Config file on Drive | Accelerator (user picks in UI) | Encoder |
|---|---|---|---|---|
| "GPU" / "T4" | `pnd4189/videotool-render` | `_VIDEOTOOL_SHARED/render_job.json` | GPU T4 | `h264_nvenc-capped` |
| "TPU" | `pnd4189/videotool-render-tpu` | `_VIDEOTOOL_SHARED/render_job.tpu.json` | TPU | `libx264-balanced-capped` (`allow_cpu`) |

- The GPU kernel reads ONLY `render_job.json`. The TPU kernel reads `render_job.tpu.json` first and
  falls back to `render_job.json`. So a GPU episode MUST be written to `render_job.json`, or the GPU
  kernel renders whatever older episode is still in that file.
- Two episodes can run in parallel (one per kernel); quotas add up (GPU 30h + TPU 20h per week).
- One checkpoint slug per episode (`_VIDEOTOOL_SHARED/checkpoints/<slug>`), never shared.
- **Never resume across runtimes.** The encoder is pinned into the checkpoint on the first run;
  a GPU-started episode resumed on TPU aborts on purpose, a TPU-started one crawls on GPU.
- User did not say which: TPU renders ~2.5× faster end to end (224 vCPU, ffmpeg 7.1) but its queue
  varies from minutes to 5h17 at peak (afternoon/evening VN). GPU starts almost at once. Suggest TPU
  when not urgent, GPU when urgent; if unclear ask one question. (chap30, chap51 logs.)

## Per-episode flow

1. **Find the folder.** A path on the default account → `gdrive:<path>`. A Drive link on another
   account (`u/1`, `u/2`, …) → `gdrive,root_folder_id=<FOLDER_ID>:` for EVERY rclone call. Confirm
   the series by the file prefix (`Binh_Thien_Sach_` vs `Dao_Si_Quen_`), not by "Chap N" — both series
   have folders with the same names. Say series + chương range in every report.
2. **Inventory** (read-only): voice (`.wav` > `.m4a` > `.mp3`), `Image/`, `Video/`, `Parallax/`,
   `Music/`, `*_vi_qa.srt`, `*_vi_qa.txt`, `*_music_prompts.txt`, `*_scene_anchors.md` or
   `.work/scene-plan.md`, `CTA voice/`, thumbnail folder, ending image, `*_DESCRIPTION_TEMPLATE.txt`.
   Count `Parallax/` vs `Image/` — they must match (see fx-parallax.md).
3. **Author `creative.yaml`** (see examples/). Rules: sfx-music.md, description-metadata.md,
   fx-parallax.md. Title comes verbatim from the series title list (series.yaml).
4. **Pin + stage** (lint runs inside stage; it also guards repo-public, module md5, idle kernel,
   config collision and a foreign checkpoint — and never writes `repo_ref`):
   ```bash
   .venv/bin/videotool creative sfx-pin "<source>" --picks picks.yaml --creative creative.yaml
   .venv/bin/videotool cloud stage "<source>" --creative creative.yaml --runtime tpu \
    [--slug <slug>] [--scene-workers 32] [--resume] [--template <file>]
   ```
   Stage uploads creative (+ template) and the runtime's config, then pings Telegram. `--dry-run`
   shows the plan without writing.
5. **User clicks.** Open the kernel for the chosen runtime (TPU: `pnd4189/videotool-render-tpu`,
   GPU: `pnd4189/videotool-render`) → Save & Run All. Still never `kaggle kernels push`.
6. **The watcher daemon does the rest** (`videotool-watchd.service`, no LLM): Telegram "started"
   when the new run reaches QUEUED/RUNNING (a stale COMPLETE/ERROR from an older run is ignored),
   clip counts + an early check of the checkpoint job.yaml while running, verify + "done" (and
   config cleanup) or "failed" with the first real error lines. Manual: `videotool renders`
   (table), `videotool renders status <slug>`, `videotool cloud watchd --once`,
   `videotool cloud finish <slug>`. CLI sessions surface status through the hook (Phase 5).
7. **Resume** after a disconnect: stage again with `--resume` and the same slug, user clicks again.

Code freshness is checked by stage itself (module md5 vs origin/main) — if it blocks, deploy first
(push main, then `rclone copyto` the 3 Colab modules to `_VIDEOTOOL_SHARED/`).

## Size cap

`render: {bitrate_cap: 2500k}` in creative.yaml selects `*-capped-2500k` (commit `083dcf4`);
`2200k` selects `*-capped-2200k` (commit `fbfcd6a`). Worst case ≈ (cap + 256) kbps × duration / 8.
User ceiling is 4.5 GB. 2-3.5h episodes → 2500k (the default 2800k overshoots near 3h); ≥ ~3.5h →
2200k (226 min at 2500k ≈ 4.6 GB). (chap31, chap34, render-size-cap-profile.)

## Failure triage

- Get the real log: `kaggle kernels output <kernel> -p <dir>` → `<kernel-slug>.log`
  (`videotool-render-tpu.log` on TPU), a papermill JSON array; look for the `===== *-mux.log =====`
  dump. The watcher does this itself and sends the first error lines. The log only appears on completion.
- `nvenc_can_encode=False` on GPU: read the ffmpeg stderr first; do not conclude "Kaggle broke NVENC".
  On the TPU box the NVENC probe failing is normal (it falls back to x264).
- Works locally, fails on the box: suspect ffmpeg version skew (GPU box 4.4.2, local 6.1, TPU 7.1).
- `pip` exit 128 "could not read Username": the repo went private. Check
  `GIT_TERMINAL_PROMPT=0 GIT_CONFIG_GLOBAL=/dev/null git ls-remote https://github.com/pnd4189/video-tool main`.
- `No render job config … Nothing to render`: the config was not staged (harmless, no quota spent).
- `No user secrets exist … RCLONE_CONF`: the secret is not attached — the user toggles it in the UI.
- Resume = the user clicks Save & Run All again. Everything prepare_job created is re-materialized
  by `_ensure_prepare_artifacts` (fixed `bcef822`, `3754fbf`, `4122ec1`).

## Timing references

TPU: ~30-60 min wall for 1.5-2.5h episodes, ~85 min for 3h. GPU: ~0.7-1.5× realtime, longer with an
overlay. Size is linear in duration. Numbers per episode live in the episode logs, not here.

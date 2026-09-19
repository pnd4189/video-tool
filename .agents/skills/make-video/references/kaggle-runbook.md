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
4. **Validate locally before staging**: run `cloud_director.apply_creative` / `run` on a scratch
   copy, check SFX survivors with `_filter_sfx_cues`, render the description with
   `render_description_template`, regex `[一-鿿]` on everything you wrote, count description chars.
5. **Stage all three files BEFORE telling the user to click** (dao-si-chap31: a click before the
   config existed killed a run):
   - `creative.yaml` → `gdrive:_VIDEOTOOL_SHARED/creative/<slug>.yaml`
   - description template → the SOURCE folder root as `<stem>_DESCRIPTION_TEMPLATE.txt` (the box
     only globs the job root; many Chap folders ship without one)
   - the config JSON for the chosen kernel:
     ```json
     {"source": "gdrive:1. YOUTUBE AUDIO/.../Chap N",
      "output": "gdrive:1. YOUTUBE AUDIO/.../Chap N/outputs",
      "checkpoint": "gdrive:_VIDEOTOOL_SHARED/checkpoints/<slug>",
      "creative": "gdrive:_VIDEOTOOL_SHARED/creative/<slug>.yaml"}
     ```
     TPU adds `"allow_cpu": true, "scene_workers": 32`. **Omit `repo_ref`** (the notebook default
     is the full `git+https://github.com/pnd4189/video-tool@main`; a bare `@main` broke pip once).
   - Verify each upload with `rclone lsl` + md5. `rclone copyto` has hung to a timeout without an
     error (dao-si-chap37); use absolute local paths (the shell cwd can reset between commands).
6. **Code freshness.** The box loads `cloud_director.py`, `cloud_render_runner.py`,
   `videotool_cloud.py` from `_VIDEOTOOL_SHARED/` at run time and pip-installs `videotool@main`.
   Before each render compare md5 of the three local modules with Drive. If they differ, stop and
   tell the user — deploying code is not a render step (push `main` first, then copy the modules).
7. **User clicks.** Open the saved kernel → pick the accelerator → Save & Run All. Never
   `kaggle kernels push`: a push detaches the `RCLONE_CONF` secret (it is base64 of
   `~/.config/rclone/rclone.conf`; only the user re-attaches it in the UI).
8. **Monitor** `kaggle kernels status <kernel>` every few minutes. A kernel shows the previous run's
   COMPLETE/ERROR until the new run reaches QUEUED/RUNNING — only a terminal state seen AFTER that
   counts. Queue time is not billed.
9. **Verify early** (~5-10 min after RUNNING): pull `checkpoints/<slug>/job.yaml` and check
   `inputs.{music,intro_image,ending_image,intro_cta,outro_cta,description_template}`, encoder name
   (the cap shows as `*-capped-2500k`, not as `bitrate_cap`), scene count, SFX count, overlay,
   `timing.source`. A wrong value can still be patched in the checkpoint job.yaml before scenes finish.
   Progress = count `checkpoints/<slug>/clips/youtube-16x9/scene-*.mp4`; it can sit at 0 for a long
   pre-render and jumps in batches.
10. **Verify the publish** (COMPLETE): `outputs/` holds `<title>.mp4`, `description.txt`,
    `captions.srt`, `captions.youtube.srt`, `chapters.json`, `quality-report.json` (11 checks),
    `thumbnail-1280x720.jpg`. Duration math: mp4 = intro CTA + narration + outro CTA (±0.1s) —
    an outro cut is invisible to QA. See pitfalls.md "verify" for how to read a multi-GB mp4 cheaply.
11. **Clean up** after verification:
    - First run `kaggle kernels status` on BOTH kernels. If the other kernel is RUNNING, its config
      belongs to a live render (maybe another session) — do not touch it (chap45 nearly deleted one).
    - Delete only the config file your episode used. Leaving it lets a stray Save & Run All
      re-render a published episode and overwrite its outputs.
    - The runner purges the checkpoint after a verified publish; now and then list
      `_VIDEOTOOL_SHARED/checkpoints/` for leftovers.
    - Local scratch keeps creative + config as the record; delete downloaded mp4s.

## Size cap

`render: {bitrate_cap: 2500k}` in creative.yaml selects `*-capped-2500k` (commit `083dcf4`);
`2200k` selects `*-capped-2200k` (commit `fbfcd6a`). Worst case ≈ (cap + 256) kbps × duration / 8.
User ceiling is 4.5 GB. 2-3.5h episodes → 2500k (the default 2800k overshoots near 3h); ≥ ~3.5h →
2200k (226 min at 2500k ≈ 4.6 GB). (chap31, chap34, render-size-cap-profile.)

## Failure triage

- Get the real log: `kaggle kernels output <kernel> -p <dir>` → parse `videotool-render.log`
  (papermill JSON) for the `===== *-mux.log =====` dump. The log only appears on completion.
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

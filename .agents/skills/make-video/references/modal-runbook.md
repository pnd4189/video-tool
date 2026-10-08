# Modal render runbook (runtime #2, after Kaggle)

GPU runtime order, user decision 2026-10-07: **Kaggle 1st, Modal 2nd, Colab 3rd.** Use Modal when the
user says "Modal", or when Kaggle is queued/out of quota. Modal is a pure compute helper here: the
episode is prepared and finished on this machine, Modal only runs `videotool render` on a T4, and no
Drive credentials ever go to Modal. Modal runs are invisible to `videotool renders`, the watcher
daemon and Telegram — say what is happening in the session.

Sources: first full run = Chap 67 (2026-10-07); Chap 65 and Kẻ Trừ Tà Tập 1 runs (2026-10-07/08); probes
of 2026-10-05 (kept under "Other probes" below); rates from
`modal billing rates` (2026-10-07); Modal docs on budgets, billing, egress, volumes, timeouts, cron
(read 2026-10-05).

## What it costs and how fast (measured)

- Chap 67, 2h12 narration, 225 scenes, parallax off, overlay on: render 66 min wall (all scene clips
  after ~18 min, the final overlay + subtitle + waveform pass ~48 min), 2.67 GB mp4, metered $1.52
  (covered by the credit). Kaggle GPU needed 4h34 for Chap 58 (2h02); Kaggle TPU is 30-60 min when
  its queue is empty. End to end (build, render, local sfx/package, download, Drive upload): ~90 min.
- Smoke test of `scripts/modal_render.py` as written here (2026-10-07): 10-minute slice with 18
  `Parallax/` clips + overlay, render 374 s, 205 MB, all of it (image build included) $0.24. Cheap
  enough to re-run after any edit to the script.
- Container: T4 + 8 cores + 32 GiB = $0.59 + 8 × $0.0473 + 32 × $0.008 ≈ $1.22/h. The render is
  CPU-bound (GPU use ~8%), so cores matter, not the GPU model.

## Budget rules (account-level, user 2026-10-05: never pay out of pocket)

The workspace is Starter with a card only to unlock the $30/month free credit (usage limit $30, spend
limit $0; the CLI does not show either). **Ask the user to confirm both once per session before the
first launch**, and give the worst case: rate × `timeout` × (retries + 1) × containers
(here 1.22 × 3 h ≈ $3.7). Refuse a launch whose worst case exceeds remaining credit minus ~$5.

- `modal run` only. Never `modal deploy`, `schedule=`, `min_containers`/keep-warm, Sandboxes,
  Notebooks, non-preemptible or region pinning (they cost 1.15-3x), or Modal inference endpoints /
  `ANTHROPIC_BASE_URL` (tokens are billed outside the credit from the first request).
- Every function sets `timeout=` and `retries=0` (the script does). No `--detach`: closing the client
  stops a plain run, which is the safety net.
- No H100/H200/B200; T4 is enough. Uploads *from* a container (rclone, bucket mounts) count as egress
  ($0.04/GiB past 1 TiB/month); Volume reads/writes and `modal volume get` do not. Keep the Volume
  small and delete it as soon as the files are local.
- Before: `modal app list` (nothing running), `modal volume list` (none left), `modal billing summary`.
  After: the same three; note the spend in the report.

## Flow

1. **Inspect, author, lint** exactly as SKILL.md steps 1-3 (creative.yaml, SFX picks, template,
   `creative lint` = 0 errors). Same rules, same files in `plans/scratch-<slug>/`.
2. **Stage and prepare locally** (never `cloud stage`, never write `_VIDEOTOOL_SHARED`):
   ```bash
   cd /home/dung/VIBE_CODING/video-tool; VT=.venv/bin/videotool
   SLUG=binh-thien-chapNN; STAGE="$HOME/.cache/videotool/$SLUG"; mkdir -p "$STAGE"
   REMOTE="gdrive:<path under the mount>/Chap NN"
   rclone copy "$REMOTE" "$STAGE" --transfers 8     # ~700 MB for 2h12; never cp through the mount
   cp plans/scratch-$SLUG/creative.yaml plans/scratch-$SLUG/*_DESCRIPTION_TEMPLATE.txt "$STAGE/"
   $VT prepare "$STAGE" --target cloud --creative "$STAGE/creative.yaml"
   $VT validate "$STAGE/job.yaml"
   ```
   Read the result before shipping: `timing` source, `enhance` (subtitles, yellow, visualizer, sfx cues,
   atmosphere), `inputs.particle_overlay` file present in `$STAGE`, `sfx/` files, `outputs/captions.srt`
   + `chapters.json`, scene durations summing to the narration length (the intro/ending cards overlay it).
3. **Launch** (background task, log to a file, keep the session alive until it ends):
   ```bash
   VT_JOB_DIR="$STAGE" VT_SLUG=$SLUG modal run .agents/skills/make-video/scripts/modal_render.py \
       > "$HOME/.cache/videotool/$SLUG-modal.log" 2>&1
   ```
   Optional `VT_WORKERS` (cores = scene workers, default 8) and `VT_TIMEOUT_S` (default 10800).
   Signals in the log, in order: image build (~3 min, ~1 min when cached) → `gpu: Tesla T4` →
   `encoder pinned: h264_nvenc-capped-2500k` → `render start (8 scene workers)` → `heartbeat:` every
   2 min (clip count climbs to all scenes, then the job dir grows ~0.5 GB per 10 min in the final pass)
   → `render finished rc=0` → `copied outputs + logs + job.yaml + render.log to volume, committed` →
   `Stopping app - local entrypoint completed`. **Stop and look** if there is no heartbeat after 5 min,
   `rc` is not 0, or the encoder is not `h264_nvenc-…` (the script aborts on a missing NVENC).
4. **Fetch, verify, clean the Volume**:
   ```bash
   DL="$STAGE-dl"; modal volume get vt-$SLUG / "$DL" --force
   ffmpeg -nostdin -v error -i "$DL/outputs/youtube-16x9.mp4" -f null -   # silent = clean, ~5 min
   modal volume delete vt-$SLUG --yes
   ```
5. **Finish locally** (the order matters; sfx ~7 min, package ~4 min on 2h12):
   ```bash
   cp "$DL/outputs/youtube-16x9.mp4" "$STAGE/outputs/"; cp "$DL/job.yaml" "$STAGE/job.yaml"
   mkdir -p "$STAGE/.videotool/tmp"; cp -r "$DL/logs" "$STAGE/.videotool/tmp/logs"
   $VT sfx "$STAGE/job.yaml"        # log line "Mixed SFX onto 1 output(s)"
   $VT package "$STAGE/job.yaml"    # expect 11/11 PASS
   $VT metadata "$STAGE/job.yaml"   # tags the mp4 and renames it to the episode title
   ```
6. **Verify** as SKILL.md step 5, plus: extract frames in the middle of several cues and look at them
   (burned yellow Vietnamese subtitles with correct diacritics, overlay, waveform strip, intro and
   ending cards); `captions.youtube.srt` first cue = intro CTA length; audio present in the first
   8 s and last 12 s; audio duration = intro CTA + narration + outro CTA.
7. **Publish** to the folder the user named (default `outputs/`), never anything else on Drive:
   ```bash
   rclone copy "$STAGE/outputs" "$REMOTE/outputs" --exclude "thumbnail-candidate-*.jpg"
   rclone lsl "$REMOTE/outputs"     # every size equals the local file
   ```
8. **Clean up**: ask the user before `rm -rf "$STAGE" "$DL"` (global rule). Keep `creative.yaml`,
   the template and `job.yaml` copy in `plans/scratch-<slug>/` as the record. Run the three Modal
   checks, report spend, and remind the user to upload `captions.youtube.srt` and paste `description.txt`.

## Gotchas (each learned on a real run)

- Modal does not ship empty directories: the script creates `media/` or render exits 2.
- `debian_slim` has no fonts; the image installs `fonts-liberation` so libass's default (Arial)
  resolves to Liberation Sans, the same face as this machine. Not tested without it.
- This module is imported inside the container too, so the script reads its parameters with
  `os.environ.get` + `modal.is_local()` and bakes them into the image with `.env()`. Keep it that way
  when editing; a bare `os.environ["…"]` or `parents[4]` at import time crashes the container.
- `videotool prepare --target cloud` already links `Parallax/`; the script re-links (a no-op) and
  runs the same parallax and title-card checks as `cloud_render_runner`. Stills without a clip stay
  Ken Burns; on-box depth (`parallax_on_box`) is not set up on Modal.
- `package` fails its `render_log` check unless `.videotool/tmp/logs` exists; step 5 restores the
  ffmpeg logs from the Volume. (Chap 67 first ran without them and showed 10/11.)
- Modal's ffmpeg is 5.1.9 (Kaggle GPU 4.4.2, local 6.1); output checked frame by frame on Chap 67.
- With 223 even-split stills the video stream ended ~0.4 s after the audio (frame rounding per
  clip, an inference); harmless, and subtitle sync is unaffected because audio is not stretched.
- `Metered Cost` in `modal billing summary` is not what you pay: `Billed Cost` after credits is.
- Preemption restarts the function from zero: scene clips live on the container disk and reach the
  Volume only after the render, so Chap 65 lost 226/236 clips (16 min, ~$0.33) when its container was
  preempted and the restart rendered from clip 1 (`binh-thien-chap65-modal.log`, "Container terminated
  due to preemption"). Budget one restart; a mid-render Volume checkpoint would need a script change.

## Other probes (2026-10-05, not part of the render flow)

- DepthFlow 1.0.1 (pip, `WINDOW_BACKEND=headless`) runs on the T4 with EGL out of the box: a 5 s
  1080p30 clip from a 1280×720 still took 25 s cold (depth model download), 4.4 s warm.
- VieNeu Turbo v3 TTS on CPU: ONNX defaults to the host core count (20) → RTF 2.6; pin
  `intra_op_num_threads` to 4 → RTF ~0.6. Needs `huggingface_hub==1.20.1` and `onnxruntime==1.27.0`
  (newer hub shards blobs and ORT rejects them with "External data path escapes model directory").

## Files

- `scripts/modal_render.py` — the Modal app (render step only). Edit only when the user asks.
- This runbook; `kaggle-runbook.md` for the primary runtime; `lessons-inbox.md` for new findings.

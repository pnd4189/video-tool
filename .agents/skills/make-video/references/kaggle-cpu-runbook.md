# Kaggle CPU render runbook (headless lane)

Use it when the user says "Kaggle CPU" / "CPU", or wants to save GPU/TPU quota and can wait overnight.
No browser click: the CLI pushes a **new private CPU kernel per episode**. Shaped like Modal: the episode
is prepared and finished on this machine, Kaggle only renders, and no Drive key goes to Kaggle (the rclone
key has full-Drive scope). CPU sessions are not counted against the GPU 30 h / TPU 20 h weekly quota.
These runs are invisible to `videotool renders`, the watcher and Telegram — report in the session.

Sources: user decisions and design 2026-10-12 (`plans/261012-0632-kaggle-cpu-render-lane/`); the
headless pattern of TTS_Local (21 chapters on Kaggle CPU via `kaggle kernels push`, 30/09–03/10,
`TTS_Local/.kaggle-bts-v2.log` — about 60 CPU-hours in 2.5 days, no quota hit); Kaggle CLI 2.2.4 help;
modal-runbook.md gotchas.

## Speed (estimate until the first real run)

- A 4-core Kaggle box with x264 rendered an 8-min synthetic job at 0.39× realtime
  (`Colab/videotool-render-tpu.ipynb` table, 2026-07-24): ~6 h for a 2h20 episode, ~9 h at the 3.5 h
  cap. Kaggle ends a session at 12 h; the kernel is pushed with `-t 41400` (11.5 h).
- Around it, on this machine: bundle upload ~0.7–1 GB (~0.8 MB/s measured on Modal ≈ 15–20 min),
  ~3 GB mp4 download, sfx ~7 min, package ~4 min, Drive publish.
- First real run (Chap 71): _to measure — fill in upload / render / download / finish times._

## Rules

- **Narration ≤ 3.5 h** (user 2026-10-12). `submit` refuses longer episodes: this lane cannot resume, so
  they go to Kaggle GPU/TPU or Modal.
- **Same code as the other lanes.** `submit` refuses unless `src/ Colab/ pyproject.toml README.md` are
  committed and equal to `origin/main` (what the GPU/TPU boxes install) and the box script is committed.
- **Only this script pushes, only `<owner>/videotool-cpu-*` kernels**; it refuses the frozen
  `videotool-render` / `videotool-render-tpu` kernels by name. Agents never run `kaggle kernels push`
  themselves. agy may run this lane (user 2026-10-12); its guard still blocks raw pushes.
- Dataset and kernel are private. The stage is scanned for credentials before upload (names like
  `rclone.conf`, `kaggle.json`, `access_token`, `.env`; small files containing `refresh_token`,
  `client_secret`, `PRIVATE KEY`); any hit refuses the upload.
- Never a published episode: `publish` writes into its `outputs/`.
- One episode = one kernel + one dataset, so several episodes can run at once. Kaggle's limit on
  concurrent CPU sessions is unverified (a forum report says 5).

## Flow

1. **Inspect, author, lint**: SKILL.md steps 1-3.
2. **Stage and prepare locally**: modal-runbook.md step 2, same commands (`rclone copy`, copy creative +
   template into `$STAGE`, `videotool prepare --target cloud`, `videotool validate`).
3. **Dry run** — read it before launching: private, `enable_gpu/tpu: false`, one dataset source,
   narration, expected video length, bundle size, credential scan clean.
   ```bash
   KCPU=".venv/bin/python .agents/skills/make-video/scripts/kaggle_cpu_render.py"
   $KCPU submit "$STAGE" --dry-run
   ```
4. **Launch** (background task, keep the session open; the machine must stay on until publish):
   ```bash
   $KCPU run "$STAGE" --remote "gdrive:<path under the mount>/Chap NN" \
       > "$HOME/.cache/videotool/$SLUG-kcpu.log" 2>&1
   ```
   Driver lines, in order: `packing` → `bundle … credential scan clean` → `uploading private dataset` →
   `pushed <kernel>` → `<kernel>: running` → every 10 min `box [ …s] heartbeat: N/M clips …` →
   `render COMPLETE on Kaggle CPU after X h` → `fetched … sha256 ok` → `sfx mixed` → `package QA …` →
   `verified …` → `published N files, sizes match` → `deleting kernel …` / `deleting dataset …`.
   Box lines in the first minutes: `box: python … cpu`, `ffmpeg:`, `font:`, `disk free:`, `bundle ok:`,
   `encoder pinned: libx264-balanced-capped-2500k`, `render start (4 scene workers, N scenes)`.
   **Stop and look** at any `FAILED:` line.
5. **At ~60 min** compare the heartbeat clip rate with the estimate. If the render projects past 11 h,
   `$KCPU cleanup "$STAGE" --force` and re-route the episode to GPU/TPU.
6. **Verify** as SKILL.md step 5 plus frames (modal-runbook.md step 6). `finish` already checked h264
   1920×1080 + aac, audio = intro CTA + narration + outro CTA (±0.3 s), video within 1 s of audio,
   < 4.5 GB, `captions.youtube.srt` starting at the intro CTA, package QA, "Mixed SFX onto 1 output(s)".
7. **Local cleanup**: ask the user before deleting `$STAGE`, `$STAGE-dl`, `$STAGE-kcpu` (global rule).

## Recovering

Every step re-runs on its own from `$STAGE/.kaggle-cpu.json`: `watch`, `fetch`, `finish`,
`publish --remote …`, `cleanup [--force]`, `status`.
- `submit` refuses while a run is open: finish it, or `--force`.
- Box failure in the first minutes = the Kaggle image (an image change killed 10 TTS runs in 13 min on
  2026-10-03). The log prints python, ffmpeg, font and disk; report it, do not patch the box script.
- `fetch` retries the download 3×, checks the mp4 sha256 and refuses output from another submission
  (bundle hash differs).

## Files

- `scripts/kaggle_cpu_render.py` (local driver) and `scripts/kaggle_cpu_box.py` (runs on Kaggle). Edit
  only when the user asks.
- `$STAGE/.kaggle-cpu.json` state · `$STAGE-kcpu/` bundle · `$STAGE-dl/` kernel output.

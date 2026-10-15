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

## Speed

- **Chap 71 trial** (2026-10-12, 3.27 h video; box = 4 vCPU on 2 cores + SMT, 31 GiB, ffmpeg 6.1.1,
  Python 3.13): bundle 887 MiB uploaded in ~1 min; clips with x264 `medium` 416 min (2.12 h per
  video-hour, 0.72 clip/min); then the mux re-encoded the whole video to draw subtitles + waveform at
  ~0.53× realtime (~1.9 h per video-hour). Needed ~13.1 h, Kaggle cut it at 11.5 h, nothing was saved.
  The old 0.39× estimate came from an 8-min synthetic job without overlay, subtitles or waveform — never
  size this lane from a synthetic job again.
- **Since 2026-10-13** the box renders x264 `faster` with the overlays baked into the scene clips
  (`render.bake_overlays`, mux = stream copy). Bench on the real Chap 71 plan projects **~1.9 h per
  video-hour** (Chap 71 ≈ 6.3 h, 3.5 h of narration ≈ 6.8 h) and a sharper picture (one encode, not two:
  SSIM 0.956 vs 0.950). Local A/B on a 6-min cut: −52 % CPU time, subtitles switch on the same frame as
  the old path, waveform aligned. Numbers: `plans/261012-0632-kaggle-cpu-render-lane/phase-06-baked-overlays.md`.
- **Measured 2026-10-13** (two episodes at once, one kernel each): Chap 71, 3.27 h of video — clips 5.9 h
  (1.81 h per video-hour) + mux 0.5 h = 6.45 h on the box, 6.57 h from submit, 4.14 GB; Chap 72, 2.89 h —
  clips 5.4 h (1.87) + mux 0.5 h = 5.86 h, 5.91 h from submit, 3.66 GB. Budget ~2 h of box per video-hour
  end to end: 3.5 h of narration ≈ 7.1 h, well inside the 10.75 h stop.
- Size: `faster-capped-2500k` averaged 2.81 Mbit/s on Chap 71, 2 % over (cap + 256) × duration; 3.5 h of
  narration at 2500k would land near 4.43 GB, 70 MB under the ceiling.
- Around it, on this machine: download 4.1 GB in ~7 min, sfx ~8 min, package ~4 min, Drive publish ~5 min.
  Finishing a render here (safety net) takes ~25 min per hour of video still missing (6-min A/B: 152 s).

## Rules

- **Narration ≤ 3.5 h** (user 2026-10-12). `submit` refuses longer episodes; they go to Kaggle GPU/TPU or
  Modal.
- **Safety net** (user 2026-10-13): the box stops at timeout − 45 min (10.75 h), ships its finished clips
  and exits cleanly; `fetch` then finishes the render on this machine (`the box stopped at its deadline…`)
  and the run continues as usual. The machine must stay on.
- **Same code as the other lanes.** `submit` refuses unless `src/ Colab/ pyproject.toml README.md` are
  committed and equal to `origin/main` (what the GPU/TPU boxes install) and the box script is committed.
- **Only this script pushes, only `<owner>/videotool-cpu-*` kernels**; it refuses the frozen
  `videotool-render` / `videotool-render-tpu` kernels by name. Agents never run `kaggle kernels push`
  themselves. agy may run this lane (user 2026-10-12); its guard still blocks raw pushes.
- Dataset and kernel are private. The stage is scanned for credentials before upload (names like
  `rclone.conf`, `kaggle.json`, `access_token`, `.env`; small files containing `refresh_token`,
  `client_secret`, `PRIVATE KEY`); any hit refuses the upload.
- Never a published episode: `publish` writes into its `outputs/`.
- One episode = one kernel + one dataset, so several episodes can run at once: two did on 2026-10-13.
  Kaggle's limit on concurrent CPU sessions is unverified (a forum report says 5).

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
   `verified …` → `published N files, sizes match` → `deleting kernel …` / `deleting dataset …` →
   `freed X GB: deleted <slug>, <slug>-dl, <slug>-kcpu; review kept in …/<slug>-review`.
   Box lines in the first minutes: `box: python … cpu`, `ffmpeg:`, `font:`, `disk free:`, `bundle ok:`,
   `encoder pinned: libx264-faster-capped-2500k, overlays baked into the scene clips`,
   `render start (4 scene workers, N scenes, stops at 10.75 h …)` — N = storyboard + 2 CTA cards.
   **Stop and look** at any `FAILED:` line.
5. **At ~60 min** compare the heartbeat clip rate with ~1.9 h per video-hour. Past 10.75 h the safety net
   takes over by itself; only a box far slower than measured is worth `cleanup --force` + GPU/TPU.
   A waiter must also end when the kernel ends (status terminal / the log follower exits): a grep for
   "render finished" never fires when Kaggle kills the box.
6. **Verify** as SKILL.md step 5 plus frames (modal-runbook.md step 6). `finish` already checked h264
   1920×1080 + aac, audio = intro CTA + narration + outro CTA (±0.3 s), video within 1 s of audio,
   < 4.5 GB, `captions.youtube.srt` starting at the intro CTA, package QA, "Mixed SFX onto 1 output(s)",
   then `videotool review` (warnings only): its lines are in the log; open
   `$STAGE-review/contact-sheet.png` (the purge moved it there).
7. **Local cleanup is automatic** (user 2026-10-15): `run` ends with `purge`, which re-checks every
   `outputs/` file on Drive at its size, then deletes `$STAGE`, `$STAGE-dl`, `$STAGE-kcpu` and keeps only
   `$STAGE-review/` (~7 MB) and the log. The pre-SFX master goes too: an SFX fix after publish means a
   re-render. Any failed step stops before the purge, so a broken run keeps everything for recovery.

## Recovering

Every step re-runs on its own from `$STAGE/.kaggle-cpu.json`: `watch`, `fetch`, `finish`,
`publish --remote …`, `cleanup [--force]`, `purge`, `status`. Once purged there is no state left to
re-run from.
- `submit` refuses while a run is open: finish it, or `--force`.
- Box failure in the first minutes = the Kaggle image (an image change killed 10 TTS runs in 13 min on
  2026-10-03). The log prints python, ffmpeg, font and disk; report it, do not patch the box script.
- `fetch` retries the download 3×, checks the mp4 (or `clips.tar`) sha256 and refuses output from another
  submission (bundle hash differs). A partial result finishes here; re-running `fetch` resumes it.

## Gotchas (Chap 71 trial, 2026-10-12)

- `kaggle datasets status` answers 403 for this account's token; presence is read from `datasets files`.
- `kaggle kernels logs` is empty while the kernel runs; `-f` replays and follows. A finished kernel's log
  is a JSON array of `{stream_name, time, data}`; the driver turns it back into text.
- The `-t` timeout is fixed at push: a running kernel cannot be given more time.
- Clip encodes are not bit-reproducible run to run (same before and after baking): compare frames by
  eye or SSIM, never by md5.

## Gotchas (Chap 71/72, 2026-10-13)

- The music mix (`amix`) dropped 0.03-0.33 s off the outro CTA and `-shortest` cut the video to match;
  Chap 71 missed the ±0.3 s audio check by 0.01 s. The cut was the outro's trailing silence, and the user
  had it published by hand. Fixed in `affc153` (voice padded before the mix, baked mux cut with `-t`).
  A `FAILED:` in `finish` stops the run before Drive: report it, never mark the state finished yourself.

## Files

- `scripts/kaggle_cpu_render.py` (local driver) and `scripts/kaggle_cpu_box.py` (runs on Kaggle). Edit
  only when the user asks. `scripts/purge_stage.py` deletes the stage after publish (all local lanes).
- `$STAGE/.kaggle-cpu.json` state · `$STAGE-kcpu/` bundle · `$STAGE-dl/` kernel output ·
  `$STAGE-review/` contact sheet + loudness, kept after the purge.

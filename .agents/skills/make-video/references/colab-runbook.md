# Colab CLI render runbook (default lane)

The default render since 2026-10-20 (user: the Kaggle account is banned; the Google AI Pro plan brings
200 Colab compute units a month). No browser tab: the official Colab CLI (`colab`) rents a high-RAM CPU
VM and `scripts/colab_render.py` uploads the prepared episode, runs the Kaggle CPU lane's box script on
it, downloads the render and stops the VM. Shaped like Modal and the Kaggle CPU lane: the episode is
prepared and finished on this machine, Colab only renders, no Drive key goes to the VM (the rclone key
has full-Drive scope). These runs are invisible to `videotool renders`, the watcher and Telegram —
report in the session.

Sources: probes and a 1 GiB transfer test on a high-RAM VM, 2026-10-20 (CLI 0.7.4); three end-to-end
runs of a 75-s job, 2026-10-20 (submit → render → fetch → VM stopped in 93-157 s, the last one with the
keeper cutting the mp4 into parts; `finish` package QA 11/11); two liveness tests with no client attached
(2.5-h and 4-h boxes), 2026-10-20; Colab's FAQ on runtime limits and its pricing page (read 2026-10-20); the
CLI 0.7.4 source, its bundled docs (`colab readme`, `colab skill`) and its design doc
`docs/01_session_management.md` + PR #144 on GitHub (liveness); kaggle-cpu-runbook.md for the box.

## Account, machine, cost

- Login: `colab whoami` must show the user's Google AI Pro account, not another of their Google accounts
  (checked 2026-10-20; scopes include `colaboratory`). `colab usage` = balance, rate, active assignments.
- High-RAM CPU VM (`colab new --high-mem`, shape `m-hm-…`): 8 vCPU (4 cores + SMT, Xeon 2.2 GHz),
  51 GiB RAM, ~205 GiB free disk, Ubuntu 24.04, Python 3.13, ffmpeg 6.1.1, `fc-match Arial` = Liberation
  Sans like this machine (a yellow Vietnamese subtitle frame came out identical on both).
- **0.26 CU/h** → 200 CU ≈ 770 VM-hours a month. The 13-min probe VM cost 0.04 CU. The balance is shared
  with every other project on the account (several use the same CLI). Worst case for one episode: a VM
  kept to Colab's 12-h limit ≈ 3.1 CU, under the ~10-CU "ask first" line of the user's global rules.
- Also eligible on this account: GPU T4/L4/A100/G4, TPU v5e1/v6e1 (not H100). This lane uses CPU only.

## Keeping the VM alive

- No browser tab, and since CLI 0.7.4 no client pings either: the Colab backend keeps a VM alive "based
  on kernel activities and active connections" and reclaims it after inactivity (PR #144 and the CLI design
  doc `docs/01_session_management.md`, 2026-09-25; the old 60-s ping became a no-op). Measured below:
  with nothing connected, that does not hold past about 3 h on this account.
- So the lane runs a **keeper cell** (`KEEP`) in the kernel's foreground for the whole render: it waits
  on the box, rewrites `/content/vt-out/status.json` every 30 s and prints a beat. The driver reads that
  file over the file API, which answers while the kernel is busy, and starts the keeper again when the
  file stops moving for 3 polls. While the keeper runs, a `colab exec` on that VM waits behind it:
  never run one by hand during a render.
- The keeper's local `colab exec` only holds the connection, detached from the driver; killing it does
  not stop the cell (the CLI installs no signal handler).
- When the box ends, the keeper cuts every output over 64 MiB into parts beside it, then says `ended`
  and keeps the VM — and the render on it — for `FETCH_GRACE_S` (6 h, ≈ 1.6 CU; 1 h after a failed box)
  in case the driver is not running. `fetch` downloads the parts over the file API, no `colab exec`, and
  stops the VM at once. Past the grace the kernel goes idle and Colab reclaims the VM with the render.
  With nothing connected here the 6-h hold fails: the VM was gone about 3 h after the last contact, also
  about 3 h after it started (measured below; which clock counts is not known).
- **Measured 2026-10-20, two liveness tests**: a fake box under the keeper (2.5 h, then 4 h), the local
  `colab exec` killed 3-4 min after the VM was created, then only account-level `colab sessions` checks
  (every 30 min, then every 5 min). Both VMs vanished about 3 h after the cut: test 1 between 2 h 30 m and
  3 h 00 m after it (VM age 2 h 33 m-3 h 03 m), test 2 between 2 h 59 m and 3 h 01 m after it (age
  3 h 03 m-3 h 05 m) with its box due to run another 55 min, so this is not idle reclaim after the grace.
  Not shown: whether the keeper cell kept beating after the cut (no read after it succeeded); whether the
  clock is VM age or time since the last contact (both cuts came 3-4 min after creation); whether the
  lane's real pattern (the keeper's exec held attached, a status read every 120 s) carries a VM past
  3 h. Background execution ("execution to continue after the browser closes up to … 24 hours") is a
  Colab Pro+ feature (pricing page FAQ) and, among Google AI plans, Ultra's only (Google Developers Blog,
  2026-09-22); this account's VMs report `subTier` 1 = Pro (2 = Pro+, enum in Colab's VS Code extension),
  so it has none (checked 2026-10-21). **So keep this machine on and the driver
  running for the whole render**, and until a run with the real pattern passes 3 h, tell the user before
  launching an episode whose render may run past ~3 h: losing the VM loses the render.
- Ceiling 12 h (`SESSION_CAP_S`): Colab's FAQ (2026-10-20) says notebooks "can run for at most 12 hours,
  depending on availability and your usage patterns"; 24 h is Pro+ only and this account is Pro. The box
  ships its finished clips at 10.75 h (`STOP_AFTER_S`, the Kaggle CPU lane's safety net and margin) and
  this machine finishes the render; the fetch grace ends at the 12-h limit at the latest.

## Speed

chưa đo on a real episode. Same box as the Kaggle CPU lane (x264 `faster`, overlays baked) with 8 scene
workers instead of 4, so expect faster than Kaggle's ~1.9 h per video-hour — but size nothing from that
guess or from the 75-s e2e job: record the first real episode's clip rate and total here.

## Transfers (measured 2026-10-20, 1 GiB random file, sha256 checked)

| Path | Up | Down |
|---|---|---|
| `colab upload/download`, 64 MiB parts, 8 at once (this lane) | ~15.5 MiB/s | ~24 MiB/s |
| the same, one part at a time | ~2.5 MiB/s | — |
| `colab ssh` + `cat`, one stream | 3.9 MiB/s | 7.2 MiB/s |

A ~1 GB bundle goes up in ~1 min, a 4 GB mp4 comes down in ~3 min.

## Rules

- **Narration ≤ 3.5 h** — the Kaggle CPU lane's cap (user 2026-10-12), kept until a real Colab run is
  measured. `submit` refuses longer episodes: ask the user (Modal, local, or a higher
  `--max-narration-hours`).
- **Same code as the other lanes.** `submit` refuses unless `src/ Colab/ pyproject.toml README.md` are
  committed and equal to `origin/main` and the box script is committed (shared preflight).
- **Compute units.** VMs only through this script: never `colab new`/`run`/`ssh` by hand, never `--gpu`
  or `--tpu`, never `colab pay`. `submit` refuses under 5 CU. The script stops the VM after a verified
  download and after a box failure, and logs the balance before and after.
- **Own CLI state file** `~/.config/colab-cli/videotool-sessions.json` (the script passes `--config` to
  every call): a bare `colab stop` in another project cannot reach a render. By hand:
  `colab --config ~/.config/colab-cli/videotool-sessions.json sessions` (`status -s vt-<slug>`, `stop -s …`).
- One episode = one VM `vt-<slug>`; several may run at once (Colab's concurrency limit: chưa đo).
- The shared credential scan refuses a stage holding anything that looks like a key.
- agy may run this lane.

## Flow

1. **Inspect, author, lint**: SKILL.md steps 1-3.
2. **Stage and prepare locally**: modal-runbook.md step 2, same commands (`rclone copy`, creative +
   template into `$STAGE`, `videotool prepare --target cloud`, `videotool validate`).
3. **Dry run** — read it before launching: session `vt-<slug>`, CPU high-RAM, parts, narration, expected
   video length, credential scan clean.
   ```bash
   CR=".venv/bin/python .agents/skills/make-video/scripts/colab_render.py"
   $CR submit "$STAGE" --dry-run
   ```
4. **Launch** (background task; this machine stays on until publish, the driver runs here):
   ```bash
   $CR run "$STAGE" --remote "gdrive:<path under the mount>/Chap NN" \
       > "$HOME/.cache/videotool/$SLUG-colab.log" 2>&1
   ```
   Driver lines, in order: `packing` → `bundle … credential scan clean` → `creating vt-<slug> (CPU,
   high-RAM); balance …` → `vt-<slug> ready (m-hm-…), uploading …` → `uploaded in Ns, sha256 checked on
   the VM` → `box started … a keeper cell keeps the kernel busy …` → the box's first lines (`box: python 3.13 | 8 cpu`, `ffmpeg:`, `font:`,
   `disk free`, `bundle ok`, `videotool:`, `encoder pinned: libx264-faster-capped…`, `render start (8
   scene workers, N scenes, stops at 10.75 h …)`) → every 10 min `box [ …s] heartbeat: N/M clips …` →
   `render COMPLETE on Colab after X h` → `downloading … GB` → `downloaded in Ns, sha256 ok` → `stopping
   vt-<slug>` → `compute units A -> B` → `fetched …` → `sfx mixed` → `package QA …` → `verified …` →
   `published N files, sizes match` → `freed …`. **Stop and look** at any `FAILED:` line.
5. **At ~60 min** compare the heartbeat clip rate with the speed section; the first real run sets it.
6. **Verify** as SKILL.md step 5; `finish` already checked streams, durations (±0.3 s), size, the YouTube
   captions offset and package QA, and `review` printed its warnings into the log.
7. **Local cleanup is automatic**, as in kaggle-cpu-runbook.md step 7; `$STAGE-colab/` goes too.

## Recovering

Every step re-runs from `$STAGE/.colab-cpu.json`: `watch`, `fetch`, `finish`, `publish --remote …`,
`purge`, `cleanup [--force]`, `status`.
- The driver stopped (session closed, Ctrl-C): the box keeps rendering, but with nothing here talking to
  the VM Colab took it about 3 h after the last contact, also about 3 h after it started (measured above),
  render and all; the keeper's detached exec may still hold it if this machine stayed on. Re-run `watch`
  at once (a status read every 2 min, the keeper restarted when status.json stops moving), then `fetch`,
  `finish`, `publish --remote …`, `purge` in turn, or `cleanup --force` to give the run up.
- `watch` says the VM is gone (Colab reclaimed it): nothing to fetch; fix the cause, `submit --force`.
- `watch` says status.json stopped moving and starts the keeper again: something ended the cell (a kernel
  restart); the box itself runs outside the kernel and is not affected.
- `watch` says 5 polls failed but the VM is still listed: network trouble here; re-run `watch`.
- Box failure: logs in `$STAGE-colab/` (`box.log`, `render.log`), the VM already stopped. A failure in
  the first minutes is the Colab image (python/ffmpeg/font lines): report it, do not patch the box.
- `submit` refuses while a run is open: finish it, `cleanup --force`, or `submit --force` (stops the old VM).
- Expired login: the lane never waits for a pasted code; the user runs `! colab whoami` in the session.

## Gotchas (CLI 0.7.4, 2026-10-20)

- `colab exec` exits 0 even when the code raised or called `sys.exit(3)`: the lane trusts only the
  `VTCOLAB {json}` line its snippets print.
- `colab exec/run --timeout` defaults to 30 s and only stops waiting; the code keeps running. Hence the
  detached box, and the keeper's exec held open by a detached local process.
- `colab upload/download` hold the whole file in memory as one base64 JSON request: past 64 MiB the lane
  sends parts.
- `colab ssh` takes one connection per VM (HTTP 429 for a second) and is 3-4× slower than the parts.
- 0.7.4 (PyPI 2026-09-26) removed the client keep-alive daemon (PR #144) and refreshes the runtime token
  on its own (#149). Docs or code that mention a keep-alive daemon describe ≤ 0.7.2. `colab update`
  reports newer versions: upgrade between renders, never during one.
- `colab sessions` lists every VM on the account; `[?]` marks one this state file does not know — another
  project's (2026-10-20: a T4 TTS job ran beside the tests). Never stop those.

## Files

- `scripts/colab_render.py` (local driver; reuses `kaggle_cpu_render.py` for preflight, bundle, finish,
  verify, publish, purge) and `scripts/kaggle_cpu_box.py` (runs on the VM with
  `VT_BOX_INPUT=/content/vt-in`, `VT_BOX_WORK=/content/vt-out`). Edit only when the user asks.
- `$STAGE/.colab-cpu.json` state · `$STAGE-colab/` bundle + manifest (+ box logs of a failed run) ·
  `$STAGE-dl/` the download · `$STAGE-review/` kept after the purge.

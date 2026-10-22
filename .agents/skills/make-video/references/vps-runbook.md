# VPS render runbook (Oracle, only on request)

Runs only when the user names the VPS (user 2026-10-21); the default stays Colab CLI, then Modal.
`scripts/vps_render.py` is the Colab lane with an ssh transport: the episode is staged, prepared, finished
and published on this machine, the VPS only runs the same box script (`kaggle_cpu_box.py`). **No Drive key on
the VPS** — the rclone key has full-Drive scope and the VPS runs other services.

Sources: setup and a 12-min benchmark on the VPS, 2026-10-21; the first full episode, BT Chap 82, 2026-10-22
(below); colab-runbook.md for the shared box.

## Machine

- `ssh oracle-vps` (alias in this machine's `~/.ssh/config`): Oracle Always Free A1, 2 Ampere Neoverse-N1
  cores (no SMT), 11 GiB RAM, ~110 GB free, Ubuntu 24.04. Always Free covers 1,500 OCPU-h + 9,000 GB-h a month
  = 2 cores / 12 GB around the clock; 4 cores would use it up in ~15 days (Oracle docs, read 2026-10-21).
- User `ubuntu` has no password, so no `sudo`: everything lives in `~/vtbench`, set up without root:
  - `ff/bin/{ffmpeg,ffprobe}`: BtbN static build `ffmpeg-n8.1-latest-linuxarm64-gpl-8.1.tar.xz` (n8.1.3);
    Colab and this machine run Ubuntu's 6.1.1. Accepted on condition that the first full episode passes `finish`
    QA (user 2026-10-21): BT Chap 82 did, 2026-10-22 (11/11, audio = expected to the 0.01 s, review 0 warnings).
  - `py/`: `python3 -m venv --without-pip py`, then `py/bin/python get-pip.py` (python3.12-venv is not installed).
    The box pip-installs the shipped videotool into it on every run.
  - Fonts: `fc-match Arial` = Liberation Sans, as on Colab.
- The VPS's own `gdrive:` rclone remote had an expired token (2026-10-21). The lane does not need it.

## Speed

- Chương 991 of BT Chap 77 (724.6 s of video, 20 clips, overlay baked, 2500k cap, 2 scene workers), 2026-10-21:
  render 21.6 min = **1.79 h per video-hour**, ~1.75× the Colab high-RAM VM. Bundle up: 221 MiB in 9 s.
- **BT Chap 82, the first full episode** (3 h 57 of narration, 303 clips, 2000k cap), 2026-10-21/22: box render
  8.73 h = 2.21 h per video-hour, while another project's ffmpeg + headless-chromium job shared the two cores
  for part of the night; clips ~8.5 h, mux ~15 min. Up: 921 MiB in 37 s. **Down: the 4.08 GB mp4 took 42 min**
  (~1.6 MB/s); sfx, package, review and publish ~25 min more. Submit → published: 9.9 h.

## Rules

- **Only on request.** One job at a time: `submit` takes `~/vtbench/jobs/.lock` and refuses while another
  episode holds it, when the load is over 1.5 (VieNeu TTS shares the two cores; `--force` overrides the load
  only) or under 20 GB is free.
- **No narration cap and no safety-net stop** (user 2026-10-21): the VPS has no session wall, and the safety net
  would leave unfinished clips for this machine to render.
- **Bitrate cap by length**: 2500k from ~2 h, 2200k from ~3.5 h, 2000k from ~3.9 h — the published mp4 must stay
  under 4.5 GB (`verify`), and the file runs ~2 % over (cap + 256 kbps) × duration.
- **Same code as the other lanes**: the shared preflight (code parity with `origin/main`, credential scan).
- This machine must be on for `submit` (upload) and from `fetch` on (download, finish, publish). In between the
  box runs on its own: the driver may stop; re-run `watch`.

## Flow

1. Inspect, author, lint: SKILL.md steps 1-3. Stage and prepare as colab-runbook.md Flow step 2.
2. Dry run (packs the bundle, reads the VPS's load/disk/lock, uploads nothing):
   ```bash
   VR=".venv/bin/python .agents/skills/make-video/scripts/vps_render.py"
   $VR submit "$STAGE" --dry-run
   ```
3. Launch (background task; log to a file):
   ```bash
   $VR run "$STAGE" --remote "gdrive:<path under the mount>/Chap NN" > "$HOME/.cache/videotool/$SLUG-vps.log" 2>&1
   ```
   Lines: `packing` → `bundle … VPS load …, lock free` → `uploading to oracle-vps:vtbench/jobs/<slug>` →
   `uploaded in Ns` → `box started on oracle-vps (pid …)` → the box's first lines (`box: python 3.12.3 | 2 cpu`,
   `ffmpeg: … n8.1.3`, `font:`, `bundle ok`, `encoder pinned: libx264-faster-capped…`, `render start (2 scene
   workers, N scenes)`) → `heartbeat: N/M clips` every 5 min → `render COMPLETE on the VPS after X h` →
   `downloading … GB` → `downloaded in Ns, sha256 ok` → `freed the VPS …` → `fetched …` → `sfx mixed` →
   `package QA …` → `verified …` → `published N files, sizes match` → `freed …`. **Stop and look** at `FAILED:`.
4. Verify as SKILL.md step 5. Local cleanup is automatic (`$STAGE-vps/` goes too).

## Recovering

Every step re-runs from `$STAGE/.vps.json`: `watch`, `fetch`, `finish`, `publish --remote …`, `purge`,
`cleanup [--force]`, `status`.
- The driver stopped (session closed, machine asleep, network): the box keeps rendering; re-run `watch`.
- Box failure: logs in `$STAGE-vps/` (`box.log`, `render.log`); the job folder, `/tmp/vt` and the lock are
  already freed on the VPS. A failure in the first minute is the VPS setup (python/ffmpeg/font lines).
- Give a run up: `cleanup --force` stops the box's process group and frees the VPS.

## Gotchas (2026-10-21)

- A remote command that backgrounds a process must close every fd and leave the ssh session: `cd x && cmd &`
  backgrounds the whole `&&` list, which then holds the session until the box ends (the first manual test hung
  that way). The driver launches through a detached `Popen` and `ssh -n`.
- The box unpacks into `/tmp/vt` without clearing it: the launch deletes it first (one job at a time).
- The download is the slow leg: one `scp` stream VPS → here ran ~1.6 MB/s on 2026-10-22, against ~25 MB/s the
  other way, so a 4 GB render needs ~40 min to come down (cause not measured).

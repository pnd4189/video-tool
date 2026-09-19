# Pitfalls, by stage

Each line: the trap → what to do (source). "Fixed" items stay only where the symptom may still be
seen. New lessons do NOT go here directly — see lessons-inbox.md.

## Stage / inspect the folder

- Same "Chap N" name in both series → identify by file prefix `Binh_Thien_Sach_` / `Dao_Si_Quen_`
  (parallax-folder-always-check).
- gdrive FUSE mount `cp -r` runs at ~0.08 MB/s → stage with `rclone copy "gdrive:<path>/X" "$STAGE/X"`
  per subfolder, `--transfers 8` (gdrive-staging-use-rclone-not-cp). Never write/delete on the mount.
- A mount `ls`/local `rclone lsf` can show a folder empty right after upload, or skip a file the box
  finds → re-check before declaring an asset missing (dao-si-chap25).
- Mount upload stalls (file `Dirty:true` in `~/.cache/rclone/vfsMeta`) → the real Drive lacks the
  file; `rclone lsf gdrive:<path>` tells the truth (gdrive-mount-uploader-stall-colab-whisper).
- Thumbnail folder with several images (old tập's `37.jpg` + `38.jpg`, A/B variants) → auto-detect
  leaves `intro_image` unset → set `inputs.intro_image` explicitly to this tập's no-text/numbered
  image (chap30, chap38, chap39, dao-si-chap15).
- Thumbnail missing or a byte copy of an older tập (compare md5) → render without `intro_image` and
  tell the user; never reuse another tập's card (dao-si-chap34, dao-si-chap35).
- ĐẠO SĨ CTA v2 files (`cta-intro-v2.mp4`) do not match auto-detect → set `intro_cta`/`outro_cta`;
  never set `*_cta_image` (a still overrides the animated clip) (dao-si-chap30).
- Bình Thiên CTA: use `… - with voice.mp4`; the plain `Intro CTA.mp4` is silent
  (binh-thien-cta-with-voice-variant).
- Wrong content under a right filename (Chap 33 held chương 311-320) → spot-check chapter numbers in
  prompts/text and look at image 1 (chap-15-program-format-from-chap31).
- Source text jumps (missing scene between chapters) or an image with baked-in text → report to the
  user; do not fix sources yourself (dao-si-chap32, dao-si-chap38).

## Prepare (job.yaml / creative.yaml)

- `init-job` writes `assets.policy: licensed-only` and `captions.mode: srt-only` → rewrite to
  `allow-missing-local` and `mode: "off"` — QUOTED, bare `off` parses as boolean false.
- Every input path must be inside the job folder (overlay, sfx, template) — copy files in.
- Description template must be a job-root `*_DESCRIPTION_TEMPLATE.txt`; the channel-root
  `template/` copy is not found (chap21, chap37, chap41).
- Image timing degrades silently to an even split → read the `Timing:` line / `timing.source`.
  No scene plan in the folder → `even` is expected (BT47-54). A folder that HAS
  `*_scene_anchors.md` or `.work/scene-plan.md` but still gives `even` is a BUG, not a missing
  input — the cloud director hard-stops on it (`_assert_timing_is_not_silently_degraded`); locally,
  stop and report it (watch-image-timing-next-renders).
- One image can legitimately hold 7-10 min where the plan has no scene — no maximum hold by user
  decision; report the number, do not add a cap (dao-si-chap36).
- SFX cues closer than 30s, inside the 30s head / 25s tail, or over the cap are dropped silently
  → simulate `_filter_sfx_cues` (sfx-music.md). Off-by-one on `voice_end`: fix pending;
  until it lands, use the START of the last SRT cue (chap47).
- ĐẠO SĨ SRT chapter numbers are relative → `captions.renumber` (description-metadata.md).
- `mood` without `grain: false` → multi-GB blowup (melancholy-grain-bitrate-blowup).

## Render

- Local: the mp4 is invalid until ffmpeg exits (moov written last, then faststart). Wait for the
  process to exit, then `ffprobe` + `ffmpeg -v error -i out.mp4 -f null -` (chap23-local-render).
- A monitor `until pgrep -f "videotool render"` matches its own command line and never ends → watch a
  PID or `ps -eo pid,args` (dao-si-chap13). `pkill -f <pattern>` can kill your own shell → `pkill -x rclone`
  (chap39).
- A `UnicodeDecodeError` from ffmpeg output with Vietnamese metadata was cosmetic and is fixed
  (2026-07-13); if it recurs, verify the mp4 before re-rendering.
- Kaggle-specific failures: kaggle-runbook.md "Failure triage".

## Verify

- Duration: mp4 = intro CTA + narration + outro CTA (±0.1s). QA does not catch an outro cut
  (chap34, chap35).
- Narration WAV length without downloading: parse the RIFF header (`data` size / byte rate);
  ffprobe on a truncated WAV reports the truncated length (dao-si-chap26).
- mp4 duration without downloading: `rclone cat --head <bytes>` (plain byte count, not "8MB"; no
  `| head -c`, SIGPIPE corrupts it). moov is at the HEAD (faststart). ffprobe may still refuse a
  partial file → parse `mvhd` by hand: timescale at offset type+16, duration at +20 (v0)
  (chap40, chap46, chap51).
- Frames deep in a long mp4 need the full file — a 12 MB head holds only the moov (chap53).
- Burned-subtitle check: sample the MIDDLE of several cues, never a fixed second (can be silence)
  (chap54). Compare title cards by grayscale correlation (64×36), not PSNR (chap53).
- ffmpeg measurements (loudnorm summary, psnr, `metadata=print`) print at info level: run with
  `-nostats`, never `-v error` (chap53, dao-si-chap36).
- `quality-report.json` "could not measure integrated LUFS" on the GPU box is a known false alarm —
  measure locally, expect −13.5..−14 LUFS (chap36).
- SFX presence cannot be heard in astats; confirm the "Mixed SFX onto 1 output(s)" log line (chap36).
- `thumbnail-candidate-0X.jpg` are not published by design (chap46).

## Publish / download

- gdrive can throttle downloads to KB/s → do not depend on a full download for QA; use the early
  job.yaml check, head/moov duration and the box quality report (chap39).
- rclone multi-thread downloads pre-allocate a sparse file: size looks complete early; trust the log.
- A small `rclone cat` while a big download runs can return 0 bytes without error → retry after.
- Local publish goes to `$SRC/Output/` (or the folder name the user gives); Kaggle to `<source>/outputs/`.

## Cleanup

- Delete only your own `render_job*.json`, after checking both kernels' status (chap45, chap51).
- Delete downloaded QA mp4s from scratch; keep creative + config as the record.
- Local staging: delete only `$HOME/.cache/videotool/<name>`, never anything under the mount.

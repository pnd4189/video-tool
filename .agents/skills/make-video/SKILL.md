---
name: make-video
description: "Render an audio-story YouTube episode (Bình Thiên Sách, Đạo Sĩ Sợ Ma, …) from an asset folder, on Kaggle (default) or locally: author the creative layer, stage, render, verify, publish. Use when the user says render / make video / render on Kaggle, or points at a Chap folder."
argument-hint: "<folder path or Drive link> [hints: GPU|TPU|local, overlay/FX, title, shorts]"
---

# make-video

Product = narration + music + thumbnail. Visuals only defeat YouTube's static-frame penalty.
Speed-to-publish beats polish. Project rules and locked decisions: `AGENTS.md` (read it first).

## Inputs

A Chap folder (gdrive path, mount path, or Drive link) containing: voice (`.wav` > `.m4a` > `.mp3`),
`Image/`, optional `Video/` (b-roll — always used), `Parallax/`, `Music/`, the provided
`*_vi_qa.srt` + `*_vi_qa.txt`, `*_music_prompts.txt`, a scene plan (`*_scene_anchors.md` or
`.work/scene-plan.md`), `CTA voice/`, a thumbnail folder, an ending image.
Hints: `GPU` / `TPU` / `local`, FX/overlay wishes, `shorts`/`9x16`/`--all`.

## Stop and ask the user (only these)

1. **New series** (not in `references/series.yaml`): ask channel, channel URL, original author,
   title-list location. Never guess.
2. **FX hint given**: propose ONE overlay (and mood if asked) in one line, wait for "ok" — unless
   the user already named it or said "không cần hỏi". No hint → render clean, propose nothing.
3. **`Parallax/` count ≠ `Image/` count**, or no voice / no SRT / zero images and clips.
4. Runtime unclear and the difference matters (TPU queue vs GPU speed) — one question.
Everything else: decide, act, report at the end.

## Hard safety rules

- Never `rm`/`mv`/overwrite anything on the gdrive mount (`/home/dung/cloud/gdrive/…`) or on Drive
  except: the per-episode files you stage (creative, template, config) and your own
  `render_job*.json` cleanup. Local deletes only under `$HOME/.cache/videotool/<name>`.
- Never `kaggle kernels push`, never edit repo code/workflow files, never `git commit`/`push`, never
  `pip install`. If code looks wrong or stale, stop and tell the user.
- Every rule in the references carries its source; do not relax a limit because it seems arbitrary.

## Step 1 — Inspect (read-only)

- Identify the series from the file prefix and `references/series.yaml`; state series + tập +
  chương range back to the user in your first report.
- List every input above. Check pitfalls.md "Stage / inspect" (thumbnail ambiguity, CTA names,
  wrong content, Parallax count).
- Measure narration length from the SRT's last cue end (and the WAV RIFF header when needed).

## Step 2 — Author the creative layer

Write `creative.yaml` (Kaggle, and locally the same file feeds `videotool prepare`). Local
`job.yaml` has no `captions.renumber`, `render.bitrate_cap`, `enhance.overlay` or `project.chapters`
keys — `videotool prepare --target local --creative creative.yaml` applies them for you. Start from
`examples/creative-binh-thien.yaml` or `examples/creative-dao-si.yaml`.
- `project.title` verbatim from the title list; `project.metadata` from series.yaml;
  `project.description`, `project.recap_previous`, `project.chapters`
  → `references/description-metadata.md`.
- `captions.renumber` when the SRT numbers chapters relatively (ĐẠO SĨ).
- `audio.music_schedule` and `enhance.sfx` → `references/sfx-music.md`.
- `inputs.*` overrides for intro/ending/CTA that auto-detect cannot resolve.
- `enhance.parallax: true` when `Parallax/` is complete; overlay/mood only per the ask-user gate
  → `references/fx-parallax.md`.
- `render.bitrate_cap: 2500k` for long episodes (≥ ~2h), `2200k` for ≥ ~3.5h (kaggle-runbook.md).
- Description template: build `<stem>_DESCRIPTION_TEMPLATE.txt` from the previous episode's
  rendered description.
Keep a working folder `plans/scratch-<slug>/` (slug `binh-thien-chapNN` / `dao-si-chapNN`) with the
creative, template, config and any helper scripts.

## Step 3 — Validate locally

Pin the SFX beats and lint the whole creative against the real source (no media downloaded):

```bash
.venv/bin/videotool creative sfx-pin "<source>" --picks picks.yaml --creative creative.yaml
.venv/bin/videotool creative lint "<source>" --creative creative.yaml --preview description-preview.txt
```

`picks.yaml` = `[{quote, near, file, gain_db?, note?}]` — a short narration quote plus its rough
second; sfx-pin interpolates the exact time inside the SRT cue and rewrites `enhance.sfx.cues`,
printing KEEP/DROP per cue. `lint` replays the box's preparation on a stand-in of the folder: 0
errors required (warnings need a decision). It checks the title against the series list, metadata,
CJK chars, description length/placeholders, SFX pack files and drops, music coverage, parallax
coverage, title cards; the preview is the exact description `package` will render.

## Step 4a — Kaggle render (default)

Follow `references/kaggle-runbook.md` exactly: pick kernel + config file from the runtime, stage
creative → template → config and verify each (md5), tell the user to open the kernel and Save & Run
All, monitor, check the checkpoint job.yaml early, verify the publish, clean up the config.

## Step 4b — Local render (user says "local")

```bash
cd /home/dung/VIBE_CODING/video-tool; VT=.venv/bin/videotool
SRC="<folder on the mount>"; REMOTE="gdrive:<same path under the mount>"
STAGE="$HOME/.cache/videotool/$(basename "$SRC")"; mkdir -p "$STAGE"
rclone copy "$REMOTE" "$STAGE" --transfers 8          # never cp -r through the mount
JOB="$STAGE/job.yaml"
$VT init-job "$STAGE" --voice <voice file> --media media --music Music
# edit job.yaml: assets.policy: allow-missing-local; captions.mode: "off" (quoted);
# enhance: {visualizer: true, subtitles: true, subtitle_color: yellow}; inputs.intro_image /
# ending_image / intro_cta / outro_cta / script / description_template; project.*; audio.*;
# enhance.sfx (copy cue files into $STAGE/sfx/, reference sfx/<file>); overlay: copy the file into
# $STAGE, set inputs.particle_overlay + enhance.atmosphere: true; long episode: render.encoder:
# libx264-balanced-capped-2500k (or -2200k) instead of bitrate_cap.
mkdir -p "$STAGE/outputs" && cp "$STAGE"/*_vi_qa.srt "$STAGE/outputs/captions.srt"
# ĐẠO SĨ relative numbering: fix the "Chương N:" headings in outputs/captions.srt now.
$VT storyboard auto "$JOB" --images-dir "$STAGE/Image" --videos-dir "$STAGE/Video"   # read "Timing:"
[ -d "$STAGE/Parallax" ] && $VT parallax-link "$JOB" --clips-dir Parallax
$VT chapters-from-srt "$JOB"
# package prefers outputs/chapters.json over project.chapters: write your chapter list
# ([{start, title}], narration seconds) into outputs/chapters.json.
$VT validate "$JOB" && $VT render "$JOB" --preset youtube-16x9
$VT sfx "$JOB" && $VT package "$JOB" && $VT metadata "$JOB"
rclone copy "$STAGE/outputs" "$REMOTE/Output"
```
Run the render in the background and watch the PID, not the file. After a verified publish, delete
`$STAGE` only. Shorts only on request: add `{preset: shorts-9x16}` to `outputs:` and `render --all`.

## Step 5 — Verify and report

Check (pitfalls.md "Verify"): mp4 named after the title; duration = intro CTA + narration + outro
CTA; h264 1920×1080 + aac; `quality-report.json` 11/11 (LUFS ≈ −13.5..−14); `Timing:` tier; SFX and
music cue counts; intro/ending cards present; `captions.youtube.srt` first cue = CTA length.
Report to the user, outcome first: output path, mp4 name + size + duration, QA result, timing tier,
overlay/SFX/music summary, anything skipped (no thumbnail, long image holds, source defects), and
remind them to upload `captions.youtube.srt` and paste `description.txt`.

## Lessons

New lesson (a trap, a fix, a number that changes a rule)? Do not edit these references and do not
write to your CLI's private memory.
- agy / codex (render-only): run `videotool agent lesson` if it exists; otherwise append an entry to
  `references/lessons-inbox.md` and tell the user in the session. Claude verifies and promotes it
  later, when the user asks.
- Claude: verify first, then edit the owning reference with a source, when the user asks.

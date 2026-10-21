---
name: make-video
description: "Render an audio-story YouTube episode (Bình Thiên Sách, Đạo Sĩ Sợ Ma, …) from an asset folder, on a Colab high-RAM CPU VM through the Colab CLI (default, no browser), Modal (backup) or locally: author the creative layer, stage, render, verify, publish. Use when the user says render / make video / render on Colab / render on Modal, or points at a Chap folder."
argument-hint: "<folder path or Drive link> [hints: Modal|local, overlay/FX, title, shorts]"
---

# make-video

Product = narration + music + thumbnail. Visuals only defeat YouTube's static-frame penalty.
Speed-to-publish beats polish. Project rules and locked decisions: `AGENTS.md` (read it first).

## Inputs

A Chap folder (gdrive path, mount path, or Drive link) containing: voice (`.wav` > `.m4a` > `.mp3`),
`Image/`, optional `Video/` (b-roll — always used), optional `Parallax/`, `Music/`, the provided
`*_vi_qa.srt` + `*_vi_qa.txt`, `*_music_prompts.txt`, a scene plan (`*_scene_anchors.md` or
`.work/scene-plan.md`), `CTA voice/`, a thumbnail folder, an ending image.
Hints: `Modal` / `VPS` / `local`, FX/overlay wishes, `shorts`/`9x16`/`--all`.

## Stop and ask the user (only these)

1. **New series** (not in `references/series.yaml`): ask channel, channel URL, original author,
   title-list location. Never guess.
2. **FX hint given**: propose ONE overlay (and mood if asked) in one line, wait for "ok" — unless
   the user already named it or said "không cần hỏi". No hint → render clean, propose nothing.
3. **`Parallax/` partly filled** (fewer clips than `Image/`, or clips matching no image — lint warns),
   or no voice / no SRT / zero images and clips. No `Parallax/` at all is not a question: Ken Burns.
4. Narration over the Colab lane's cap (3.5 h): Modal or local — one question.
Everything else: decide, act, report at the end.

## Hard safety rules

- Never `rm`/`mv`/overwrite anything on the gdrive mount (`/home/dung/cloud/gdrive/…`) or on Drive
  except: the per-episode files you stage (creative, template, config) and your own
  `render_job*.json` cleanup. Local deletes only under `$HOME/.cache/videotool/<name>`.
- Never run `kaggle kernels push` yourself (the one pusher is the CPU-lane script of Step 4d, and only
  for its own private `videotool-cpu-*` kernels), never edit repo code/workflow files, never
  `git commit`/`push`, never `pip install`. If code looks wrong or stale, stop and tell the user.
- A blocked `cloud stage` is FINAL: report the ERROR/BLOCK lines and stop. Never stage by hand — no
  self-written `render_job.json`, no direct `rclone` of the config/creative to `_VIDEOTOOL_SHARED`
  (that skips lint, the guards and the watcher; CHAP 3 failed on Kaggle twice exactly that way).
  Tell the user to click Run only after `videotool renders` shows the slug as `staged`.
- Modal spends a prepaid credit: run it only when the user named Modal in this request, do the budget
  checklist and have the user confirm the limits once per session (`references/modal-runbook.md`).
  agy's guard does not block `modal`; the discipline is yours.
- Colab spends the account's monthly compute units, shared with the user's other projects: VMs only
  through `scripts/colab_render.py` — never `colab new`/`run`/`ssh` by hand, never `--gpu`/`--tpu`, never
  `colab pay`. The script stops its VM after the download and after a box failure; after any other
  `FAILED:` look at `colab --config ~/.config/colab-cli/videotool-sessions.json sessions` and report a VM
  still listed (`references/colab-runbook.md`). agy's guard does not block `colab` either.
- In agy a `PreToolUse` guard enforces that list (`videotool agent guard`). A block is final: read
  the reason, stop, and tell the user — do not look for another way round it. Your own working
  folder is `plans/scratch-<slug>/`; the staged copy under `$HOME/.cache/videotool/<name>` and
  `/tmp` are yours too.
- Learned something the references do not say? `videotool agent lesson "<what happened / evidence /
  suggested rule>" --episode <slug>` — it goes to `references/lessons-inbox.md` and messages the
  user; say it in the session too. Never edit a reference yourself.
- Every rule in the references carries its source; do not relax a limit because it seems arbitrary.

## Step 1 — Inspect (read-only)

- Identify the series from the file prefix and `references/series.yaml`; state series + tập +
  chương range back to the user in your first report.
- List every input above. Check pitfalls.md "Stage / inspect" (thumbnail ambiguity, CTA names,
  wrong content, Parallax count).
- Measure narration length from the SRT's last cue end (and the WAV RIFF header when needed).

## Step 2 — Author the creative layer

Write `creative.yaml` (every lane: `videotool prepare` builds the job from it). Local
`job.yaml` has no `captions.renumber`, `render.bitrate_cap`, `enhance.overlay` or `project.chapters`
keys — `videotool prepare --target local --creative creative.yaml` applies them for you. Start from
`examples/creative-binh-thien.yaml` or `examples/creative-dao-si.yaml`.
- `project.title` verbatim from the title list; `project.metadata` from series.yaml;
  `project.description`, `project.recap_previous`, `project.chapters`
  → `references/description-metadata.md`.
- `captions.renumber` when the SRT numbers chapters relatively (ĐẠO SĨ).
- `audio.music_schedule` and `enhance.sfx` → `references/sfx-music.md`.
- `inputs.*` overrides for intro/ending/CTA that auto-detect cannot resolve — paths **inside the
  episode folder** (`Ảnh bìa Thumbnail-Intro/22.jpg`, the template's bare file name). An absolute
  path exists on this machine only; the box stops on it (ĐS22).
- Only keys the pipeline reads: lint rejects anything else (`enhance.atmosphere` did nothing — the
  overlay key is `enhance.overlay: <file from ~/.local/share/videotool/overlays/>`).
- No parallax key: `Parallax/` clips link on their own, stills without a clip render as Ken Burns.
  `enhance.parallax` + `parallax_on_box` only when the user asked for on-box depth. Overlay/mood only
  per the ask-user gate → `references/fx-parallax.md`.
- `render.bitrate_cap: 2500k` for long episodes (≥ ~2h), `2200k` for ≥ ~3.5h (kaggle-runbook.md).
- Description template: build `<stem>_DESCRIPTION_TEMPLATE.txt` from the previous episode's
  rendered description.
Keep a working folder `plans/scratch-<slug>/` (slug `binh-thien-chapNN` / `dao-si-chapNN`) with the
creative, template, config and any helper scripts.

## Step 3 — Validate locally

Pin the SFX beats and lint the whole creative against the real source (no media downloaded):

```bash
.venv/bin/videotool creative sfx-pin "<source>" --picks picks.yaml --creative creative.yaml
.venv/bin/videotool creative lint "<source>" --creative creative.yaml --preview description-preview.txt \
    [--template <the template you will stage>]
```

These commands take 1–5 minutes. In agy give `run_command` a large `WaitMsBeforeAsync` (600000) for
them; if one still goes to the background, wait until its task is DONE and read the log before the
next step. Never start the next step on, and never quote, a result you have not read — and never
write creative.yaml after sfx-pin (it holds the pinned cues).

`picks.yaml` = `[{quote, near, file, gain_db?, note?}]` — a short narration quote plus its rough
second; sfx-pin interpolates the exact time inside the SRT cue and rewrites `enhance.sfx.cues`,
printing KEEP/DROP per cue. `lint` replays the box's preparation on a stand-in of the folder: 0
errors required (warnings need a decision). It checks the title against the series list, metadata,
CJK chars, description length/placeholders, SFX pack files and drops, music coverage, parallax
coverage, title cards, `Image/` names (no SCENE number, a number used twice, a missing scene) and an
empty voice file; the preview is the exact description `package` will render.

## Step 4a — Colab render (default)

Colab CLI, high-RAM CPU VM, no browser tab (user 2026-10-20; the Kaggle account is banned). Like Modal,
Colab only renders: the episode is staged, prepared and finished on this machine and no Drive key goes
to the VM. A keeper cell keeps the kernel busy, its exec attached from here; with nothing connected Colab
took the VM about 3 h after the last contact, also about 3 h after it started (runbook, measured 2026-10-20;
which clock counts is not known), so keep this machine on and the driver running until the run ends (it
also downloads, finishes and publishes here). Narration ≤ 3.5 h. agy
may run it. Read `references/colab-runbook.md` first (stage + prepare as its Flow says), dry run, then:

```bash
.venv/bin/python .agents/skills/make-video/scripts/colab_render.py run "$STAGE" --remote "gdrive:…/Chap NN"
```

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
Run the render in the background and watch the PID, not the file. After the publish, free the machine
(unasked, user 2026-10-15; it re-checks every published size first):
`.venv/bin/python .agents/skills/make-video/scripts/purge_stage.py "$STAGE" --published-to "$REMOTE/Output"`.
Shorts only on request: add `{preset: shorts-9x16}` to `outputs:` and `render --all`.

## Step 4c — Modal render (backup runtime, user says "Modal")

Colab CLI is #1 (Step 4a), Modal #2. Modal only renders: the job is prepared and finished locally, no Drive
credentials go to Modal. Everything (budget checklist, commands, expected signals, cleanup) is in
`references/modal-runbook.md` — read it before the first command. Shape:

```bash
videotool prepare "$STAGE" --target cloud --creative "$STAGE/creative.yaml"   # after rclone copy + lint
VT_JOB_DIR="$STAGE" VT_SLUG=<slug> modal run .agents/skills/make-video/scripts/modal_render.py
modal volume get vt-<slug> / "$STAGE-dl" --force   # then modal volume delete vt-<slug> --yes
videotool sfx "$STAGE/job.yaml" && videotool package "$STAGE/job.yaml" && videotool metadata "$STAGE/job.yaml"
```

## Step 4e — VPS render (only when the user says "VPS")

The Oracle VPS over ssh (`ssh oracle-vps`, 2 ARM cores): the same box as Colab, prepared and finished here, no
Drive key on the VPS, no narration cap, one job at a time (user 2026-10-21). Read `references/vps-runbook.md`
first (setup without sudo, speed, signals), stage + prepare as Step 4a, dry run, then:

```bash
.venv/bin/python .agents/skills/make-video/scripts/vps_render.py run "$STAGE" --remote "gdrive:…/Chap NN"
```

## Step 4d — Kaggle lanes (dormant: the Kaggle account is banned, user 2026-10-20)

Only if the user says the account is back. GPU/TPU notebook: `videotool cloud stage … --runtime gpu|tpu`
and the user's Save & Run All, all in `references/kaggle-runbook.md`. Headless CPU kernel:
`scripts/kaggle_cpu_render.py`, `references/kaggle-cpu-runbook.md` (the Colab lane runs its box script).

## Step 5 — Verify and report

Check (pitfalls.md "Verify"): mp4 named after the title; duration = intro CTA + narration + outro
CTA; h264 1920×1080 + aac; `quality-report.json` 11/11 (LUFS ≈ −13.5..−14); `Timing:` tier; SFX and
music cue counts; intro/ending cards present; `captions.youtube.srt` first cue = CTA length.
With the job folder on this machine, `videotool review <job.yaml>` (~1 min for 3 h): open
`.videotool/review/contact-sheet.png` (after a purge: `$STAGE-review/`) and report its loudness line
and every `WARN`.
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

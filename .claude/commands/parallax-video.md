---
name: parallax-video
description: "Build an audio-story YouTube video with 2.5D parallax stills, ingesting pre-rendered DepthFlow clips from a Parallax/ folder. Same pipeline as /make-video plus a parallax-link step. Use when the user wants the 2.5D 'living photo' look and has Colab-rendered clips ready."
argument-hint: "<folder> [optional hints: title, music file, presets, language]"
---

Read `./AGENTS.md` first — workflow, pitfalls, confirmed decisions. This command is `/make-video`
PLUS one inserted step (`parallax-link`); everything else is identical. Treat "Confirmed project
decisions" as locked.

The 2.5D motion clips are produced OFF this machine (Colab + DepthFlow — see `Colab/v4_depthflow_clips_colab.py`),
one loopable clip per still, named `<image-stem>.mp4`. The user downloads them and uploads them into
`<folder>/Parallax/` manually. This command does NOT generate clips locally — it only ingests them.

Execute against the user's input:

$ARGUMENTS

## Execution rules

0. If the folder is on a gdrive mount (`/home/dung/cloud/gdrive/...`), STAGE it locally first per
   AGENTS.md "When assets live on gdrive", but use `rclone copy "<gdrive folder>" "$STAGE"` (the FUSE
   mount is ~60× slower via `cp -r`). **Include the `Parallax/` subfolder so the clips travel with the
   assets.** Run the pipeline in the stage, copy `outputs/` back to `<gdrive folder>/Output/` with
   `rclone copy`, then `rm -rf` the LOCAL staging ONLY. Never delete on the mount.
1. Inspect the asset folder exactly like `/make-video`: voice file, images, optional video clips, the
   music FOLDER, intro thumbnail / ending image, `*_vi.txt`, `_DESCRIPTION_TEMPLATE.txt`, `CTA voice/`.
   Also detect `<folder>/Parallax/` (the parallax clips). Use absolute paths.
2. Run `init-job` (point `--music` at the music folder), then patch `job.yaml` identically to
   `/make-video`: `assets.policy: allow-missing-local`, `captions.mode: off`, intro/ending images,
   channel default `enhance: {visualizer: true, subtitles: true, progress_bar: false}`,
   `inputs.script` / `inputs.description_template`, CTA inputs, `project.title` (the episode's
   line from the series title list) + `project.metadata` (channel/URL/original author, from memory
   `series-channel-ownership`; ask the user at tập 1 of a NEW series), `project.recap_previous` /
   `project.description`. (Do NOT set `enhance.parallax` — that is the separate local-numpy path; here
   the motion comes from the ingested clips, not from the render.)
3. Run `storyboard auto "$JOB" --images-dir "$FOLDER/Image"` (add `--videos-dir "$FOLDER/Video"` when a
   Video folder exists — Pitfall #2). This writes the scene list with per-scene durations.
4. **Ingest parallax clips:** run `videotool parallax-link "$JOB" --clips-dir Parallax`. It swaps each
   image scene for a matching `Parallax/<stem>.mp4` clip (motion=static; render loop+trims it to the
   scene duration) and leaves scenes with no matching clip as Ken Burns stills. If `Parallax/` is
   missing or empty, the command swaps nothing — WARN "no parallax clips found — rendering stills as
   Ken Burns" and continue. Never block. Note the swapped/missing counts from its summary line.
5. Because subtitles are on, ensure captions: if `outputs/captions.srt` is missing, run
   `transcribe "$JOB" --model "$HOME/.cache/videotool/models/faster-whisper-base"` first (model PATH,
   not bare `base`; can take minutes on long audio; emits `chapters.json`). Run it automatically.
6. `validate` → `render --preset youtube-16x9` → `package` → `metadata` (last step: tags the mp4 with title/tags/genre/channel credits and renames it to the episode title — needs `project.title` set, see step 2) (per-feature `enhance` flags drive
   overlays — do NOT pass `--enhance full`). Render Shorts only if the hint asks.
7. Report: mp4 path(s) (named after the episode title, not `youtube-16x9.mp4`), thumbnail, `description.txt`, chapter count, AND **how many scenes used a
   parallax clip vs fell back to Ken Burns** (from the `parallax-link` summary). Quote the `ffprobe`
   codec/resolution check. If staged from gdrive, report the `Output/` path + space reclaimed.

## When to pause

Only ask ONE concise question, and only if essential: no voice file detectable; ambiguous
voice/music candidates; or zero images AND zero clips. `Parallax/` absent is NOT a blocker — warn and
render stills.

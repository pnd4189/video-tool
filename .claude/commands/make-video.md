---
name: make-video
description: "Build an audio-story YouTube video end-to-end from an asset folder. Reads AGENTS.md for workflow + pitfalls + confirmed decisions. Use when user says 'render video', 'make video', or points at a job folder."
argument-hint: "<folder> [optional hints: title, music file, presets, language]"
---

Read `./AGENTS.md` first — it contains the workflow, pitfalls, and confirmed decisions for this project. Treat its "Confirmed project decisions" as locked unless the user explicitly asks to change one.

Then execute the standard 4-step pipeline against the user's input:

$ARGUMENTS

## Execution rules

0. If the folder is on a gdrive mount (`/home/dung/cloud/gdrive/...`), STAGE it locally first per AGENTS.md "When assets live on gdrive": `cp -r` to `~/.cache/videotool/<name>` (cp -r, not -a — the mount can't preserve perms), run the pipeline there, copy `outputs/` back to `<gdrive folder>/Output/`, then `rm -rf` the local staging ONLY. Never delete on the mount.
1. Inspect the asset folder. Identify the voice file, image files, optional video clips (.mp4/.mov), the music FOLDER, any intro thumbnail / ending image (AGENTS.md "Auto-detecting intro / ending images"), a `*_vi.txt` story script, a `_DESCRIPTION_TEMPLATE.txt`, and a `CTA voice/` folder (`Intro CTA.*` / `Outro CTA.*`). Use absolute paths.
2. Run `init-job` (point `--music` at the music folder), then patch `job.yaml`:
   - `assets.policy: allow-missing-local`, `captions.mode: off`, `inputs.intro_image` / `inputs.ending_image` when detected (Pitfalls #1, #3).
   - **Channel default = full overlays minus progress bar**: `enhance: {visualizer: true, subtitles: true, progress_bar: false}`.
   - When a `*_vi.txt` exists, set `inputs.script` to it. When a `_DESCRIPTION_TEMPLATE.txt` exists, set `inputs.description_template` to it (it must contain the `{{CHAPTERS}}`/`{{RECAP_PREV}}`/`{{SUMMARY}}` placeholders — add them once if missing).
   - **CTA**: when `CTA voice/` exists, set `inputs.intro_cta` / `inputs.outro_cta` to the clips and `inputs.intro_cta_image` (the thumbnail) / `inputs.outro_cta_image` (the ending image) for the title cards. The tool splices them at the very start/end, holds the card image, and auto-shifts captions + chapters (a 00:00 "Giới thiệu" chapter is added).
   - Author `project.recap_previous` (3-5 lines summarizing the PREVIOUS tập's vi.txt) and `project.description` (3-5 lines summarizing THIS tập's vi.txt) so viewers can catch up. Keep them spoiler-light.
   - Set `project.title` to the episode's line from the series title list, and author `project.metadata` (channel / channel_url / original_author / copyright / subtitle) from memory `series-channel-ownership` — the final `metadata` step names the mp4 after the title and writes the publisher credits into it. A series NOT in that memory: ask the user which channel + URL owns it before rendering, then add it there.
3. Run `storyboard auto` for images (it reads intro/ending from `job.yaml` and frames them). If the folder also contains video clips, append them manually to the storyboard list (autogen skips videos — Pitfall #2).
4. Because subtitles are on, captions are required: if `outputs/captions.srt` is missing, run `transcribe "$JOB" --model "$HOME/.cache/videotool/models/faster-whisper-base"` FIRST (it aligns to `inputs.script`, emits `outputs/chapters.json`, and offsets both for any intro CTA). `--model` needs the model PATH, not the bare name `base`. Warn the user this whisper pass can take several minutes on long audio; run it automatically (don't block).
5. `validate` → `render --preset youtube-16x9` → `package` → `metadata` (last step: tags the mp4 with title/tags/genre/channel credits and renames it to the episode title — needs `project.title` set, see step 2) (per-feature `enhance` flags drive overlays — do NOT pass `--enhance full`, it would also switch on particles). `package` renders `outputs/description.txt` from the template with chapter timestamps (from `chapters.json`) + recap + summary. Render Shorts ONLY if the hint asks (shorts/9x16/all): add `{preset: shorts-9x16}` to `outputs` then `render --all`.
6. Report the output mp4 paths (the final name is the episode title, not `youtube-16x9.mp4`), thumbnail path, `description.txt` path, chapter count, and a one-line summary (durations, scene count, preset list, whether intro/ending applied). Remind the user to paste `description.txt` into the YouTube description so chapters render natively. If staged from gdrive, report the `Output/` path + local space reclaimed. Quote any `ffprobe` codec check.

## When to pause

Only ask the user ONE concise question, and only if essential:
- No voice file detectable in the folder
- Multiple candidate voice/music files and the hint doesn't disambiguate
- Folder has zero images AND zero video clips (nothing to render)

Otherwise run silently end-to-end and report at the end.

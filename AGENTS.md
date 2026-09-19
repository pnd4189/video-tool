# Video Tool — Agent Guide

Core rules for every agent (Claude Code, Antigravity `agy`, Codex). `CLAUDE.md` and `GEMINI.md` are
symlinks to this file. The render workflow itself lives in the shared skill
`.agents/skills/make-video/` — read its `SKILL.md` before any render.

## Project intent

Audio-first YouTube videos (kể truyện / audiobook). The product is **audio + background music +
thumbnail**. Visuals exist only to defeat YouTube's static-frame penalty. Speed-to-publish wins.

## Entry points

- Render an episode (Kaggle or local): `.agents/skills/make-video/SKILL.md`
  (Claude: `/make-video <folder> [hints]`; agy/codex: the `make-video` skill).
- Local render with pre-rendered parallax clips: `.agents/skills/parallax-video/SKILL.md`.
- References (load only when the step needs them): `.agents/skills/make-video/references/`
  — `kaggle-runbook.md`, `sfx-music.md`, `description-metadata.md`, `fx-parallax.md`,
  `pitfalls.md`, `series.yaml`, `lessons-inbox.md`.
- Cloud architecture and setup: `docs/cloud-render-setup.md`, `docs/cloud-gpu-whisper-setup.md`.

## Asset folder convention (short)

Voice `.wav` > `.m4a` > `.mp3` (never fail when `.wav` is absent) · `Image/` · `Video/` b-roll ·
`Parallax/` DepthFlow clips · `Music/` (natural-sorted, `01-`, `02-` prefixes order it) ·
`*_vi_qa.srt` + `*_vi_qa.txt` (provided subtitles + script) · `*_music_prompts.txt` · scene plan
(`*_scene_anchors.md` or `.work/scene-plan.md`) · `CTA voice/` · thumbnail folder (`thumb*`) ·
ending image (`*end*` / "Ảnh end"). No `assets/asset-index.yaml` — policy is `allow-missing-local`.
Ambiguous intro/ending candidates → skip that image, render, report the skip.

## gdrive safety (non-negotiable)

The rclone mount (`/home/dung/cloud/gdrive/...`) and Drive itself are source material. Never
`rm`/`mv`/overwrite anything there. Stage with `rclone copy` into `$HOME/.cache/videotool/<name>`,
publish back with `rclone copy`, delete only the local stage. The only Drive writes a render makes
are the per-episode creative/template/config files and the cleanup of its own `render_job*.json`.

## Agent roles and lessons

- **Render-only agents (agy, codex)** run renders. They must not edit code, tests, notebooks, the
  skill, references, `AGENTS.md` or configs; must not run git commands that change state,
  `pip install`, or `kaggle kernels push`. When something in code looks wrong, stop and tell the user.
- **New lessons go into the repo, never into a CLI's private memory.** Render-only agents append to
  `references/lessons-inbox.md` (or run `videotool agent lesson` once it exists) and tell the user.
  Claude verifies an inbox entry against code/logs before moving it into a reference, when the user
  asks. Every rule in a reference names its source (memory slug, episode log, or commit).

## Confirmed project decisions (do NOT silently reverse)

Detail and mechanics live in the linked reference. Ask the user before changing any of these.

- **Tier light: no waveform, no self-made subtitles** for generic light jobs; zoompan defeats static
  detection without a re-encode. *(2026-05-28; tier-scoped 2026-05-31.)*
- **Audio-story channels override that: showwaves + burned subtitles ON, progress bar OFF, music bed
  −30 dB.** *(2026-05-31.)*
- **Subtitles and chapters come from the user-provided SRT**, copied to `outputs/captions.srt`;
  `chapters-from-srt` derives chapters. Whisper `transcribe` only when no SRT exists.
  *(2026-07-03.)* → description-metadata.md
- **Mood / atmosphere FX are OFF by default and never proposed**; only on an explicit FX hint, and the
  overlay choice waits for the user's confirmation. *(2026-07-03; overlay gate 2026-06-21.)* → fx-parallax.md
- **WAV-first voice** (`.wav` > `.m4a` > `.mp3`). *(2026-07-03.)*
- **Yellow subtitles (`enhance.subtitle_color: yellow`) for audio-story only**; default white keeps other
  jobs byte-identical. *(2026-07-03.)*
- **Audio AAC 256k, loudnorm −14 LUFS.** *(2026-07-03.)*
- **Music schedule + default SFX**: `audio.music_schedule` places a track per story-mood span (unset →
  concat + loop); `enhance.sfx` mixes one-shot SFX after render (`videotool sfx`, `-c:v copy`, not
  ducked, `amix normalize=0` + limiter), default ON, auto-burn, no montage. Beds deferred.
  *(2026-07-03.)* → sfx-music.md
- **Tier full opts into overlays** (`--enhance full`: burn captions + bundled particles/progress/
  waveform, one re-encode). Audio-story jobs use per-feature `enhance`, not `--enhance full`.
- **Motion amplitude 0.30, pan zoom 1.22** (`render/video_filters.py`). Don't lower without asking.
  *(2026-05-28.)*
- **No auto Shorts.** Only `youtube-16x9` unless the user asks. *(2026-05-29.)*
- **Every published mp4 carries publisher metadata and is named after the episode title**
  (`videotool metadata`, last step). The filename matters (YouTube prefills the title); in-file tags
  are a cheap bet, not a ranking lever. A series' channel/URL/author/credit is fixed from tập 1 —
  ask for a new series. From BT Chap 41 / ĐS Chap 30; published episodes untouched. *(2026-08-24.)*
  → description-metadata.md, series.yaml
- **ĐẠO SĨ title `|` is written as ` - `** in `project.title`. *(2026-08-24.)*
- **No Chinese characters** in descriptions or mp4 tags — Vietnamese names only. *(2026-08-25.)*
- **No CapCut / external editor**; FFmpeg only.
- **Caption mode default `off`** (not `srt-only`); `enhance.subtitles` forces the burn anyway.
- **Intro and ending images overlay the narration** (first 10s / last 10s, no added time) so the
  outro CTA stays in sync. *(2026-06-13.)*
- **Images are timed to the narration per image** (tiers anchor → chapter → even, fail-soft), no
  maximum hold; injecting `=== CHƯƠNG N ===` into prompt files was rejected on evidence. Not a
  retention lever — the frame is right where the listener looks. *(2026-09-07.)* → pitfalls.md
- **B-roll clips interleave with images by story order** (`storyboard auto --videos-dir`), keep their
  real duration, never dropped. *(2026-06-13.)*
- **2.5D parallax, local numpy path = opt-in `enhance.parallax: true`** (independent of tier;
  DepthAnything V2-Small, CPU torch build, `local_files_only`; DepthFlow rejected locally — pyaudio
  needs sudo). *(2026-06-15.)* → fx-parallax.md
- **Pre-rendered DepthFlow clips = `/parallax-video` + `parallax-link`**, separate from
  `enhance.parallax`; a still without a clip stays Ken Burns. *(2026-06-18.)*
- **Progress bar removed from every job** (`enhance.progress_bar` validates but renders nothing).
  *(2026-06-15.)*
- **Group-A mood FX** (`enhance.mood` clean/melancholy/cozy/horror/action → vignette/grain/glow/
  flicker/grade) are independent of tier; per-effect fields override the mood. *(2026-06-15.)*
- **Atmosphere overlay = one clip from the local CC0/generated library**
  `~/.local/share/videotool/overlays/`, screen-blended in `gbrp` (never yuv420p — magenta tint).
  Masters stay on gdrive `KHÁC/HIỆU ỨNG VIDEO/`. *(2026-06-18; durable dir 2026-06-21.)* → fx-parallax.md
- **Full cloud render on Kaggle** (`Colab/cloud_render_runner.py`): the agent authors `creative.yaml`
  locally, the box runs no LLM (the on-box LLM is only an `autonomous=True` fallback), NVENC or
  x264 with resumable Drive checkpoints, results publish to the source folder. Kaggle primary,
  Colab fallback. *(2026-07-11.)* → kaggle-runbook.md
- **Local and cloud job preparation merge into one package step** (`videotool.creative`, driven by
  `videotool prepare` / `Colab/cloud_director.py`; `videotool creative lint` + `sfx-pin` check the
  same rules before staging). Reverses the 2026-07-11 "local flow byte-unchanged, cloud is a
  parallel system": the cloud copy silently lost the intro/ending cards from ĐS25 to ĐS38 while
  local was right. *(2026-09-19.)*
- **agy renders with the NEWEST Gemini Pro model at effort High** — checked via `agy models` at
  each run; today that is `gemini-3.1-pro-high` (shadow test BT54: Pro đạt 5/5 tiêu chí, Flash loại
  — copy + dở việc; Opus chỉ dự phòng vì chạy bằng quota Anthropic). *(2026-09-19.)*
- **One knowledge source in the repo** (this file + `.agents/skills/`); per-CLI memories only point
  here. Render-only agents work under the guard above. *(2026-09-19.)*

## Verification commands

- `.venv/bin/python -m pytest -q` — full suite (283+ must pass)
- `.venv/bin/videotool doctor` — ffmpeg + environment check
- `ffprobe -v error -show_entries stream=codec_name,width,height -of csv=p=0 <out.mp4>` — h264 + aac + 1920×1080

## Tech notes

- Python 3.12 venv at `.venv/`; call binaries by path (`.venv/bin/videotool`). FFmpeg is required;
  default encoder `libx264-balanced` (`*-capped` / `*-capped-2500k` variants cap the bitrate).
- `faster-whisper` (`ai` extra) is installed; offline `base` model at
  `~/.cache/videotool/models/faster-whisper-base` (pass the PATH to `--model`). Cloud GPU whisper:
  `transcribe --device cuda --compute-type float16 --model large-v3`.
- Render branches at 40 scenes (`render.max_inline_scenes`): above it the segmented path renders
  scene clips in parallel (one per core, cap 8, `VIDEOTOOL_SCENE_WORKERS`) and bakes the overlay per scene.
- Every subprocess capture uses `errors="replace"` — Vietnamese bytes cannot crash a run (2026-07-13).
- The Google CLI is Antigravity (`agy`); Gemini CLI is discontinued. Headless `agy -p` runs in an
  empty default project and loads NO workspace skills — pass `--project /home/dung/VIBE_CODING/video-tool`
  (verified 2026-09-19 with `agy -p "/skills"`).
- Key files: `src/videotool/core/{job_spec,storyboard,services}.py`, `render/{video_filters,segmented,
  executor,sfx_mix}.py`, `cli/main.py`; cloud: `Colab/{cloud_director,cloud_render_runner,videotool_cloud}.py`
  and the notebooks `Colab/videotool-render{,-tpu}.ipynb`.

## When to update this file

- A user decision changes → update its line here (with the date) and the owning reference.
- CLI command names/arguments change → update `make-video/SKILL.md`.
- Keep this file ≤150 lines; detail belongs in the skill references or `docs/`.

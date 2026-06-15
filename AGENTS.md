# Video Tool — Agent Guide

Canonical workflow doc. Read this every session before acting. Symlinked from `CLAUDE.md` and `GEMINI.md` so Claude Code, Antigravity (Agy), and Codex CLI all see the same source.

## Project Intent

Audio-first YouTube videos (kể truyện / audiobook). The product is the **audio + background music + thumbnail**. Video visuals exist only to defeat YouTube's static-frame penalty — quality is not a goal. Speed-to-publish wins over polish.

## When the user invokes `/make-video <folder> [hints]`

Run the 4-step CLI pipeline below, end-to-end, until an mp4 + package is on disk. Report paths at the end. Don't ask permission step-by-step — only ask if something in the folder is ambiguous.

## Asset folder convention

User points at a folder containing:

- `voice.wav` / `voice.mp3` / `voice.m4a` — the narration (required)
- `media/` — images (`.png .jpg .jpeg .webp`) and optional video clips (`.mp4 .mov`)
- `music/` — optional background music. Point `inputs.music` at the **folder**: all tracks
  inside play back-to-back (natural-sorted by name — prefix `01-`, `02-` to order them) then
  loop to the end of the video.
- An **intro thumbnail** (no-text template) and an **ending image** may sit anywhere in the
  folder (often a subfolder like `Ảnh end video/`). Detect them and set `inputs.intro_image` /
  `inputs.ending_image`. Intro overlays the FIRST 10s of the narration and the ending overlays
  the LAST 10s (both no added time) — so the ending card stays flush with the voice end and a
  spliced outro CTA card lines up with the CTA voice instead of lagging 10s behind.
- **No** `assets/asset-index.yaml` required — we use `allow-missing-local`

### Auto-detecting intro / ending images
Scan the folder (incl. subfolders): a filename/subfolder matching `thumb*` → intro template;
matching `*end*` / `outro` / "ảnh end" → ending image. If absent or genuinely ambiguous
(several equally-likely candidates), SKIP that image, render normally, and note the skip in the
final report. Never block on it.

## When assets live on gdrive (rclone mount)

If the folder path is on a gdrive mount (e.g. under `/home/dung/cloud/gdrive/...`), stage it
locally first — the mount is slow and must never be written to destructively:

```bash
SRC="<gdrive folder>"                 # the user-supplied mount path
STAGE="$HOME/.cache/videotool/$(basename "$SRC")"
rm -rf "$STAGE"; mkdir -p "$STAGE"
cp -r "$SRC"/. "$STAGE"/             # assets -> fast local disk (cp -r: mount can't preserve perms)
# ... run the standard pipeline with JOB_DIR="$STAGE" ...
mkdir -p "$SRC/Output"               # sibling of the asset subfolders
cp -r "$STAGE/outputs"/. "$SRC/Output"/   # publish results back to gdrive
rm -rf "$STAGE"                      # delete LOCAL staging ONLY
```

SAFETY (non-negotiable): the only delete is `rm -rf "$STAGE"` on the local cache path. NEVER run
`rm`/`mv`/overwrite against `$SRC` or anything under the mount. Report the `$SRC/Output/` path +
local space reclaimed.

## Standard pipeline (run all 4 steps)

All commands use the project venv at `/home/dung/VIBE_CODING/video-tool/.venv/`.

```bash
cd /home/dung/VIBE_CODING/video-tool
VT=.venv/bin/videotool
JOB_DIR="<user-supplied folder>"
JOB="$JOB_DIR/job.yaml"

# 1. Init job.yaml skeleton. Point --music at the music FOLDER (all tracks concat+loop).
$VT init-job "$JOB_DIR" --voice voice.wav --media media --music music
# Then add intro/ending if detected (edit job.yaml inputs):
#   inputs.intro_image: <path to no-text thumbnail>
#   inputs.ending_image: <path to ending image>

# 2. Force allow-missing-local + caption off (init-job defaults are wrong for our flow)
sed -i \
  -e 's/policy: licensed-only/policy: allow-missing-local/' \
  -e "/captions:/,/^[^ ]/ s/mode: srt-only/mode: off/" \
  "$JOB"
# If "captions:" block not present after init-job, append: printf '\ncaptions:\n  mode: off\n' >> "$JOB"

# 3. Auto-storyboard. Pass --videos-dir to interleave b-roll clips evenly across the
#    timeline (clips keep their real duration; images split the remaining time). Images
#    and clips are spread by story order — flexible to whatever count of each survived.
$VT storyboard auto "$JOB" --images-dir "$JOB_DIR/Image" --videos-dir "$JOB_DIR/Video"

# 4. Validate → render → package
$VT validate "$JOB"
$VT render "$JOB" --preset youtube-16x9   # default: long-form only, NO Shorts
# Tier-full overlay jobs: ensure outputs/captions.srt exists, then add --enhance full.
$VT package "$JOB"
```

### Audio-story channel default (e.g. BÌNH THIÊN SÁCH)
Seed `enhance:{visualizer:true,subtitles:true,progress_bar:false}`; `inputs.script`=`*_vi.txt`,
`inputs.description_template`=`_DESCRIPTION_TEMPLATE.txt` (needs `{{CHAPTERS}}`/`{{RECAP_PREV}}`/`{{SUMMARY}}`).
Author `project.recap_previous` (prev tập) + `project.description` (this tập) from vi.txt. CTA: if a
`CTA voice/` folder exists, set `inputs.intro_cta`/`outro_cta` + `inputs.intro_cta_image`/`outro_cta_image`
(prefer animated `Intro CTA.mp4`/`Outro CTA.mp4` in that folder if present — tool loops/trims clip to
voice length; else fall back to thumbnail/ending still) — tool splices at start/end, auto-shifts captions+chapters (adds
00:00 "Giới thiệu"). Then `transcribe "$JOB" --model "$HOME/.cache/videotool/models/faster-whisper-base"`
(PATH not bare `base`; slow on long audio; emits `chapters.json`) → `render --preset youtube-16x9`
(per-feature enhance drives overlays; NOT `--enhance full` — adds particles) → `package` (renders
`description.txt`). Paste it into the YouTube description for native chapters.

Render Shorts ONLY when the user asks (hint contains "shorts"/"9x16"/"--all"): add
`{preset: shorts-9x16}` to `outputs:` in job.yaml, then `$VT render "$JOB" --all`.

Outputs land in `$JOB_DIR/outputs/`:
- `youtube-16x9.mp4` (and `shorts-9x16.mp4` only if Shorts was requested)
- `thumbnail-1280x720.jpg`, `thumbnail-candidate-0[1-5].jpg`
- `description.txt`, `license-report.md`, `quality-report.json`, `package-manifest.json`
- `captions.srt` + `chapters.json` (only when subtitles on / transcribe ran)

## Known pitfalls (MUST handle)

1. **`init-job` writes `assets.policy: licensed-only`** (`src/videotool/core/job_spec.py:160`). Validation fails without an asset index. ALWAYS rewrite to `allow-missing-local`.
2. **`storyboard auto` needs `--videos-dir` to include b-roll clips.** Without it, only images are used. WITH it, clips are interleaved with images by story order (spread across the whole timeline, never bunched) and keep their real duration — pass `--videos-dir "$JOB_DIR/Video"` whenever a Video folder exists. Never drop clips.
3. **`captions.mode: srt-only` is the init default** — set `mode: off` for light jobs (YouTube auto-CC suffices). For audio-story channel jobs, subtitles come via `enhance.subtitles` + `transcribe` (Whisper `base` IS installed now). `enhance.subtitles` forces caption burn regardless of `captions.mode`.
4. **Music loop preparation** (`src/videotool/core/services.py:227`) only fires when `inputs.music` is set. Always include the music path if there's a music file in the folder.
5. **Render path branches at 40 scenes** (`render.max_inline_scenes`). >40 → segmented path. Light tier uses `-c:v copy` at mux; full tier re-encodes once for overlays. Don't force inline.

## Confirmed project decisions (do NOT silently reverse)

- **Tier light: no waveform / no self-made subtitles.** Zoompan defeats static detection without re-encode; YouTube auto-CC suffices. Stays the default for generic light jobs. *(Decided 2026-05-28; tier-scoped 2026-05-31.)*
- **Audio-story channel OVERRIDES the two above: showwaves + subtitles ON, progress bar OFF** (whisper `base` runs); **music bed default −30 dB**; **chapters from transcript (W1)** — `transcribe` emits `chapters.json`, no rendered progress bar (Sweezy-style is viewer-side). *(Decided 2026-05-31.)*
- **Tier full opts into overlays.** `--enhance full` burns existing `outputs/captions.srt`, adds bundled particle/progress/optional waveform, and re-encodes once.
- **Motion amplitude = 0.30, pan zoom = 1.22** (`src/videotool/render/video_filters.py` `ZOOM_AMPLITUDE` / `PAN_ZOOM`). Bumped up from 0.12 because long-duration images need visible per-second motion. Don't lower without checking with user. *(Decided 2026-05-28.)*
- **No auto Shorts.** Default render is `youtube-16x9` only; add `shorts-9x16` solely when the
  user asks. `init-job` / `storyboard plan` seed a single long-form preset. *(Decided 2026-05-29.)*
- **No CapCut / external editor.** Tool is self-sufficient via FFmpeg.
- **Caption mode default for our flow = `off`** (not `srt-only`).
- **Intro AND ending images both OVERLAY the narration (no added time)** — intro the first 10s,
  ending the LAST 10s. Keeps the ending card flush with the voice end so a spliced outro CTA
  card stays in sync with its voice (was "ending extends +10s", which desynced the outro CTA by
  10s and got -shortest-clipped). *(Decided 2026-06-13.)*
- **B-roll clips interleave with images by story order** via `storyboard auto --videos-dir`
  (spread across the whole timeline, never bunched; clips keep real duration). Never drop clips
  for stills — every chapter has b-roll. *(Decided 2026-06-13.)*
- **2.5D parallax = opt-in via `enhance.parallax: true`** (independent of tier; tier=full does
  NOT enable it). Stills become depth-parallax clips (DepthAnything V2-Small + numpy inverse-warp,
  CPU/offline) cached under `<job>/.videotool/parallax-cache`. A scene whose depth fails falls
  back to Ken Burns. Needs the `parallax` extra; on a no-GPU box install the **CPU torch build**
  (`pip install torch --index-url https://download.pytorch.org/whl/cpu` then `pip install -e .[parallax]`)
  and the model loads `local_files_only` to avoid an ~80s HF-Hub stall (first run downloads once).
  DepthFlow rejected for local (pyaudio needs sudo); only in the Colab GPU versions (`/Colab`).
  *(Decided 2026-06-15.)*

## Input format the user gives

Bare minimum: a folder path. Optional hints in free text: title, which preset to render (`youtube-16x9` / `shorts-9x16` / `--all`), specific music filename, language. Ask ONE concise question only if essential and unguessable.

## Verification commands

- `.venv/bin/python -m pytest -q` — full test suite, must be 66+ passing
- `.venv/bin/videotool doctor` — ffmpeg + env check
- `ffprobe -v error -show_entries stream=codec_name,width,height -of csv=p=0 <out.mp4>` — confirm h264 + aac + correct resolution

## Tech notes

- Python 3.12 venv at `.venv/`. Activate via the explicit binary paths above.
- AI extras (`faster-whisper` + deps) ARE installed; `base` model offline at `~/.cache/videotool/models/faster-whisper-base`. Used by `transcribe` for subtitles + chapter timing.
- FFmpeg is a hard dependency (`apt install ffmpeg`). Encoder default `libx264-balanced`.
- Key source files:
  - `src/videotool/core/job_spec.py` — pydantic schema
  - `src/videotool/core/storyboard.py` — autogen logic
  - `src/videotool/core/services.py` — orchestrates init/validate/render/package
  - `src/videotool/render/video_filters.py` — motion constants live here
  - `src/videotool/render/segmented.py` — long-video resumable render
  - `src/videotool/cli/main.py` — Typer CLI surface

## When to update this file

- CLI command names or args change → update "Standard pipeline".
- New pitfall discovered while running real jobs → add to "Known pitfalls".
- A user decision changes (with date) → update "Confirmed project decisions".
- Don't grow this past ~150 lines. Detail belongs in `docs/`.

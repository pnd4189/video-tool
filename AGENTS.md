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
  `inputs.ending_image`. Intro overlays the first 10s of the narration (no added time); the
  ending image extends the video by 10s after the voice ends.
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

# 3a. Auto-storyboard from IMAGES (autogen skips videos)
$VT storyboard auto "$JOB" --images-dir "$JOB_DIR/media"

# 3b. (IF folder has video clips .mp4/.mov) Append them as scenes manually.
#     Pick a sensible per-clip duration (or use ffprobe to get the real duration).
#     Edit "$JOB" YAML to add entries to the storyboard list.

# 4. Validate → render → package
$VT validate "$JOB"
$VT render "$JOB" --preset youtube-16x9   # default: long-form only, NO Shorts
$VT package "$JOB"
```

Render Shorts ONLY when the user asks (hint contains "shorts"/"9x16"/"--all"): add
`{preset: shorts-9x16}` to `outputs:` in job.yaml, then `$VT render "$JOB" --all`.

Outputs land in `$JOB_DIR/outputs/`:
- `youtube-16x9.mp4` (and `shorts-9x16.mp4` only if Shorts was requested)
- `thumbnail-1280x720.jpg`, `thumbnail-candidate-0[1-5].jpg`
- `description.txt`, `license-report.md`, `quality-report.json`, `package-manifest.json`

## Known pitfalls (MUST handle)

1. **`init-job` writes `assets.policy: licensed-only`** (`src/videotool/core/job_spec.py:160`). Validation fails without an asset index. ALWAYS rewrite to `allow-missing-local`.
2. **`storyboard auto` skips video clips** (`src/videotool/core/storyboard.py:149-156` — image extensions only). If the user's `media/` has `.mp4`, append video scenes to job.yaml after autogen.
3. **`captions.mode: srt-only` is the init default** — produces nothing meaningful unless `outputs/captions.srt` exists. Whisper is intentionally NOT installed; set `mode: off` to avoid surprises.
4. **Music loop preparation** (`src/videotool/core/services.py:227`) only fires when `inputs.music` is set. Always include the music path if there's a music file in the folder.
5. **Render path branches at 40 scenes** (`render.max_inline_scenes`). >40 → segmented path (resumable, `-c:v copy` at mux). For typical 100+ image audiobooks this is expected. Don't try to force inline.

## Confirmed project decisions (do NOT silently reverse)

- **No waveform / sound-wave overlay.** Would force segmented mux re-encode → ~2x render time. Zoompan motion already defeats YouTube's static detection. *(Decided 2026-05-28.)*
- **No self-made subtitles / no Whisper.** YouTube auto-CC is enough for audio-story channels. `faster-whisper` is deliberately uninstalled. *(Decided 2026-05-28.)*
- **Motion amplitude = 0.30, pan zoom = 1.22** (`src/videotool/render/video_filters.py` `ZOOM_AMPLITUDE` / `PAN_ZOOM`). Bumped up from 0.12 because long-duration images need visible per-second motion. Don't lower without checking with user. *(Decided 2026-05-28.)*
- **No auto Shorts.** Default render is `youtube-16x9` only; add `shorts-9x16` solely when the
  user asks. `init-job` / `storyboard plan` seed a single long-form preset. *(Decided 2026-05-29.)*
- **No CapCut / external editor.** Tool is self-sufficient via FFmpeg.
- **Caption mode default for our flow = `off`** (not `srt-only`).

## Input format the user gives

Bare minimum: a folder path. Optional hints in free text: title, which preset to render (`youtube-16x9` / `shorts-9x16` / `--all`), specific music filename, language. Ask ONE concise question only if essential and unguessable.

## Verification commands

- `.venv/bin/python -m pytest -q` — full test suite, must be 66+ passing
- `.venv/bin/videotool doctor` — ffmpeg + env check
- `ffprobe -v error -show_entries stream=codec_name,width,height -of csv=p=0 <out.mp4>` — confirm h264 + aac + correct resolution

## Tech notes

- Python 3.12 venv at `.venv/`. Activate via the explicit binary paths above.
- AI extras (`faster-whisper` + `onnxruntime` + `ctranslate2` + `av`) are deliberately uninstalled.
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

# Video Tool — Agent Guide

Canonical workflow doc. Read this every session before acting. Symlinked from `CLAUDE.md` and `GEMINI.md` so Claude Code, Antigravity (Agy), and Codex CLI all see the same source.

## Project Intent

Audio-first YouTube videos (kể truyện / audiobook). The product is the **audio + background music + thumbnail**. Video visuals exist only to defeat YouTube's static-frame penalty — quality is not a goal. Speed-to-publish wins over polish.

## When the user invokes `/make-video <folder> [hints]`

Run the 4-step CLI pipeline below, end-to-end, until an mp4 + package is on disk. Report paths at the end. Don't ask permission step-by-step — only ask if something in the folder is ambiguous.

## Asset folder convention

User points at a folder containing:

- `voice.wav` / `voice.mp3` / `voice.m4a` — the narration (required). **Prefer `.wav`** when several
  exist (`.wav` > `.m4a` > `.mp3`): lossless + no encoder-delay so the provided SRT stays in sync.
  Fall back to whatever is present — never fail just because `.wav` is absent.
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

### Mood / atmosphere FX are OFF by default (2026-07-03)
`/make-video` does NOT enable mood overlay or atmosphere by default and does NOT propose them.
Render clean. Only turn them on when the user explicitly asks for FX in the hint — then read the
story (first ~300 words of `*_vi.txt` + `*_image_prompts.txt`), pick a `mood`
(clean/melancholy/cozy/horror/action) and, if asked for atmosphere, ONE overlay from
`~/.local/share/videotool/overlays/`, and write `enhance.tier: full` (or per-feature) +
`enhance.mood` + `enhance.atmosphere: true` + `inputs.particle_overlay` into job.yaml
(`parallax` only if asked — expensive). No FX hint → do nothing, do not ask.

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

# 4. Validate → render → package → metadata
$VT validate "$JOB"
$VT render "$JOB" --preset youtube-16x9   # default: long-form only, NO Shorts
# Tier-full overlay jobs: ensure outputs/captions.srt exists, then add --enhance full.
$VT package "$JOB"
$VT metadata "$JOB"   # publisher tags + renames the mp4 to the episode title (see below)
```

### Audio-story channel default (e.g. BÌNH THIÊN SÁCH)
Seed `enhance:{visualizer:true,subtitles:true,subtitle_color:yellow}` (progress bar removed from all
jobs; `subtitle_color:yellow` = yellow fill + black outline, audio-story only, for legibility);
`inputs.script`=`*_vi.txt`, `inputs.description_template`=`_DESCRIPTION_TEMPLATE.txt`
(needs `{{CHAPTERS}}`/`{{RECAP_PREV}}`/`{{SUMMARY}}`).
Author `project.recap_previous` (prev tập) + `project.description` (this tập) from vi.txt. CTA: if a
`CTA voice/` folder exists, set `inputs.intro_cta`/`outro_cta` + `inputs.intro_cta_image`/`outro_cta_image`
(prefer animated `Intro CTA.mp4`/`Outro CTA.mp4` in that folder if present — tool loops/trims clip to
voice length; else fall back to thumbnail/ending still) — tool splices at start/end, auto-shifts captions+chapters (adds
00:00 "Giới thiệu"). **Subtitles come from the user-provided SRT, NOT whisper** (2026-07-03): copy the
supplied `*_vi_qa.srt` → `"$JOB_DIR/outputs/captions.srt"`, then `$VT chapters-from-srt "$JOB"`
(parses "Chương N:" markers → `chapters.json`; skips silently if <3 markers). `transcribe` is only for
when NO SRT is provided / cloud-GPU whisper. Then `render --preset youtube-16x9`
(per-feature enhance drives overlays; NOT `--enhance full` — adds particles) → **`$VT sfx "$JOB"`**
(mixes SFX cues onto the mp4, remux `-c:v copy`) → `package` (renders `description.txt`) →
**`$VT metadata "$JOB"`**. Paste `description.txt` into the YouTube description for native chapters.

**`metadata` = publisher tags + publish filename** (last step, after `package`). It renames
`youtube-16x9.mp4` to the episode title and writes the fields Windows Explorer shows, so YouTube
prefills the title from the filename on upload. Title/tags/genre are NOT invented: `project.title`
is the exact line from the series title list, and Tags + Genre are read back out of the rendered
`description.txt` (`==== TAGS` block, `• Thể loại:` line). Author `project.metadata` in job.yaml
from memory `series-channel-ownership` — it is constant for a whole series, and for a NEW series
you must ask the user at tập 1 which channel/URL owns it:

```yaml
project:
  title: "<full title from the series title list — becomes the mp4 filename>"
  metadata:
    channel: "Chính Dịch Đường"          # Directors/Producers/Publisher/Content provider/Encoded by
    channel_url: "https://www.youtube.com/@ChinhDichDuongVN"   # Author URL + Promotion URL
    original_author: "Vô Tội"            # Writers — we translate it, we did not write it.
                                         # Vietnamese only: no Chinese anywhere in the
                                         # description OR these tags (user decision 2026-08-25).
    copyright: "Bản dịch & sản xuất audio: Chính Dịch Đường. Nguyên tác thuộc về tác giả Vô Tội."
    subtitle: "Chương 421-435"
    release_date: "2026-08-24"           # today when unset
```

ĐẠO SĨ's title list separates the hook with `|`; write it as ` - ` in `project.title` so the tag
and the filename read the same (Windows rejects `|` in filenames). *(User decision 2026-08-24.)*

Needs ExifTool (`~/.local/share/videotool/exiftool/exiftool`, or on PATH) — ffmpeg cannot write the
Windows `Xtra` box the Origin fields live in. The cloud runner installs it into the same user dir
(the TPU box has no sudo) and treats the whole pass as best-effort: a finished render is never lost
over metadata, it just publishes untagged under the preset name.

**Music-schedule + SFX cues are authored by the LLM into job.yaml** (tool just renders them):
- **`audio.music_schedule`** — read `*_vi_qa.txt` + `*_music_prompts.txt` (N mood blocks, **block i ↔
  track i** natural-sorted in `Music/`) + chapter seconds from the SRT markers. Map each track to the
  chapter range whose mood fits (calm/scenery → gentle track, action/climax → faster track). Write cues
  `{track, start, end, gain_db?}` narration-aligned covering the whole voice. Unset → concat+loop.
- **`enhance.sfx.cues`** (default ON, ~12–15 cue/45min, auto-burn, NO montage) — scan
  `outputs/captions.srt` for action keywords, **drop metaphorical homographs** (grep context first),
  **pin by char-interpolation inside the cue** (`start + frac*(end-start)`, NOT segment-start, NOT
  re-transcribe). Copy chosen files from `~/.local/share/videotool/sfx/<pack>/` (kiếm hiệp→`binh-thien`,
  ma hài→`dao-si`) into `<job>/sfx/` and reference them job-relative. Point-SFX −8..−15 dB under voice,
  NOT ducked; cluster at climax, ~0 at exposition, ≥30–60s between clusters, ≤3/10s, skip first 30s /
  last 25s (CTA regions). Beds/ambient not built yet. See memories `sfx-insertion-workflow` /
  `sfx-library-location`.

Render Shorts ONLY when the user asks (hint contains "shorts"/"9x16"/"--all"): add
`{preset: shorts-9x16}` to `outputs:` in job.yaml, then `$VT render "$JOB" --all`.

Outputs land in `$JOB_DIR/outputs/`:
- `<episode title>.mp4` — renamed from `youtube-16x9.mp4` by `metadata` (and `shorts-9x16.mp4`,
  never renamed, only if Shorts was requested)
- `thumbnail-1280x720.jpg`, `thumbnail-candidate-0[1-5].jpg`
- `description.txt`, `license-report.md`, `quality-report.json`, `package-manifest.json`
- `captions.srt` + `chapters.json` (from the provided SRT via `chapters-from-srt`). `captions.srt` is
  RAW (narration-aligned, the burn baseline). When an intro CTA is spliced, `package` also writes
  `captions.youtube.srt` (shifted by the CTA offset) — **upload THAT one as the YouTube sidecar**,
  not `captions.srt` (raw lags the video by the CTA duration).

## Known pitfalls (MUST handle)

1. **`init-job` writes `assets.policy: licensed-only`** (`src/videotool/core/job_spec.py:160`). Validation fails without an asset index. ALWAYS rewrite to `allow-missing-local`.
2. **`storyboard auto` needs `--videos-dir` to include b-roll clips.** Without it, only images are used. WITH it, clips are interleaved with images by story order (spread across the whole timeline, never bunched) and keep their real duration — pass `--videos-dir "$JOB_DIR/Video"` whenever a Video folder exists. Never drop clips.
3. **`captions.mode: srt-only` is the init default** — set `mode: off` for light jobs (YouTube auto-CC suffices). For audio-story channel jobs, subtitles come via `enhance.subtitles` + the **user-provided SRT** copied to `outputs/captions.srt` (whisper `transcribe` is NOT in the default flow anymore — 2026-07-03). `enhance.subtitles` forces caption burn regardless of `captions.mode`.
4. **Music loop preparation** (`src/videotool/core/services.py:227`) only fires when `inputs.music` is set. Always include the music path if there's a music file in the folder.
5. **Render path branches at 40 scenes** (`render.max_inline_scenes`). >40 → segmented path. Light tier uses `-c:v copy` at mux; full tier re-encodes once for overlays. Don't force inline. On the segmented path scene clips render **in parallel** (one per core, cap 8; override with `VIDEOTOOL_SCENE_WORKERS`) and the atmosphere screen-blend is **baked per scene**, not at the mux — that blend used to pin ~90% of wall time to one core. *(2026-07-23.)*
6. **Render's mux step USED to crash `UnicodeDecodeError` COSMETICALLY when job/project metadata contained Vietnamese** (ffmpeg echoes `-metadata title=…`; a split multi-byte UTF-8 char on a stdout read boundary threw in strict-UTF-8 mode). FIXED 2026-07-06 (`package` `947cc00`, `render/executor.py`, `render/sfx_mix.py`) and extended 2026-07-13 to EVERY subprocess capture in the pipeline — `render/cta_compose.py`, `render/music_loop.py`, `core/media_probe.py`, `ai/whisper_cpp_adapter.py`, `ai/silence.py` all now pass `text=True, errors="replace"` so no ffmpeg/ffprobe/whisper output can crash the run on Vietnamese (or Latin-1 ID3) bytes. Residual fallback if it ever recurs: the mp4 is already fully written BEFORE the Python crash (ffmpeg keeps writing to disk), so verify the artifact (`ffprobe` shows full duration + `ffmpeg -v error -i out.mp4 -f null -` decodes clean) and proceed; do NOT re-render. Only treat a real failure as a real failure.

## Confirmed project decisions (do NOT silently reverse)

- **Tier light: no waveform / no self-made subtitles.** Zoompan defeats static detection without re-encode; YouTube auto-CC suffices. Stays the default for generic light jobs. *(Decided 2026-05-28; tier-scoped 2026-05-31.)*
- **Audio-story channel OVERRIDES the two above: showwaves + subtitles ON, progress bar OFF**; **music bed default −30 dB**. Subtitles + chapters now come from the **user-provided SRT** (see 2026-07-03 below), not whisper; no rendered progress bar (Sweezy-style is viewer-side). *(Decided 2026-05-31; SRT-sourced 2026-07-03.)*
- **`/make-video` defaults overhaul** *(Decided 2026-07-03)*:
  - **Provided-SRT, no whisper in default flow.** Copy the user's SRT → `outputs/captions.srt`; `chapters-from-srt` derives `chapters.json` from "Chương N:" markers. `transcribe`/whisper stays only for the no-SRT / cloud-GPU path.
  - **Mood/atmosphere OFF by default** and NOT proposed — only on explicit FX hint.
  - **WAV-first voice** (`.wav` > `.m4a` > `.mp3`) for quality + SRT sync; fall back, never fail.
  - **Yellow subtitles for audio-story only** via `enhance.subtitle_color: yellow` (fill `&H0000FFFF` + black outline). Default `white` keeps other jobs byte-identical. Legibility → retention, not an algorithm reading pixel colour.
  - **Audio AAC 256k** (was 192k), loudnorm target unchanged at −14 LUFS.
  - **Music-schedule + default SFX** (Plan 2): `audio.music_schedule` places a track per story-mood
    span (unset → concat+loop); `enhance.sfx` mixes one-shot SFX onto the mp4 post-process
    (`$VT sfx`, `-c:v copy`, NOT ducked, `amix normalize=0`+limiter), default ON ~12–15 cue/45min,
    auto-burn no montage. Cue times narration-aligned; tool shifts by the intro-CTA offset. SFX
    beds/ambient deferred.
- **Tier full opts into overlays.** `--enhance full` burns existing `outputs/captions.srt`, adds bundled particle/progress/optional waveform, and re-encodes once.
- **Motion amplitude = 0.30, pan zoom = 1.22** (`src/videotool/render/video_filters.py` `ZOOM_AMPLITUDE` / `PAN_ZOOM`). Bumped up from 0.12 because long-duration images need visible per-second motion. Don't lower without checking with user. *(Decided 2026-05-28.)*
- **No auto Shorts.** Default render is `youtube-16x9` only; add `shorts-9x16` solely when the
  user asks. `init-job` / `storyboard plan` seed a single long-form preset. *(Decided 2026-05-29.)*
- **Every published mp4 carries publisher metadata and is named after the episode title**
  (`$VT metadata`, last step). Filename = the title from the series title list, because YouTube
  prefills the upload title from it — that is the part with a real, observable effect. The
  in-container tags (Title/Tags/Genre/Origin credits) cost ~4s and no quality, but no public
  YouTube documentation says they affect ranking: they are a cheap bet plus a tidy library, NOT a
  substitute for the title/description/tags typed in Studio. A series' channel, URL, original
  author and credit line are fixed from tập 1 — ask the user for a NEW series, never guess.
  Applies from Bình Thiên Chap 41 / ĐẠO SĨ Chap 30 onward; already-published episodes are left
  alone. *(Decided 2026-08-24.)*
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
- **Progress bar REMOVED from every job.** The `enhance.progress_bar` key still validates but is
  a no-op (renders nothing). Sweezy-style progress is viewer-side. *(Decided 2026-06-15.)*
- **Full-tier "Group A" mood FX (filter-only, free, no assets):** `enhance.mood` ∈
  `clean/melancholy/cozy/horror/action` expands to vignette/grain/glow/flicker/color-grade.
  Mood is INDEPENDENT of tier (tier=full alone does NOT enable it); per-effect fields override the
  mood. Effects ride the single full-tier re-encode (cheap). When `/make-video`, suggest a mood
  that fits the video and write it into `job.yaml`. *(Decided 2026-06-15.)*
- **Atmospheric overlay = pick from local CC0 library.** `enhance.atmosphere: true` blends
  `inputs.particle_overlay` (rain/snow/fire/smoke/etc. loop, black bg) with `screen`. A local CC0
  library (ForFilmCreation + FX Elements, all converted to 4K H264 yuv420p, black-bg or
  alpha-flattened-on-black) lives at `~/.local/share/videotool/overlays/` (durable XDG data dir,
  NOT `~/.cache` — moved there 2026-06-21 so a cache wipe can't delete it), files named
  `{kind}-{src}-{id}.mp4` (`rain-* snow-* fire-* smoke-* particles-* dust-* cosmos-*` CC0 +
  generated `fireflies-gen-* ember-gen-* dust-gen-* qi-gen-*`). Generated overlays come from
  `scripts/gen_overlay.py --preset <fireflies|ember|dust>` (numpy, local, instant) and
  `Colab/qi_wisps_overlay_colab.py` (GLSL on Colab/Kaggle GPU → download `qi-gen-01.mp4`).
  When the user wants full FX, `ls` that folder, **suggest** the overlay that fits the
  video (read the story/scene mood first) and **WAIT for the user to confirm which overlay via a
  one-line proposal before rendering full**, then set `inputs.particle_overlay` to it
  (melancholy→`rain-*`, winter/cozy→`snow-*`, action/horror→`fire-*`/`smoke-*`,
  rural-night/summer→`fireflies-gen-*`, talisman-burning→`ember-gen-*`,
  mystical/qi/dreamy→`qi-gen-*`/`smoke-*`/`particles-*`/`cosmos-*`,
  old-film/abandoned-interior→`dust-*`/`dust-gen-*`) + `enhance.atmosphere: true`.
  One overlay slot per video; `particles` wins if both on. Masters stay on gdrive
  (`KHÁC/HIỆU ỨNG VIDEO/`); nothing copyrighted lives in the repo. Re-stage the library with
  `rclone` to the durable folder if it is ever cleared. Screen-blends (atmosphere + glow) run in
  `gbrp` (RGB) — blending in yuv420p tints the whole frame magenta; do NOT revert.
  *(Library + blend fix 2026-06-18; moved to durable dir + generated overlays 2026-06-21.)*
- **Colab DepthFlow 2.5D = separate `/parallax-video` command (NOT `enhance.parallax`).** GPU-offload
  path: Colab `Colab/v4_depthflow_clips_colab.py` renders one loopable 1080p clip per still →
  `Parallax/<image-stem>.mp4` (manual download + upload beside the asset folder). `/parallax-video`
  runs the same pipeline as `/make-video` plus `videotool parallax-link "$JOB" --clips-dir Parallax`,
  which swaps each image scene for its matching clip at the data layer (job.yaml); a still with no
  matching clip stays Ken Burns. Render needs no torch — it just loop+trims the clip. Distinct from
  the local-numpy `enhance.parallax` (2026-06-15), which stays as-is; `/make-video` untouched.
  *(Added 2026-06-18.)*
- **Full cloud render = separate parallel system (`Colab/cloud_render_runner.py`), NOT
  `/make-video`.** Reverses "render stays local" (2026-06): the whole pipeline can run on a free
  Colab/Kaggle T4 — `Colab/cloud_director.py` LLM-authors job.yaml, NVENC renders with resumable
  Drive checkpoints, results publish to the source folder's `Output/`. Zero local CPU. The local
  flow is byte-unchanged; the only shared-code touch is the additive `h264_nvenc-capped` profile.
  Cloud job.yaml sets `render.max_inline_scenes: 1` to force the resumable segmented path (schema
  forbids 0). Resume = rerun the cell (restores pinned job.yaml + ffprobe-verified clips, no LLM
  call). **Claude Code CLI is the director**: Claude reads the folder + authors a `creative.yaml`
  (music_schedule, SFX cues, mood, atmosphere overlay, description) locally — same intelligent work
  as local `/make-video`, incl. confirming the overlay with the user — then the render box just runs
  the deterministic pre-steps + `apply_creative` + NVENC render. **No LLM on the render box.** The
  on-box LLM (Kaggle Model Proxy `google/gemini-3.5-flash`; probed 2026-07-11 as the only slug that
  worked) survives only as an `autonomous=True` fallback for notebook-without-Claude. **Kaggle =
  primary** (4 vCPU > Colab 2; T4×2 gives NO render speedup — 1 ffmpeg uses 1 GPU; filters are the
  CPU bottleneck), **Colab = fallback on quota**. See `docs/cloud-render-setup.md`. Pain driving
  this = machine occupation/heat, not speed. *(Decided 2026-07-11.)*

## Input format the user gives

Bare minimum: a folder path. Optional hints in free text: title, which preset to render (`youtube-16x9` / `shorts-9x16` / `--all`), specific music filename, language. Ask ONE concise question only if essential and unguessable.

## Verification commands

- `.venv/bin/python -m pytest -q` — full test suite, must be 66+ passing
- `.venv/bin/videotool doctor` — ffmpeg + env check
- `ffprobe -v error -show_entries stream=codec_name,width,height -of csv=p=0 <out.mp4>` — confirm h264 + aac + correct resolution

## Tech notes

- Python 3.12 venv at `.venv/`. Activate via the explicit binary paths above.
- AI extras (`faster-whisper` + deps) ARE installed; `base` model offline at `~/.cache/videotool/models/faster-whisper-base`. Used by `transcribe` for subtitles + chapter timing. `transcribe` also takes `--device cuda --compute-type float16 --model large-v3` to run on cloud GPU (Kaggle/Colab) — see `docs/cloud-gpu-whisper-setup.md` + `Colab/{kaggle,colab}_runner.ipynb`.
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

# Codebase Summary

Audio-first YouTube video tool. Wraps FFmpeg + Whisper to render `voice + media + music + captions` into long-form `youtube-16x9.mp4` and optional `shorts-9x16.mp4`. CPU-only encode (libx264), no iGPU dependency.

---

## Project Intent

Transform **narration audio + background images/video + music** into YouTube-ready video packages, optimized for **speed-to-publish** (tier light: ~1h for 1h audio). Target: audiobook/truyện audio channels (Bình Thiên Sách, Đạo Sĩ, v.v.).

**Key decisions:**
- Schema-first (JobSpec is single source of truth)
- CLI-driven workflow (`videotool init-job → storyboard → validate → render → package`)
- No cloud, no CapCut, no auto model downloads (all offline)
- Tier light: Ken Burns + no re-encode
- Tier full: Single re-encode + mood FX + atmosphere overlays + subtitles

---

## Directory Layout

```
src/videotool/
├── cli/
│   ├── main.py              # Typer CLI entry (app:app)
│   ├── commands.py          # doctor, init-job, validate, probe, render, transcribe,
│   │                        # analyze-audio, package, benchmark
│   └── storyboard_commands.py  # storyboard plan, storyboard auto --images-dir --videos-dir
├── core/
│   ├── job_spec.py          # Pydantic schemas (JobSpec, AudioSpec, EnhanceSpec, etc.)
│   ├── timeline.py          # JobSpec → Timeline (planning IR; audio dB/duck/loudnorm)
│   ├── storyboard.py        # Image discovery, auto-gen even-split, B-roll interleave
│   ├── services.py          # Orchestrator: validate → stage → render → package
│   ├── media_probe.py       # ffprobe wrapper (duration, codec, resolution)
│   ├── validation.py        # JobSpec + path sanity checks
│   ├── errors.py            # Typed exceptions (ValidationError, RenderError, etc.)
│   ├── chapter_timing.py    # Derive YouTube chapters from aligned transcript
│   ├── parallax_link.py     # Swap stills with Colab parallax clips at data layer
│   ├── presets.py           # Profile definitions (libx264-balanced, libx264-fast)
│   └── logging.py           # Rich console output
├── render/
│   ├── commands.py          # JobSpec + Timeline → FFmpeg argv (inline path)
│   ├── segmented.py         # Scene-per-clip + concat demuxer (resumable, >40 scenes)
│   ├── audio_graph.py       # build_audio_graph(): voice → sidechain → amix → loudnorm
│   ├── video_filters.py     # Ken Burns (ZOOM_AMPLITUDE=0.30, PAN_ZOOM=1.22), mood FX,
│   │                        # atmosphere overlay, caption filter helpers
│   ├── music_loop.py        # prepare_seamless_music(): concat + loop + acrossfade
│   ├── executor.py          # Popen streaming, 6h timeout, SIGTERM on failure
│   ├── profiles.py          # Codec presets (CRF, preset, bitrate)
│   ├── workspace.py         # Temp file staging per job
│   └── parallax.py          # DepthAnything V2 integration (local CPU, optional)
├── ai/
│   ├── transcribe.py        # TranscriptResult, TranscriptSegment models
│   ├── faster_whisper_adapter.py  # Primary STT (faster-whisper [ai] extra)
│   ├── whisper_cpp_adapter.py     # Fallback STT
│   ├── align_script.py      # parse_script + align_script_to_transcript
│   │                        # (character-position interpolation onto whisper timing)
│   ├── subtitles.py         # SRT writer, CRLF-safe validator
│   └── silence.py           # Silence detection, cut suggestions
├── assets/
│   ├── library.py           # asset-index.yaml loader
│   ├── licenses.py          # Licensed-only policy enforcement
│   ├── reports.py           # License-report.md writer
│   ├── overlays/            # Bundled overlays (legacy, moved to ~/.local/share)
│   │   └── dust.mp4         # Example dust particle overlay
│   └── SOURCES.md
├── package/
│   ├── youtube.py           # validate_package, write_description (chapters/tags/CTA)
│   ├── thumbnails.py        # generate_thumbnail_candidates (5 stills)
│   ├── manifest.py          # package-manifest.json writer
│   └── reports.py           # quality-report.json (codec, loudness, bitrate)
└── gui/
    ├── app.py               # FastAPI app factory (videotool gui)
    ├── web_app.py           # Web interface shell
    ├── state.py             # Render queue state
    ├── queue.py             # Job queue management
    └── static/, templates/  # HTML/JS assets

tests/
├── test_job_spec.py         # Schema validation
├── test_timeline.py         # Timeline building
├── test_audio_graph.py      # Audio chain construction
├── test_music_loop.py       # Music seamless loop
├── test_subtitles.py        # Subtitle alignment (char-position)
├── test_storyboard.py       # Storyboard auto-gen, B-roll interleave
├── test_segmented_plans.py  # Segmented render planning
├── test_render_executor.py  # FFmpeg execution
└── fixtures/
    └── generated/           # Synthetic fixtures (ffmpeg -f lavfi, no pre-recorded)

Colab/
├── v4_depthflow_clips_colab.py    # DepthFlow GPU renders stills → 1080p clips
├── qi_wisps_overlay_colab.py      # GLSL qi-wisps atmosphere generator
├── v3_depthflow_colab.py          # Earlier variant (kept for reference)
├── v2_depthanything_parallax_colab.py
├── v1_current_workflow_colab.py
└── ...

scripts/
├── gen_overlay.py           # Local numpy generators (fireflies, ember, dust)
└── generate-test-media.sh   # Tiny test fixtures (ffmpeg)

docs/
├── codebase-summary.md      # This file
├── project-overview-pdr.md  # Product intent, target user, success criteria
├── deployment-guide.md      # Installation variants, troubleshooting
├── system-architecture.md   # Render flow, audio chain, tier paths, tier branching
├── code-standards.md        # Python style, Pydantic schema-first, testing
├── design-guidelines.md     # Motion (Ken Burns), loudness, subtitle timing, mood FX, mood map
├── project-changelog.md     # 2026-05-20 to 2026-06-21 updates
├── project-roadmap.md       # Now/deferred/won't-do
└── journals/                # Session logs (Colab parallax shipped, atmosphere generators, etc.)

examples/
├── jobs/
│   └── basic-audio-first/
│       └── job.yaml         # Example job.yaml (reference)
└── assets/
    └── asset-index.yaml     # Example asset library metadata

.claude/
├── commands/
│   ├── make-video.md        # /make-video skill doc
│   └── parallax-video.md    # /parallax-video skill doc
├── agent-memory/
│   └── planner/
│       └── MEMORY.md        # Planner memory for parallax 2.5D
└── settings.local.json

.gemini/
├── commands/
│   └── make-video.toml      # Gemini CLI config

plans/
├── 260519-*/                # V1 foundation plan
├── 260527-*/                # Audio-story autopublisher MVP
├── 260531-*/                # Render enhance tier (light/full)
├── 260614-*/                # Local parallax 2.5D integration
├── 260618-*/                # Colab DepthFlow parallax shipped
├── 260621-*/                # Atmosphere overlay generators
└── reports/                 # Plan reports, research summaries
```

---

## CLI Surface

**Commands:**
- `doctor` — Check FFmpeg, Python, venv, dependencies
- `init-job <dir>` — Create job.yaml skeleton
- `validate <job.yaml>` — Schema + asset policy + path checks
- `probe <audio/video>` — ffprobe wrapper (duration, codec, resolution)
- `render <job.yaml>` — Render video (inline ≤40 scenes, segmented >40)
  - `--preset youtube-16x9 | shorts-9x16` — Output format
  - `--all` — Render all presets
  - `--dry-run` — Print FFmpeg command, don't execute
  - `--enhance light | full` — Apply tier FX
- `batch <job1.yaml> <job2.yaml> ...` — Parallel render (ProcessPoolExecutor)
- `transcribe <job.yaml>` — Whisper STT → captions.srt + chapters.json
  - `--model <path>` — Model folder (e.g., `~/.cache/videotool/models/faster-whisper-base`)
  - `--script <script.txt>` — Align script to whisper timing
- `analyze-audio <audio.wav>` — Silence detection, loudness analysis
- `package <job.yaml>` — YouTube artifacts (description, thumbnails, manifest)
- `benchmark` — Performance profiling
- `gui` — FastAPI web interface (thin wrapper)
- `storyboard plan` — Prompt-driven storyboard (deprecated, not recommended)
- `storyboard auto <job.yaml>` — Even-split images + interleave clips
  - `--images-dir <dir>` — Scene image folder
  - `--videos-dir <dir>` — Scene video clip folder (optional)
- `parallax-link <job.yaml>` — Swap stills with Colab parallax clips
  - `--clips-dir <dir>` — Parallax/ folder with scene-*.mp4 clips
- `parallax-video <job.yaml>` — Full /parallax-video pipeline (init + storyboard + parallax-link + render + package)

---

## Render Flow (Core Logic)

### 1. services.run_validate()

```python
validate(job_spec, job_dir):
  → Pydantic schema validation
  → File existence checks (voice, images, clips, music)
  → Asset policy enforcement (licensed-only vs allow-missing-local)
  → Path escaping validation (subtitles, overlays, scripts)
  → Return: validated JobSpec or raise ValidationError
```

### 2. services.run_render()

```python
render(job, job_dir, preset):
  → Workspace.prepare()  # Create <job>/.videotool/temp/
  → _stage_subtitle()    # Copy outputs/captions.srt to temp (short ASCII path)
  → _stage_music()       # prepare_seamless_music() → music-loop.flac
  → Decide inline vs segmented based on scene count
  
  IF inline (≤40 scenes):
    → build_render_plans()  # One CommandPlan per output
    → RenderExecutor.run()  # Single FFmpeg with xfade storyboard
    
  ELSE (>40 scenes):
    → build_segmented_plans()  # One SegmentedPlan per output
    → RenderExecutor.run_segmented()  # Per-scene clips, concat demuxer
    → For each scene: render clip, skip if cached
    → Final audio-mux pass
  
  → Render to outputs/<preset>.mp4
```

### 3. services.run_package()

```python
package(job, job_dir):
  → validate_package()  # Check outputs/ artifacts exist
  → generate_thumbnail_candidates()  # 5 stills (25%, 50%, 75%, etc.)
  → write_description()  # Render template ({{CHAPTERS}}, {{RECAP}}, {{SUMMARY}})
  → write_license_report()  # Credits for assets
  → write_quality_report()  # Codec, loudness, bitrate, duration
  → write_manifest()  # package-manifest.json (metadata)
  → Outputs: *.mp4, *.jpg, .txt, .md, .json
```

---

## Inline Render (≤40 Scenes)

**Single FFmpeg call with one filtergraph:**

```
Input: voice.wav + media/ (images/clips) + music-loop.flac

Audio chain:
  voice → atempo? → asplit ──┬──> [voice_main] ──┐
                             └──> [voice_key]   │
                                                 ▼
  music → sidechaincompress(key=voice_key) ──> [duck]
          (threshold=0.05, ratio=8, attack=5, release=400)
  
  [voice_main] + [duck] → amix → loudnorm(I=-14:TP=-1:LRA=11) → AAC output

Video chain:
  scene-001.jpg/mp4 → zoom/pan (Ken Burns or clip duration)
  scene-002.jpg/mp4 → xfade(0.5s) → zoom/pan
  ...
  scene-NNN.jpg/mp4 → [video_out]

Optional:
  captions.srt → [subtitles filter] → (overlays video)
  mood FX → vignette/grain/glow/flicker/color-grade
  atmosphere → screen-blend overlay (rgb format)

Output: H.264 (CRF 23 light / CRF 22 full) + AAC
```

**Speed:** ~1h for 1h audio (real-time, no re-encode on light tier)

---

## Segmented Render (>40 Scenes)

**Per-scene clips + concat demuxer:**

```
For each scene:
  → ffmpeg render → <workspace>/clips/<preset>/scene-NNNN.mp4
  → Skip if cached (resumable)

Concat phase:
  → Write concat demuxer list file
  → ffmpeg concat → join all clips
  
Audio mux pass:
  → Build audio (voice + music + sidechain + loudnorm)
  → Mux into final video

Output: <job_dir>/outputs/<preset>.mp4
```

**Speed:** ~2–3h for 1h audio (per-scene encode + mux overhead)

**Resumable:** Restart from scene N if earlier clips done.

---

## Audio Chain Details

(`render/audio_graph.py:build_audio_graph`)

**Voice → Music Sidechain:**

```
Input: voice.wav (44.1kHz or resampled), music-loop.flac (48kHz stereo)

voice → atempo=<pitch_correction>?  # if needed
        → asplit ──┬──> [voice_main]  # Main mix output
                   └──> [voice_key]   # Sidechain key

music → sidechaincompress(
          threshold=0.05,     # Sensitivity to voice
          ratio=8,            # Strong duck (8:1)
          attack=5,           # Fast respond to voice
          release=400,        # Slow fade out when voice stops
          makeup=2            # Gain compensation
        ) ──> [duck]

[voice_main] + [duck] ──> amix=inputs=2:duration=longest
                          → loudnorm=I=-14:TP=-1:LRA=11
                          → aformat=sample_rates=48000:channel_layouts=stereo
                          → AAC output
```

**Settings from JobSpec:**
- `audio.voice_gain_db` (default 0): pre-loudnorm scaling
- `audio.music_gain_db` (default −30): music bed level
- `audio.duck` (default true): enable sidechain
- `audio.normalize_lufs` (default −14): target loudness; null = skip

**Result:** Music auto-ducks when voice present, no manual curves needed.

---

## Music Seamless Loop

(`render/music_loop.py`)

**Problem:** Single music track clicks audibly every N seconds on long videos.

**Solution:**
1. Take ordered track list (music/ folder, natural-sorted `01-`, `02-`)
2. If ≥target duration: trim single track with fade-out
3. Else: cycle + concat with `acrossfade(d=2s, curve1=tri, curve2=tri)` ← 2s fade between reps
4. Normalize each segment (resample, stereo)
5. Trim + fade-out tail
6. Output: FLAC (lossless) at `<workspace>/music-loop.flac`

**Performance:**
- ~30s prep for 1h audio + 3-track mix
- MAX_PLAYS=200 (raise RenderError if exceeded)

---

## Subtitle & Chapter Timing

### Script Alignment (Tier Full)

**Source:** Script (text) + Whisper transcript (timing)

**Algorithm** (`ai/align_script.py`):
1. Parse script into sentence cues
2. For each cue: find whisper segment span
3. Map character position to span percentage → interpolate timing
4. Result: SRT with script wording + whisper timing

**Why character-position (NOT segment-start):**
- Whisper segments ≠ sentence boundaries
- Segment-start would cause timing jumps
- Character-position is monotonic, bounded, robust
- Validated 2026-06-24 with SFX insertion

### Chapter Derivation (Audio-Story Channel)

**Source:** Aligned transcript (from transcribe output)

**Logic** (`core/chapter_timing.py`):
1. Find all "Chương" markers in transcript
2. If ≥3 chapters: derive timestamps from alignment
3. If <3 chapters: skip auto-gen (user hand-writes chapters.json)
4. Output: `outputs/chapters.json`

**YouTube format:** Paste description.txt into description field; YouTube auto-parses chapters.

---

## Tier Light vs Tier Full

| Aspect | Light | Full |
|--------|-------|------|
| **Encode** | Single pass, `-c:v copy` mux (no re-encode) | Single re-encode (burns overlays) |
| **CRF** | 23 | 22 |
| **Motion** | Ken Burns (0.30, 1.22) | Ken Burns (same) |
| **Subtitle** | None (YouTube auto-CC) | Yes (whisper-aligned via script) |
| **Mood FX** | None | 5 presets (clean/melancholy/cozy/horror/action) |
| **Atmosphere** | None | Optional CC0 overlays (rain/snow/fire/etc.) |
| **Speed** | ~1h for 1h audio | ~2–3h for 1h audio |
| **Use case** | Weekly release pace | Premium episodes, flagship releases |

**Both tiers share:** Audio chain (sidechain, loudnorm), Ken Burns motion, B-roll interleave.

**Full-tier only:** Re-encode (unavoidable for subtitle burn) + mood filters (cheap, rides single pass).

---

## Mood FX (Independent of Tier)

**5 presets** (`src/videotool/render/video_filters.py`):

| Mood | Filters | Use |
|------|---------|-----|
| clean | vignette (6%) | Light, uplifting |
| melancholy | grain (0.05) + vignette (8%) | Sad, contemplative |
| cozy | warm color (8000K) + soft glow | Comfortable, intimate |
| horror | flicker (10%) + high contrast | Suspense, scary |
| action | oversaturation (1.4×) + contrast | Energy, excitement |

**Decided:** `enhance.mood` is **independent of tier**. Tone customization available at all quality levels.

**Override per-effect:** `enhance.grain: false` to disable grain for melancholy.

---

## Atmosphere Overlays (CC0 Library)

**Location:** `~/.local/share/videotool/overlays/` (durable XDG, not cache)

**Naming:** `{kind}-{source}-{id}.mp4`

**Mood map (suggestions):**
- Melancholy → rain-*
- Cozy/Winter → snow-*
- Action/Horror → fire-*, smoke-*
- Mystical → qi-gen-*, particles-*
- Old-film → dust-*, dust-gen-*
- Summer → fireflies-gen-*

**Blending:** Screen (lighten) in RGB (`gbrp`, NOT yuv420p — prevents magenta tint).

---

## B-Roll Interleave

**Requirement:** Never drop video clips; spread by story order, full duration kept.

**Algorithm** (`core/storyboard.py`):
1. Discover images + video clips (scene-001.jpg, scene-001.mp4, etc.)
2. Interleave by story order (alternate when both present for a scene)
3. For each clip: use real duration (no trim unless exceeds remaining narration)
4. For each image: Ken Burns or parallax animation
5. Timeline: accumulate durations, map to voice narration

**Example:**
```
Story: image-001 (5s) + video-002 (3s) + image-003 (5s) + video-004 (5s) = 18s
Voice: 20s total
→ Timeline maps each scene to available time
```

---

## Parallax (2.5D Stills)

### Local Path (CPU, Optional)

**Opt-in:** `enhance.parallax: true` in job.yaml

**Process:**
1. For each still: run DepthAnything V2-Small
2. Generate depth map, cache at `<job>/.videotool/parallax-cache/`
3. Render with parallax motion (pseudo-3D inverse-warp)
4. Fall back to Ken Burns if depth fails

**Speed:** 1–2 min/still on CPU

**Model:** ~350MB (cached at `~/.cache/videotool/models/`)

### Colab Path (GPU, Optional)

**Separate command:** `/parallax-video <job_dir>`

**Process:**
1. User runs `Colab/v4_depthflow_clips_colab.py` on GPU
2. Outputs 1080p loopable clips (1 per still)
3. User downloads `Parallax/` folder, uploads beside asset folder
4. `/parallax-video` runs:
   - parallax-link (swap stills with clips at data layer)
   - Render (no torch needed locally, just loop+trim)
   - Package

**Speed:** Colab 4–6h + local render 30min

---

## Testing

**155+ tests** (pytest):
- Schema validation
- Timeline building
- Audio graph construction
- Music loop preparation
- Subtitle alignment
- Storyboard auto-gen, B-roll interleave
- Segmented render planning
- Error propagation

**Fixtures:** Synthetic audio (ffmpeg -f lavfi), dummy images, no heavy downloads.

**Run:**
```bash
.venv/bin/python -m pytest -q
# Expected: 155+ pass
```

---

## Git & Commits

**Conventional commits (no AI references):**
- `feat(render): add mood FX filters`
- `fix(music-loop): prevent click at boundary`
- `test(audio-graph): add sidechain validation`
- `docs: update deployment guide`

**Branches:**
- `feat/parallax-2-5d` (active development)
- `main` (stable releases)

---

## Performance Profile

| Job | Input | Render | Total |
|-----|-------|--------|-------|
| Light 1h, 20 stills | 500MB | ~1h | ~1h |
| Full 1h, 20 stills | 500MB | ~2.5h | ~2.5h |
| Parallax 1h (Colab) | 500MB | ~30min | ~7h (Colab 6h + local 1h) |

**Hardware:** AMD Ryzen 5 7640HS (8 cores), 30GB RAM, SSD

---

## Key References

- **[CLAUDE.md](../CLAUDE.md)** — Canonical workflow (4-step pipeline, pitfalls, confirmed decisions)
- **[docs/project-overview-pdr.md](./project-overview-pdr.md)** — Product intent, target user, success criteria
- **[docs/deployment-guide.md](./deployment-guide.md)** — Installation variants, troubleshooting
- **[docs/system-architecture.md](./system-architecture.md)** — Render flow, audio chain, tier branching
- **[docs/code-standards.md](./code-standards.md)** — Python style, schema-first, testing strategy
- **[docs/design-guidelines.md](./design-guidelines.md)** — Motion (Ken Burns 0.30, 1.22), loudness (−14 LUFS), subtitle timing, mood FX, mood map

---

## Recent Updates (2026-06-18 to 2026-06-21)

- **2026-06-18:** Colab DepthFlow parallax shipped (`/parallax-video` command + `parallax-link` + v4_depthflow_clips_colab.py)
- **2026-06-18:** Fixed atmosphere overlay blending to RGB (`gbrp`, NOT yuv420p — prevents magenta tint)
- **2026-06-21:** Added local overlay generators (numpy point-sprite: fireflies, ember, dust)
- **2026-06-21:** Moved overlay library to durable `~/.local/share/videotool/overlays/` (not cache)
- **2026-06-21:** Documented mood map + confirmed decisions (glow wash-out workaround, particle path validation, <3 chapters hand-write)
- **2026-06-24:** Validated SFX insertion workflow (char-position interpolation, not whisper segment-start)

---

**Last updated:** 2026-06-25

**For detailed workflow:** Read [CLAUDE.md](../CLAUDE.md) before running `/make-video`.

**For development:** Read [docs/code-standards.md](./code-standards.md) before editing code.

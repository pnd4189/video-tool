# System Architecture

## High-Level Flow

```
CLI Entry (main.py)
    ↓
JobSpec Pydantic Schema (job_spec.py)
    ↓
Services Orchestrator (services.py)
    ├─ validate() → schema + asset policy
    ├─ render() → Timeline + Workspace → Render Executor
    │   ├─ Inline path (≤40 scenes) → single FFmpeg
    │   └─ Segmented path (>40 scenes) → per-scene clips + concat demuxer
    └─ package() → YouTube artifacts (description, thumbnails, manifest)
```

---

## Core Components

### 1. Job Schema (`core/job_spec.py`)

**Pydantic 2.7 models** define the entire job:

```python
class JobSpec:
    project: ProjectSpec          # title, chapters, description
    inputs: InputSpec             # voice, media, music, script, intro/ending images
    storyboard: List[SceneSpec]   # scenes with motion/duration
    audio: AudioSpec              # voice_gain_db, music_gain_db, duck, loudnorm
    captions: CaptionSpec         # mode: off | srt-only | srt-and-burn
    enhance: EnhanceSpec          # tier, mood, atmosphere, parallax, grain, glow, flicker
    outputs: List[OutputSpec]     # presets (youtube-16x9, shorts-9x16)
    render: RenderSpec            # max_inline_scenes (default 40)
    assets: AssetsSpec            # policy: licensed-only | allow-missing-local
```

**Why schema-first:**
- Single source of truth for all configuration
- Validation at every boundary (CLI input, render, package)
- AI agents can read schema to infer valid values
- No runtime surprises (all defaults, ranges declared upfront)

---

## Render Paths

### Path A: Inline (≤40 scenes)

**Single FFmpeg call** with one filtergraph:

```
voice.wav → [voice_main] ──┐
            [voice_key]   │
                          ├─ amix → loudnorm → AAC output
music-loop.flac ──┬──────┤
                  ↓ sidechain (voice_key)
                 [duck]

media/ scenes → zoom/pan/xfade ──→ H264 video output
captions.srt (optional) ──────────┘
```

**Timeline construction** (`core/timeline.py`):
1. `build_timeline(job_spec)` → `Timeline` object
   - Scene timing (cumulative, in seconds)
   - Audio dB gains, sidechain duck settings
   - Voice pad if ending image extends past narration

2. `render/commands.py` generates FFmpeg command:
   - Build audio_graph (voice → atempo → sidechain → amix → loudnorm)
   - Build video_graph (scenes → xfade with Ken Burns per scene)
   - Optional caption filter (`subtitles=...`)
   - Optional mood/atmosphere overlay (full tier)

**Speed:** ~1h for 1h audio (real-time, no re-encode on light tier)

### Path B: Segmented (>41 scenes)

**Per-scene clips + concat demuxer:**

```
Scene 1 → ffmpeg render → scene-0001.mp4 ──┐
Scene 2 → ffmpeg render → scene-0002.mp4 ──┤
  ...                                        ├─ concat demuxer → output.mp4
Scene N → ffmpeg render → scene-NNNN.mp4 ──┤
                                            │
Audio mux pass (separate, final) ──────────┘
```

**Why segmented:**
- No single filtergraph explosion (complexity O(n))
- Resumable: skip already-rendered clips
- Memory: ~800MB per clip vs potential 2GB+ for 100-scene graph

**Implementation** (`render/segmented.py`):
1. `build_segmented_plans()` → list of `SegmentPlan`
   - One per output preset
   - Each segment targets `clips/<preset>/scene-NNNN.mp4`
   - Metadata carries motion/duration per scene

2. `RenderExecutor.run_segmented()`:
   - For each scene: check if clip exists (resumable)
   - If not: render with per-scene audio (voice + sidechain + loudnorm)
   - Collect all clips
   - Concat with demuxer (hard cut, softened by per-clip fade)
   - Final audio-mux pass (audio from first clip, muxed into output)

**Speed:** ~2–3h for 1h audio (per-scene encode + mux)

---

## Audio Chain

### Voice + Music Sidechain

(`render/audio_graph.py:build_audio_graph`)

```
Input: voice.wav + music-loop.flac

voice → [tempo adjustment if needed]
        → asplit ──┬──> [voice_main] ──┐
                   └──> [voice_key]   │
                                      ▼
music → sidechaincompress(key=voice_key) ─→ [duck]
        (threshold=0.05, ratio=8, attack=5, release=400, makeup=2)

[voice_main] + [duck] → amix → loudnorm(I=-14:TP=-1:LRA=11) → AAC output
```

**Settings** (`core/job_spec.py:AudioSpec`):
- `voice_gain_db` (default 0): scale voice before loudnorm
- `music_gain_db` (default −30): music bed level (−28 for light jobs, −30 for audio-story channel)
- `duck` (default true): sidechain active
- `normalize_lufs` (default −14.0): YouTube spec; null = skip loudnorm

**Result:** Music automatically pulls back under voice, no manual gain curves.

---

## Music Seamless Loop

(`render/music_loop.py:prepare_seamless_music`)

**Problem:** Single short music loop clicks audibly every time it repeats on 1h+ videos.

**Solution:**
1. Takes ordered track list (from `music/` folder, natural-sorted)
2. If single track ≥ target duration: trim with `afade=t=out`
3. Otherwise: cycle tracks until they cover target
4. Chain via `acrossfade(d=2s, curve1=tri, curve2=tri)` ← 2s fade between reps
5. Trim end + fade-out tail
6. Output: FLAC (lossless) at `<workspace>/music-loop.flac`

**Performance:** ~30s prep for 1h audio + 3-track mix

---

## Subtitle & Chapter Timing

### Subtitle Path (Tier Full)

**Input:** Script (`.txt`) + Whisper transcript

**Process** (`ai/align_script.py`):
1. `parse_script()` → sentence cues from prose
2. `align_script_to_transcript()` → map cues onto whisper segment spans
   - Proportional timing: cue character position → span percentage → start + duration
   - Monotonic: no backwards jumps
   - Bounded: cue duration ≤ span duration

**Output:** SRT (SubRip format) with precise timing

**Why NOT segment-start:** Whisper segments ≠ sentence boundaries. Script alignment is robust; segment-start is flaky (2026-06-24 validated with SFX insertion).

### Chapter Timing (Audio-Story Channel)

**Input:** Aligned transcript (from transcribe)

**Process** (`core/chapter_timing.py`):
1. Find all "Chương" markers in transcript
2. If ≥3 chapters: derive timestamps from alignment timing
3. If <3 chapters: skip auto-generation (hand-write `chapters.json`)
4. Output: `outputs/chapters.json`

**YouTube chapters:** Pasted from `description.txt`, auto-formatted by YouTube

---

## Tier Light vs Tier Full

### Tier Light (Default)

- **Encode:** Single pass, libx264 CRF 23, `-c:v copy` on mux (no re-encode)
- **Motion:** Ken Burns (0.30 zoom amplitude, 1.22 pan zoom)
- **Subtitle:** None (YouTube auto-CC)
- **FX:** None
- **Speed:** ~1h for 1h audio
- **Use case:** Generic audio-story uploads, weekly releases

### Tier Full

- **Encode:** Single re-encode (libx264 CRF 22), all overlays burned during encode
- **Motion:** Ken Burns (same as light)
- **Subtitle:** Whisper-aligned, burned at full tier
- **FX:** Mood (5 presets) + optional atmosphere overlay
- **Speed:** ~2–3h for 1h audio
- **Use case:** Flagship episodes, promotional content, special releases

**Key difference:** Full tier re-encodes ONCE and burns everything (subtitles, mood filters, atmosphere); light tier avoids re-encode entirely.

---

## Mood FX (Group A)

**Filter-only presets**, independent of tier (tier=full alone does NOT enable mood).

Configured in `enhance.mood` ∈ {clean, melancholy, cozy, horror, action}:

| Mood | Filters |
|------|---------|
| clean | vignette (subtle) |
| melancholy | grain (noise) + vignette |
| cozy | warmth (color shift) + soft glow |
| horror | flicker + high contrast |
| action | saturated color + high contrast |

**Implementation:** Filtergraph applied in single full-tier re-encode. Per-effect fields in job.yaml override preset (e.g., `enhance.grain: false` disables grain for melancholy).

**Note:** `enhance.mood=melancholy` auto-enables grain. If file balloons (~700× larger), add `enhance.grain: false`.

---

## Atmosphere Overlays

**CC0 library at `~/.local/share/videotool/overlays/`** (durable XDG data dir, NOT cache).

**Naming:** `{kind}-{source}-{id}.mp4`

```
rain-forfilmcreation-001.mp4       # CC0 rain loop
snow-forfilmcreation-002.mp4       # CC0 snow
fire-fxelements-003.mp4            # CC0 fire
fireflies-gen-001.mp4              # Generated (numpy point-sprite)
ember-gen-001.mp4                  # Generated (numpy particle)
dust-gen-001.mp4                   # Generated (numpy particle)
qi-gen-001.mp4                     # Generated (GLSL on Colab)
particles-gen-001.mp4              # Generated particle mix
cosmos-generated.mp4               # Starfield/cosmos
```

**Application:**
1. Input overlay: black background or alpha
2. Blend mode: screen (lighten) via FFmpeg `overlay=format=rgb`
3. Duration: looped/trimmed to match scene
4. Output: Combined video frame (RGB, NOT yuv420p which causes magenta tint)

**Mood map (suggestion only; user confirms):**
- Melancholy → rain-*
- Cozy/Winter → snow-*
- Action/Horror → fire-* or smoke-*
- Mystical/Spiritual → qi-gen-* or fireflies-gen-*
- Abandoned/Old-film → dust-* or dust-gen-*
- Summer night → fireflies-gen-*
- Dreamy → particles-* or cosmos-*

---

## Parallax (2.5D Stills)

### Local Path (CPU, DepthAnything V2)

**Opt-in:** `enhance.parallax: true` in job.yaml

**Process:**
1. For each still in storyboard:
   - Check cache at `<job>/.videotool/parallax-cache/scene-NNNN-depth.npy`
   - If missing: run DepthAnything V2-Small (1–2 min on CPU)
   - Save depth map
2. Generate Ken Burns variant with parallax:
   - Inverse-warp using depth map
   - Camera moves through 3D pseudo-space
   - Falls back to Ken Burns if depth fails (invalid image, etc.)
3. Render as normal

**Speed:** 1–2 min/still (CPU), cached thereafter

**Size:** Depth model ~350MB (cached at `~/.cache/videotool/models/`)

### Colab Path (GPU, DepthFlow Offload)

**Separate command:** `/parallax-video <job_dir>`

**Process:**
1. User runs `Colab/v4_depthflow_clips_colab.py` on GPU
   - Takes each still
   - Outputs 1080p loopable clip per still
   - Downloads to `Parallax/` folder
2. User uploads `Parallax/` folder beside asset folder locally
3. Run `/parallax-video`:
   - `parallax-link <job> --clips-dir Parallax` → swap stills with clips at data layer
   - Render as normal (clips are pre-rendered, no torch locally)

**Speed:** Colab 4–6h + local render 30min = ~7h total

**Advantage:** Best-quality depth + motion; GPU off-loaded

---

## B-Roll Interleave

**Requirement:** Video clips spread by story order, full duration kept, never drop.

(`core/storyboard.py:build_even_split_storyboard`)

**Algorithm:**
1. Separate media into images and video clips
2. Sort by name (scene-001, scene-002, etc.)
3. Interleave: alternate image/clip slots maintaining story order
4. For each slot:
   - Image: use Ken Burns (or parallax if enabled)
   - Clip: use full duration (no trim unless exceeds remaining narration)
5. Timeline: accumulate durations, map to voice narration

**Example:**
- Story: Scene 1 (image) + Scene 2 (clip 5s) + Scene 3 (image) + Scene 4 (clip 3s)
- Voice: 20s total
- Output: image (5s) + clip (5s) + image (5s) + clip (5s) — all fit, no drop

---

## Validation Layer

(`core/validation.py`)

**Checks performed:**
1. **Schema:** Pydantic validates job.yaml against JobSpec
2. **File existence:** voice, images, clips, music paths verified
3. **Asset policy:** Licensed-only → asset-index.yaml required; allow-missing-local → skip
4. **Video codec:** Supported presets exist in ProfileSpec
5. **Path escaping:** Subtitles, overlays, scripts path-safe (no shell injection)
6. **Particle overlay inside job folder:** Relative path from job root (validation escapes prevent breakout)

**Error handling:** TypeError + detail → user sees exact cause (missing file, invalid codec, etc.)

---

## Package Layer

(`package/`)

**Outputs:**
- `youtube-16x9.mp4` (main video)
- `shorts-9x16.mp4` (if requested)
- `thumbnail-1280x720.jpg` (primary)
- `thumbnail-candidate-01.jpg` through `thumbnail-candidate-05.jpg` (alternatives)
- `description.txt` (YouTube description with chapters, tags)
- `license-report.md` (asset credits)
- `quality-report.json` (codec, loudness, duration, bitrate)
- `package-manifest.json` (metadata: title, author, chapters)
- `captions.srt` (if transcribed)
- `chapters.json` (if transcribed, ≥3 chapters)

**Description template** (`package/youtube.py`):
- Supports `{{CHAPTERS}}`, `{{RECAP_PREV}}`, `{{SUMMARY}}` placeholders
- Rendered from `inputs.description_template` path
- User supplies recap/summary via agent

**Thumbnail generation** (`package/thumbnails.py`):
- 5 candidates (center frame, 25%, 50%, 75%, 95% marks)
- 1280×720 JPG (YouTube standard)

---

## Error Handling

**Boundary-based strategy:**
- CLI input → typed error (suggest fix)
- File I/O → FileNotFoundError with path
- Render execution → RenderError with log tail (last 10 lines)
- Schema validation → ValidationError with field + reason

**No silent failures:** All errors propagate with context. Tests verify error cases.

---

## Testing

**155+ tests** covering:
- Schema validation (job_spec.py)
- Timeline building (timeline.py)
- Audio graph construction (audio_graph.py)
- Music loop preparation (music_loop.py)
- Subtitle alignment (align_script.py)
- Segmented render plan building
- Error propagation

**Test fixtures:**
- Minimal job.yaml examples
- Synthesized tone WAV (ffmpeg -f lavfi sine=...)
- Dummy PNG/JPG images
- No heavy downloads (CI-friendly)

---

## Concurrency & Resumability

### Inline Path
- Single FFmpeg process; no resumability (full re-render on failure)
- Suitable for <1h videos

### Segmented Path
- Each scene renders independently; clips cached on disk
- Resumable: restart at scene N if earlier clips done
- Suitable for 1h+ videos with many scenes

### Batch Rendering
- `videotool batch <job1.yaml> <job2.yaml> ...`
- ProcessPoolExecutor (not threaded, true parallelism)
- Workers limit (default 4, configurable via CLI)

---

## Git Organization

```
src/videotool/
├── core/              # Schema, timeline, validation, orchestration
├── render/            # FFmpeg commands, segmented, audio, music, parallax
├── ai/                # Whisper, transcription, alignment, subtitles
├── assets/            # License metadata, reports
├── package/           # YouTube output, thumbnails, descriptions
├── cli/               # Typer CLI wiring
└── gui/               # FastAPI thin shell (optional)

tests/
├── test_job_spec.py
├── test_timeline.py
├── test_audio_graph.py
├── test_music_loop.py
├── test_subtitles.py
└── ...

Colab/
├── v4_depthflow_clips_colab.py     # DepthFlow stills → clips
├── qi_wisps_overlay_colab.py       # GLSL qi-wisps generator
└── ...

scripts/
├── gen_overlay.py                  # Local overlay generators (fireflies, ember, dust)
└── generate-test-media.sh          # Tiny test fixtures
```

---

## Key Decisions (Do NOT Reverse)

1. **Schema-first:** JobSpec is single source of truth
2. **Inline ≤ 40 scenes, segmented >40:** Prevents O(n) filtergraph explosion
3. **Sidechain duck:** Automatic music pull-back under voice (not manual gain curves)
4. **Char-position subtitle alignment:** NOT whisper segment-start (robust)
5. **Tier full = single re-encode:** Burns all overlays at once (efficient)
6. **Mood independent of tier:** Tone customization available at all quality levels
7. **Atmosphere RGB blend:** NOT yuv420p (prevents magenta tint)
8. **B-roll interleave:** Never drop clips; spread by story order
9. **Parallax Colab offload:** GPU work outside job/local render loop

---

## Performance Profile

| Job Type | Input | Timeline | Render | Package | Total |
|----------|-------|----------|--------|---------|-------|
| Light 1h, 20 stills | 500MB | <1s | ~1h | <1min | ~1h |
| Full 1h, 20 stills | 500MB | <1s | ~2.5h | <1min | ~2.5h |
| Parallax 1h (Colab) | 500MB | <1s | ~30min | <1min | ~7h (Colab 6h + local 1h) |
| Shorts (9:16) parallel | 500MB | <1s | ~2h | <1min | ~2h (overlap with 16:9) |

**Hardware:** AMD Ryzen 5 7640HS (8 cores), 30GB RAM, SSD

---

## Next Steps

- Read [docs/code-standards.md](./code-standards.md) for Python conventions
- Read [docs/design-guidelines.md](./design-guidelines.md) for motion/loudness/timing details
- Read [CLAUDE.md](../CLAUDE.md) for full CLI reference + pitfalls

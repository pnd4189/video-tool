# Brainstorm — videotool feature expansion

Date: 2026-05-27. Status: design approved. Next: `/ck:plan --tdd` for P0.

## Problem statement

Extend the existing audio-first videotool (FFmpeg argv builder, CPU libx264, Pydantic JobSpec, Typer CLI)
to render long-form audio-story chapters end to end. Triggering case: chapter folder with 107-min TTS
narration, 114 scene images, 17 video clips, 3 music tracks, 1 cover image, and a polished script
(`translated_qa.txt`). Current tool cannot: time many images to audio, control per-track volume, scale
the filtergraph to 100+ inputs, or build subtitles from a known script.

## Requirements (captured, concrete)

- **Effects engine**: extend the existing FFmpeg filtergraph builder. No Remotion/MoviePy. AI-animate
  (DepthFlow/SVD) left as optional GPU/cloud module, out of scope.
- **Audio dB mixer (Capcut-like)**: independent `voice_gain_db` / `music_gain_db`, auto-duck on/off,
  keep final loudnorm -14 LUFS (toggleable).
- **Subtitle from script**: align provided `script.txt` to audio (approach A — whisper timestamps as the
  clock, overwrite text with the polished script). Reuse existing faster-whisper. No new dependency.
- **`/video-tool` slash command**: Claude skill parsing NL/flags after the command to orchestrate CLI workflows.
- **Web GUI**: FastAPI local app, "focused producer panel" (not a full NLE). Reuse `services.py` + `gui/queue.py`.
- Constraints: CPU-only, libx264, Python/Typer, files <200 lines, extend existing modules (no `_v2` copies).

## Decisions (from user)

| Topic | Decision |
|---|---|
| Effects engine | FFmpeg-native, extend current builder |
| GUI tech | FastAPI web app (browser, local) |
| GUI scope | Focused producer panel (no drag-track NLE) |
| Priority | P0 = storyboard auto + dB mixer (CLI) |
| Storyboard timing | Even split across audio duration, rotating motion/transition |
| dB model | Per-track dB + auto-duck on/off, keep loudnorm -14 |
| Subtitle approach | A — whisper timestamps + script text overwrite |
| Plan mode | `/ck:plan --tdd` |

## Approaches evaluated

- **Effects**: FFmpeg-native (chosen) vs MoviePy (redundant over FFmpeg) vs Remotion (2nd runtime, heavy).
  Reference docs (`hiệu ứng video.txt`, `tìm kiếm ... github ...md`) confirm FFmpeg overlay+filter is the
  correct CPU-only path; AI image-to-video needs GPU.
- **GUI**: web/FastAPI (chosen, reuses Python core, native video preview) vs PySide6 desktop (heavier) vs
  thin queue dashboard (not "visual" enough).
- **Subtitle**: A whisper-timestamp+script-overwrite (chosen) vs B aeneas forced aligner (robust but heavy
  espeak dep) vs C plain whisper (loses exact Hán-Việt wording).

## Final solution — phased

**P0 (next, --tdd):**
1. **dB mixer** — add `AudioSpec` to `core/job_spec.py` (`voice_gain_db`, `music_gain_db`, `duck`,
   `duck_strength`, `normalize_lufs`). In `render/commands.py` extract `_audio_graph()` helper (DRY across
   storyboard + single-bg paths), map dB via FFmpeg `volume={x}dB`, replace hardcoded `volume=0.5`, make
   sidechain duck optional. Note: loudnorm normalizes final level → dB sets balance, not absolute loudness.
2. **Storyboard auto-gen** — `core/storyboard_gen.py` + CLI `videotool storyboard JOB --images-dir DIR`.
   Probe voice duration, natural-sort images, even split (last absorbs remainder), rotate motion, default
   crossfade. Write `storyboard:` into job.yaml.
3. **Segmented render** — render each scene to an intermediate clip then `concat` demuxer + mux audio,
   instead of one 100+ input filtergraph. Robust, low-RAM, resumable. Touches `render/commands.py` +
   `render/executor.py`.
4. **Subtitle from script** — `ai/align_script.py`; extend `videotool transcribe JOB --script FILE`.
   Whisper for timestamps, overwrite with script sentences, re-anchor periodically, cue split ≤2 lines /
   ~42 chars (reuse `subtitles.py`). Add `inputs.script: Path | None` to JobSpec. Write `outputs/captions.srt`.

**P1 — effects engine**: `render/effects.py` registry. Overlay group (snow/rain/fog/dust/light-leak via
`colorkey`/`blend=screen` on black-bg loops) + filter group (`noise` grain, `vignette`, `gblur`, `fade`,
`eq/curves` color grade, camera-shake). Global + per-scene `effects` in JobSpec. Overlay assets follow
existing license policy.

**P2 — `/video-tool` skill**: `~/.claude/skills/video-tool/SKILL.md`. NL/flags → orchestrate
init → storyboard → transcribe → render → package.

**P3 — Web GUI**: FastAPI reusing `services.py`; SSE render-log stream from `RenderExecutor`; serve preview
mp4; reuse `gui/queue.py`. Frontend panels: job builder, dB mixer (sliders + duck toggle), storyboard table
(thumb/duration/motion/transition/effects, editable), effects picker, render+log+preview. `videotool gui` launches.

## Risks

1. **(HIGH) 100+ input filtergraph won't scale** — current builder loads all images at once (`-loop 1 -i`
   ×N) + N-way xfade chain. For 114 scenes → huge RAM, fragile, non-resumable. Mitigation: segmented render
   in P0 (mandatory, not optional).
2. 107-min libx264 ≈ real-time render. Mitigation: `libx264-fast` + existing `batch` parallelism.
3. Even-split storyboard feels static. Mitigation: motion variety + manual edit / effects (P1).
4. dB vs loudnorm confusion. Mitigation: document + GUI tooltip; `normalize_lufs: null` for absolute dB.
5. Subtitle drift over 107 min (approach A). Mitigation: periodic re-anchor; aeneas (B) as fallback upgrade.

## Acceptance criteria (P0)

- `videotool storyboard Chap1/job.yaml --images-dir Image` writes 114 scenes, total ≈ 6425s.
- `audio.*` gains change voice/music balance (verify by LUFS probe); duck toggles correctly.
- `videotool transcribe Chap1/job.yaml --script ...translated_qa.txt` writes `outputs/captions.srt` using
  exact script wording, monotonic timestamps, validates clean.
- `videotool render` of that chapter completes via segmented path → `outputs/youtube-16x9.mp4` matching
  audio length.
- 43 existing tests stay green + new tests for dB mapping, storyboard gen, script alignment.

## Out of scope (this round)

P1/P2/P3 implementation; AI image-to-video; full NLE timeline; channel banner (one-time YouTube Studio,
not a per-video concern); thumbnail text compositing (tool only extracts candidate stills — use cover image
manually or as scene 1).

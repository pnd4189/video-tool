# Codebase Summary

Audio-first YouTube video tool. Wraps FFmpeg + Whisper to render `voice + media + music + captions` into long-form `youtube-16x9.mp4` and `shorts-9x16.mp4`. CPU-only encode (libx264), no iGPU dependency.

## Layout

```
src/videotool/
├── cli/            # Typer CLI (entry: videotool.cli.main:app)
│   ├── main.py            # command wiring
│   └── commands.py        # doctor / validate / probe / render / batch / transcribe / analyze-audio / package / benchmark
├── core/
│   ├── job_spec.py        # Pydantic schemas (JobSpec, ChapterSpec, ProjectSpec, ...)
│   ├── timeline.py        # JobSpec → Timeline (the planning IR)
│   ├── services.py        # orchestrator: validate→stage→build_plans→execute→package
│   ├── media_probe.py     # ffprobe wrapper
│   ├── validation.py      # path & job sanity checks
│   ├── errors.py          # typed exceptions (ValidationError, RenderError, DependencyError, LicensePolicyError)
│   └── logging.py         # rich console
├── render/
│   ├── commands.py        # Timeline → ffmpeg argv (sidechain duck, loudnorm I=-14, escape, metadata)
│   ├── music_loop.py      # prepare_seamless_music(): pre-render music to target duration with acrossfade
│   ├── executor.py        # Popen streaming + 6h timeout + SIGTERM
│   ├── profiles.py        # libx264-balanced | libx264-fast (VAAPI removed)
│   └── workspace.py       # <job>/<temp_dir> staging
├── ai/
│   ├── transcribe.py              # TranscriptResult / TranscriptSegment
│   ├── faster_whisper_adapter.py  # primary STT
│   ├── whisper_cpp_adapter.py     # fallback
│   ├── subtitles.py               # SRT writer + CRLF-tolerant validator
│   └── silence.py                 # detect_silence + cut suggestions
├── assets/
│   ├── library.py         # asset-index.yaml loader (Pydantic)
│   ├── licenses.py        # licensed-only policy enforcement
│   └── reports.py         # license-report.md writer
├── package/
│   ├── youtube.py         # validate_package + write_description (chapters/tags/cta) + LUFS measure
│   ├── thumbnails.py      # generate_thumbnail_candidates (5 stills)
│   ├── manifest.py        # package-manifest.json
│   └── reports.py         # quality-report.json
└── gui/
    └── queue.py           # minimal job queue shell
```

## Render flow

1. `services.run_validate` → schema + asset license policy
2. `services.run_render`:
   - `Workspace.prepare()` → `<job>/<temp_dir>/`
   - `_stage_subtitle()` → copy `outputs/captions.srt` into workspace (short ASCII path; ffmpeg `subtitles=` is fragile)
   - `_stage_music()` → `prepare_seamless_music()` produces `music-loop.flac` matching voice duration exactly
   - `build_render_plans()` compiles a `Timeline` → `CommandPlan` per output (16x9 + 9x16)
   - `RenderExecutor.run()` streams ffmpeg output to `<job>/<temp_dir>/logs/<preset>.log`
3. `services.run_package` writes license report, description, 5 thumbnails, quality report, manifest

## Audio chain (in `render/commands.py`)

```
voice → atempo? → asplit ──┬──> [voice_main] ─┐
                           └──> [voice_key]  │
                                              ▼
music(loop) ──────────────► sidechaincompress(key=voice_key) ──► [duck]
                                                                  │
                            [voice_main] + [duck] ──► amix ──► loudnorm I=-14:TP=-1:LRA=11 ──► output
```

`sidechaincompress=threshold=0.05:ratio=8:attack=5:release=400:makeup=2` — ducks music automatically when voice is present.

## Music seamless loop

`prepare_seamless_music(music_path, target_duration, workspace_root)`:
- If `music_duration >= target`: trim with `afade=t=out`
- Else: chain N copies via `acrossfade=d=2:curve1=tri:curve2=tri`, then `atrim + afade=t=out`
- Cap: `MAX_PLAYS=200` (raises `RenderError` beyond — user must use a longer music track)
- Output: FLAC (lossless intermediate) at `<workspace>/music-loop.flac`
- The main render's `-stream_loop -1` on this prepared file is a no-op (output length already matches)

## Testing

- 43 tests, all pass via `.venv/bin/python -m pytest`
- Music loop tests synthesize tones with `ffmpeg -f lavfi sine=...` so no fixtures needed
- End-to-end render verified on `fixtures/generated/` (voice 3s + music 1.04s → prepared 3.0s + 1080p outputs)

## Hardware notes

- AMD Ryzen 5 7640HS w/ Radeon 760M, 30GB RAM, 1GB VRAM
- Encode runs 100% on CPU (libx264) — iGPU VRAM allocation is irrelevant
- A ~1h video at 1080p libx264 medium takes ~real-time on this CPU

# Codebase Summary

Audio-first YouTube video tool. Wraps FFmpeg + Whisper to render `voice + media + music + captions` into long-form `youtube-16x9.mp4` and `shorts-9x16.mp4`. CPU-only encode (libx264), no iGPU dependency.

## Layout

```
src/videotool/
├── cli/            # Typer CLI (entry: videotool.cli.main:app)
│   ├── main.py            # command wiring
│   ├── commands.py        # doctor / validate / probe / render / batch / transcribe / analyze-audio / package / benchmark
│   └── storyboard_commands.py  # storyboard plan (prompt-driven) + storyboard auto (even-split)
├── core/
│   ├── job_spec.py        # Pydantic schemas (JobSpec, AudioSpec, RenderSpec, ProjectSpec, ...)
│   ├── timeline.py        # JobSpec → Timeline (the planning IR; carries audio dB/duck/loudnorm)
│   ├── storyboard.py      # prompt parser + auto-gen (discover_scene_images, build_even_split_storyboard)
│   ├── services.py        # orchestrator: validate→stage→build_plans→execute→package
│   ├── media_probe.py     # ffprobe wrapper
│   ├── validation.py      # path & job sanity checks (voice/media/music/script)
│   ├── errors.py          # typed exceptions (ValidationError, RenderError, DependencyError, LicensePolicyError)
│   └── logging.py         # rich console
├── render/
│   ├── commands.py        # Timeline → ffmpeg argv (inline path: single filtergraph, xfade storyboard)
│   ├── segmented.py       # clip-per-scene + concat demuxer + audio-mux pass (resumable, long boards)
│   ├── audio_graph.py     # build_audio_graph(): dB gains, sidechain duck, loudnorm — shared by both paths
│   ├── video_filters.py   # shared scene/zoompan/codec/metadata helpers
│   ├── music_loop.py      # prepare_seamless_music(): concat+loop a track list to target duration with acrossfade
│   ├── executor.py        # Popen streaming + 6h timeout + SIGTERM; run() + run_segmented()
│   ├── profiles.py        # libx264-balanced | libx264-fast (VAAPI removed)
│   └── workspace.py       # <job>/<temp_dir> staging
├── ai/
│   ├── transcribe.py              # TranscriptResult / TranscriptSegment
│   ├── faster_whisper_adapter.py  # primary STT
│   ├── whisper_cpp_adapter.py     # fallback
│   ├── align_script.py            # parse_script + align_script_to_transcript (script wording on whisper timing)
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
    ├── app.py             # FastAPI app factory (videotool gui)
    ├── web_app.py / state.py / queue.py  # job queue shell + state
    └── static/ templates/
```

## CLI surface

`doctor`, `init-job`, `validate`, `probe`, `render` (`--dry-run`, `--preset`, `--all`),
`batch`, `transcribe` (`--model`, `--script`), `analyze-audio`, `package`, `benchmark`,
`gui`, and the `storyboard` group: `storyboard plan` (prompt-driven) and
`storyboard auto JOB --images-dir DIR` (even-split a folder of images across the voice).

## Render flow

1. `services.run_validate` → schema + asset license policy
2. `services.run_render`:
   - `Workspace.prepare()` → `<job>/<temp_dir>/`
   - `_stage_subtitle()` → copy `outputs/captions.srt` into workspace (short ASCII path; ffmpeg `subtitles=` is fragile)
   - `_stage_music()` → `prepare_seamless_music()` produces `music-loop.flac` covering the full
     video (voice plus any ending-image extension); a music *directory* concatenates all tracks
   - Routing by scene count vs `render.max_inline_scenes` (default 40):
     - **inline** (≤ threshold): `build_render_plans()` → one `CommandPlan` per output; single
       filtergraph with xfade transitions. `RenderExecutor.run()` streams to `logs/<preset>.log`.
     - **segmented** (> threshold): `build_segmented_plans()` → one `SegmentedPlan` per output;
       each scene renders to `clips/<preset>/scene-NNNN.mp4`, joined by the concat demuxer with a
       final audio-mux pass. `RenderExecutor.run_segmented()` skips clips already on disk
       (resumable) and logs per scene + mux. Segment seams are hard cuts softened by a per-clip
       fade; true N-way crossfade across segments is deferred.
3. `services.run_package` writes license report, description, 5 thumbnails, quality report, manifest

## Subtitle from script (`transcribe --script`)

Whisper provides the *timing*; the script provides the *wording*. `ai/align_script.parse_script`
splits prose into sentence cues, and `align_script_to_transcript` re-times them onto the whisper
segment spans (proportional to character length, monotonic, bounded by the span). Without
`--script`, plain whisper SRT is written. The script path can also be set via `inputs.script`.

## Audio chain (`render/audio_graph.build_audio_graph`, shared by inline + segmented)

Configured via the job's `audio:` block (`AudioSpec`): `voice_gain_db` (default 0),
`music_gain_db` (default -28.0, a quiet bed that never competes with narration), `duck`
(default true), `normalize_lufs` (default -14.0; `null` drops the final loudnorm and makes dB
gains absolute). When scenes run past the voice (an ending image), `compile_timeline` sets
`voice_pad_seconds` and the voice chain gets `apad=pad_dur=N` so `-shortest` keeps the outro.

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

`prepare_seamless_music(music_paths, target_duration, workspace_root)`:
- Takes an ordered list of tracks. `_stage_music` expands a music *directory* to all audio files,
  natural-sorted (`01-`, `02-`); a single file is a one-element list.
- Single track ≥ target: trim with `afade=t=out`.
- Otherwise: cycle the tracks (`_build_sequence`) until they cover the target, normalize each
  segment (`aresample=48000,aformat=channel_layouts=stereo`), chain via
  `acrossfade=d=2:curve1=tri:curve2=tri`, then `atrim + afade=t=out`.
- Cap: `MAX_PLAYS=200` segments (raises `RenderError` beyond — use longer tracks).
- Output: FLAC (lossless intermediate) at `<workspace>/music-loop.flac`.
- The main render's `-stream_loop -1` on this prepared file is a no-op (output length already matches).

## Testing

- 73 tests, all pass via `.venv/bin/python -m pytest`
- Music loop tests synthesize tones with `ffmpeg -f lavfi sine=...` so no fixtures needed
- End-to-end render verified on `fixtures/generated/` (voice 3s + music 1.04s → prepared 3.0s + 1080p outputs)

## Hardware notes

- AMD Ryzen 5 7640HS w/ Radeon 760M, 30GB RAM, 1GB VRAM
- Encode runs 100% on CPU (libx264) — iGPU VRAM allocation is irrelevant
- A ~1h video at 1080p libx264 medium takes ~real-time on this CPU

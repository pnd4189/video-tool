---
phase: 3
title: "Full-tier overlay filtergraph"
status: done
priority: P2
effort: "1-2d"
dependencies: [1, 2]
---

# Phase 3: Full-tier overlay filtergraph

## Overview
The core change. When `enhance_tier == "full"`, build a single video overlay filtergraph applied at the segmented mux (drop `-c:v copy` → re-encode) and on the inline path, layering: burned subtitles → particle/grain → progress/chapter bar → optional `showwaves` visualizer. tier light is untouched.

## Requirements
- Functional (tier full): final video carries burned subtitles (when SRT present), a looping particle/grain layer, a bottom progress bar, and — when `visualizer` on — a waveform strip keyed off the voice.
- Functional (tier light): mux still `-c:v copy`; no overlay. Locked by Phase 1 test.
- Non-functional: one re-encode pass at mux (not per-clip); reuse `codec_args(profile)`; keep the new module < 200 lines.

## Architecture
- New `render/overlay_graph.py`: pure builder `build_video_overlay(label_in, label_out, timeline, output, *, particle_input_idx, audio_label) -> str`. Composes, in order, only the enabled layers:
  1. **subtitles** — reuse `commands._caption_filter(timeline, output)` (already styled); skip if no SRT / `caption_mode != srt-and-burn`.
  2. **particle/grain** — `overlay` a looping particle input with `blend=screen` (or `colorchannelmixer`/`addition`), then light `noise`/`vignette`. Particle source resolved in Phase 4 (procedural ffmpeg or `inputs.particle_overlay`).
  3. **progress bar** — `drawbox` thin bar at bottom whose width scales with `t/duration` via `w=iw*t/{dur}`; optional `drawtext` chapter label.
  4. **visualizer** (optional) — `showwaves`/`showcqt` from the voice audio label → `overlay` into a corner. Gated by `is_on("visualizer")`.
- `segmented._build_mux_command`: branch on `timeline.enhance_tier`.
  - light → unchanged (`-c:v copy`).
  - full → add particle input after audio inputs; replace copy with `-filter_complex "[0:v]<overlay chain>[v]"`, `-map "[v]"` + existing `[aout]`/audio map, then `codec_args(profile)`. Audio graph untouched.
- Inline path lives in `render/commands.py` (verified: `_caption_filter` composed at `commands.py:44-46` single-bg and `:84-86` storyboard). Inject the same `build_video_overlay` there after the existing scene/caption graph when tier full (particle/progress/visualizer were not there before; subtitles already were). `ffmpeg_graph.py` does not handle captions — do not target it.

<!-- Updated: Validation Session 1 - subtitle style = SRT sentence-level burn (reuse _caption_filter); no ASS/word-kinetic in this plan -->
- **Subtitle style (confirmed):** sentence-level SRT burn via existing `_caption_filter`. No ASS/karaoke word-highlight — that needs word-level whisper timestamps `align_script` does not produce; deferred to a future plan if needed.
- `services.run_render`: for tier full, force `caption_mode` effective = `srt-and-burn` and ensure `_stage_subtitle` runs (stage the Phase-2 SRT). Keep light behavior unchanged.

## Related Code Files
- Create: `src/videotool/render/overlay_graph.py`
- Modify: `src/videotool/render/segmented.py` (`_build_mux_command` tier branch + particle input)
- Modify: `src/videotool/render/ffmpeg_graph.py` (inline tier-full overlay injection)
- Modify: `src/videotool/render/commands.py` (expose `_caption_filter` for reuse; no style change)
- Modify: `src/videotool/core/services.py` (tier-full → stage SRT + caption on)
- Create: `tests/test_overlay_graph.py`
- Modify: `tests/test_segmented_render.py` (tier-full mux assertions)

## Implementation Steps
1. **Test first:** in `test_overlay_graph.py`, assert `build_video_overlay` for a full-tier timeline emits, in order, `subtitles=`, a particle `overlay`/`blend`, `drawbox`, and (visualizer on) `showwaves`; and emits an empty/passthrough chain when all layers off.
2. **Test first:** in `test_segmented_render.py`, full-tier `mux_command` **omits** `-c:v copy`, contains `-filter_complex` with `-map "[v]"`, includes the particle input; light-tier unchanged (existing assertions stay green).
3. Implement `overlay_graph.py` builder (layers conditional, single chain, labels threaded).
4. Wire `segmented._build_mux_command` tier branch (input indices: concat=0, voice=1, music=2?, particle=next). Recompute audio input indices carefully when particle added.
5. Wire inline path injection + `services` tier-full caption staging.
6. Run suite; `dry-run` a full-tier job and eyeball the command. Real render verified in Phase 4.

## Success Criteria
- [x] tier-full mux re-encodes (no `-c:v copy`), single `-filter_complex`, `-map [v]`
- [x] overlay chain order = subtitles → particle/grain → progress bar → visualizer, each conditional
- [x] tier-light commands unchanged (Phase 1 lock still green)
- [x] audio mapping/indices correct with particle input added (duck/loudnorm intact)
- [x] `overlay_graph.py` < 200 lines

## Implementation Notes (done 2026-05-31)
- Added `render/overlay_graph.py` (100 lines) with a pure overlay builder and shared caption filter escaping.
- Wired full-tier segmented mux to add a particle lavfi input, build a combined video/audio filtergraph, map `[v]` + `[aout]`, and re-encode with `codec_args(profile)`; light tier still uses `-c:v copy`.
- Wired full-tier inline/single-background commands to use the same overlay builder. Existing subtitle-only light behavior remains through the shared caption filter.
- Full tier now treats subtitles as burn-in at timeline compile time and requires/stages `outputs/captions.srt` when `enhance.subtitles` resolves on.
- Visualizer overlay uses `eof_action=pass` so ending-image/outro scenes are not truncated when the waveform audio stream ends before the padded video.
- Verified with targeted tests, full suite (`95 passed`), and a CLI dry-run full-tier command. Real mp4 smoke render and bundled particle assets remain Phase 4.

## Risk Assessment
- Risk: input-index off-by-one when particle stream added shifts music/voice maps → broken audio. Mitigation: centralize index assignment; assert in test; duck still keys off voice label.
- Risk: `showwaves` needs the audio decoded in the video graph (extra `[1:a]` split) → graph complexity. Mitigation: make visualizer default OFF; ship subtitles+particle+bar first, visualizer behind override.
- Risk: re-encode at mux loses the resumability benefit of segmented copy. Mitigation: clips still cached/resumable; only the final mux re-encodes — documented as the accepted ~2x cost.
- Risk: particle `blend` over yuv420p needs format hops. Mitigation: insert `format` guards; verify in Phase 4 smoke.

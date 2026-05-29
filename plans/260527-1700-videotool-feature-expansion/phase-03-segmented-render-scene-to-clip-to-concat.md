---
phase: 3
title: "Segmented render (scene to clip to concat)"
status: done
priority: P1
effort: "1-2d"
dependencies: [1, 2]
---

# Phase 3: Segmented render (scene to clip to concat)

## Overview

The current `_build_storyboard_command` loads every scene as a simultaneous
`-loop 1 -t -i` input plus an N-way xfade chain. At 114 scenes that filtergraph
is huge, RAM-heavy, fragile, and non-resumable (HIGH risk in brainstorm). Add a
segmented path: render each scene to its own intermediate clip, then join with
the FFmpeg `concat` demuxer and mux audio in a final pass. Resumable (skip clips
already on disk), low-RAM, scales to 100+ scenes.

Keep the existing inline xfade path for small storyboards (preserves crossfade +
existing tests); route to segmented only when scene count exceeds a threshold.

## Requirements

- Functional:
  - New `build_segmented_render(timeline, profile, output)` returning a
    `SegmentedPlan`: ordered per-scene clip commands (video only, zoompan/scale
    via the existing `_scene_filter`), a concat-list file path + contents, and a
    final mux command (concat demuxer video + `_audio_graph()` audio from Phase 1
    + metadata + codec + faststart).
  - Routing threshold is **configurable per job**: add
    `render.max_inline_scenes: int = 40` to `RenderSpec` (job.yaml). `services`
    routes to segmented when `len(timeline.scenes) > max_inline_scenes`; else
    keep the current single-command inline path unchanged. Thread the value onto
    `Timeline` (or pass through from the loaded job).
  - `RenderExecutor.run_segmented(plan, log_dir)`: render each missing scene clip
    (skip if the clip file already exists → resumable), write the concat list,
    run the final mux. Reuse existing log/stream/timeout handling.
  - Segment boundaries are hard cuts (concat demuxer), with a short per-clip
    `fade` in/out to soften them. True N-way crossfade across the segmented path
    is explicitly deferred (documented).
- Non-functional: clips + concat list live under the job's render `temp_dir`
  workspace; `commands.py`/`executor.py` stay <200 lines (extract a small
  `render/segmented.py` if needed — distinct concern, not a `_v2`).

## Architecture

- `render/commands.py` (or new `render/segmented.py` if size forces it):
  - `@dataclass(frozen=True) SegmentedPlan`: `scene_commands: list[CommandPlan]`,
    `concat_list_path: Path`, `concat_list_text: str`, `mux_command: list[str]`,
    `output_path: Path`, `preset: str`.
  - Per-scene clip command: single image input + `_scene_filter`-derived vf
    (without the xfade join), `-t duration`, libx264, no audio, write to
    `temp_dir/clips/scene-{idx:04}.mp4`.
  - Final mux: `ffmpeg -f concat -safe 0 -i concat.txt -i voice [-i music]
    -filter_complex {_audio_graph(...)} -map 0:v:0 -map [aout] … faststart`.
    Concat list = `file '<abs clip path>'` lines in order.
- `render/executor.py`: `run_segmented` loops `scene_commands` (skip when
  `output_path.exists()` and non-empty), writes `concat_list_text` to
  `concat_list_path`, then runs `mux_command`. One log file per phase under
  `workspace.logs_dir`.
- `core/services.py`: in `run_render`, choose segmented vs inline by scene count;
  call `executor.run_segmented(...)` for the segmented `SegmentedPlan`. `dry_run`
  returns the plan (scene commands + mux command) without executing.

## Related Code Files

- Modify: `src/videotool/render/commands.py` (+ maybe new `src/videotool/render/segmented.py`)
- Modify: `src/videotool/render/executor.py` (`run_segmented`)
- Modify: `src/videotool/core/services.py` (routing in build_render_plans/run_render)
- Modify: `src/videotool/core/job_spec.py` (`RenderSpec.max_inline_scenes: int = 40`)
- Modify: `src/videotool/core/timeline.py` (thread `max_inline_scenes` onto Timeline)
- Create: `tests/test_segmented_render.py`

## Implementation Steps

1. **TDD lock (green first)**: assert the existing small-storyboard path is
   unchanged — a 2-3 scene timeline still produces ONE command containing
   `xfade` (today's `test_ffmpeg_commands.py` storyboard expectations). This
   guards the routing threshold.
2. **TDD new (red)** in `tests/test_segmented_render.py`:
   - A timeline with scenes > threshold → `build_segmented_render` returns N
     scene commands + 1 mux command.
   - Each scene command is image→clip, video-only, has `-t {duration}` and writes
     a distinct `clips/scene-NNNN.mp4`.
   - `concat_list_text` lists all N clips in order, each as `file '…'`.
   - Mux command contains `-f concat`, `loudnorm`/`sidechaincompress` via
     `_audio_graph()` (respects Phase 1 dB/duck/loudnorm), and `-metadata title=`.
   - Routing: `run_render(..., dry_run=True)` on a >threshold timeline returns a
     segmented plan; on a small timeline returns the single inline command.
   - Resumability: `run_segmented` skips a scene whose clip file already exists
     (assert the skipped scene's command is not executed — use a fake/stub
     executor or check via a recorded-commands seam).
3. Implement `SegmentedPlan` + `build_segmented_render` reusing `_scene_filter`
   and `_audio_graph`.
4. Implement `RenderExecutor.run_segmented`.
5. Add routing in `services.py`.
6. Full suite green. Check file sizes; extract `render/segmented.py` if needed.

## Success Criteria

- [ ] `videotool render Chap1/job.yaml --dry-run` on the 114-scene job returns a
      segmented plan (114 clip commands + 1 mux), not a single mega-filtergraph.
- [ ] Small storyboards still render via the inline xfade path (existing tests green).
- [ ] Re-running render skips already-rendered scene clips (resumable).
- [ ] Final video audio honors Phase 1 dB/duck/loudnorm settings.

## Risk Assessment

- No true crossfade across segments (concat demuxer joins hard cuts) — accepted
  for P0; soft per-clip fade mitigates; xfade path remains for small boards.
  Revisit (pairwise-xfade segmented) in a later round if needed.
- Clip codec params must match for concat demuxer (same preset/fps/pix_fmt/res) —
  enforce identical `_codec_args` + scale/fps in every scene command.
- 107-min libx264 ≈ real-time; `libx264-fast` + `batch` parallelism mitigate.
  Resumability means a crash mid-run does not restart from scene 1.

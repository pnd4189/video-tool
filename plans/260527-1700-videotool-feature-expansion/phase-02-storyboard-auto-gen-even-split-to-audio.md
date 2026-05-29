---
phase: 2
title: "Storyboard auto-gen (even-split to audio)"
status: pending
priority: P1
effort: "0.5-1d"
dependencies: []
---

# Phase 2: Storyboard auto-gen (even-split to audio)

## Overview

Generate a complete `storyboard:` block from an images folder + the voice
duration, with no prompt files. Natural-sort the image folder, split the voice
duration evenly across N images (last scene absorbs the rounding remainder),
rotate motion for variety, default transition `crossfade`. Writes scenes into an
existing `job.yaml`. This is what produces the 114-scene timeline that Phase 3
must render.

User decisions locked: **natural-sort the `Image/` folder, ignore prompt files**;
**even split across audio duration, rotating motion/transition**.

## Requirements

- Functional:
  - Discover images in a dir by extension (`.png/.jpg/.jpeg/.webp`), natural-sorted
    so `scene_2` < `scene_10`. **Naming-agnostic**: works for ANY image filenames
    (`scene_001_4K.jpg`, `001.png`, `frame-12.jpeg`, …) — sort by the numeric runs
    in whatever names exist; never assume a `scene_`/`_4K`/`scene-NNN.png` pattern.
    Image count and durations come from the folder + probed audio, never hardcoded.
  - Even split: `each = total/N`; scenes 1..N-1 = `each`, scene N = remainder so
    `sum == voice_duration` exactly (within float tolerance).
  - Rotate motion through a fixed cycle (e.g. `slow-push, zoom-in, pan-right,
    zoom-out, pan-left`); transition default `crossfade`.
  - CLI `videotool storyboard auto JOB --images-dir DIR` probes the job's voice
    duration, builds scenes, writes them into the existing `job.yaml` (load,
    set `storyboard`, dump) — preserving other keys.
  - If `job.yaml` already has a `storyboard` block, **overwrite it and print a
    warning** naming the old scene count being replaced (user decision). No
    `--force` gate; the warning is the safeguard.
- Non-functional: extend `core/storyboard.py` (keep <200 lines; if it would
  exceed, split the even-split helpers into a focused `core/storyboard_autogen.py`
  — a distinct concern, not a `_v2` copy). Reuse `StoryboardSceneSpec` shape so
  the result validates against `JobSpec`.

## Architecture

- `core/storyboard.py` additions:
  - `natural_sort_key(name: str) -> list` — split digit runs to ints.
  - `discover_scene_images(image_dir: Path) -> list[Path]` — glob image
    extensions, natural-sorted.
  - `build_even_split_storyboard(image_dir, voice_duration, *, motions=MOTION_CYCLE,
    transition="crossfade") -> list[dict]` — returns scene dicts ready for
    `job.yaml` (`scene`, `image`, `duration`, `motion`, `transition`). Image path
    written relative to the job dir.
- `cli/storyboard_commands.py`: new `auto_storyboard(job_path, images_dir)` —
  `load_job`, `probe_media(voice).duration`, build scenes, set
  `job.yaml["storyboard"]`, re-dump preserving key order. Validate via
  `JobSpec.model_validate` before writing.
- `cli/main.py`: `@storyboard_app.command("auto")` calling the new function
  (mirror the existing `storyboard plan` wiring).

## Related Code Files

- Modify: `src/videotool/core/storyboard.py`
- Modify: `src/videotool/cli/storyboard_commands.py`
- Modify: `src/videotool/cli/main.py`
- Create: `tests/test_storyboard_autogen.py`

## Implementation Steps

1. **TDD (red)** in `tests/test_storyboard_autogen.py`:
   - natural sort: `[scene_10.jpg, scene_2.jpg, scene_1.jpg]` →
     `[scene_1, scene_2, scene_10]`.
   - even split: 3 images, `voice_duration=10.0` → durations `[3.333, 3.333,
     3.334]` (last absorbs remainder); `sum == 10.0`.
   - motion rotation cycles and repeats for N > cycle length.
   - CLI `storyboard auto` on a temp job + temp image dir writes job.yaml whose
     `storyboard` has N scenes, durations summing ≈ voice duration, paths
     relative to job dir, and re-validates as a `JobSpec`.
2. Implement `natural_sort_key`, `discover_scene_images`,
   `build_even_split_storyboard` in `storyboard.py`.
3. Implement `auto_storyboard` in `storyboard_commands.py`; wire `storyboard auto`
   in `main.py`.
4. Run suite; green. Verify `storyboard.py` < 200 lines (else extract autogen
   helpers to `core/storyboard_autogen.py` and re-point imports).

## Success Criteria

- [ ] `videotool storyboard auto Chap1/job.yaml --images-dir Image` writes ~114
      scenes whose durations sum to the probed voice duration (≈ 6425s).
- [ ] Natural sort places `scene_2` before `scene_10`; non-`scene-NNN.png` names work.
- [ ] Existing `test_storyboard.py` (prompt-file path) stays green — auto-gen is
      additive, does not touch `build_storyboard` / `select_effects` / `find_scene_media`.
- [ ] Generated `storyboard` re-validates as a `JobSpec`.

## Risk Assessment

- Even-split feels static over 107 min → mitigated by motion rotation now;
  effects engine + manual edit deferred to the older plan's P1.
- File-size pressure on `storyboard.py` → fallback split documented above.
- `probe_media` needs ffprobe; CLI test should build scenes from a passed
  duration (unit) and only smoke-test the CLI path with a stubbed/short audio to
  avoid a hard ffprobe dependency in CI.

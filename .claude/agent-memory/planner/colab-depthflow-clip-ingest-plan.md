---
name: colab-depthflow-clip-ingest-plan
description: Isolated Colab-DepthFlow 2.5D clip ingest feature — parallax-link data-layer swap, distinct from numpy enhance.parallax
metadata:
  type: project
---

Feature (GH-2, branch feat/parallax-2-5d): Colab DepthFlow GPU renders one loopable 1080p 2.5D
clip per still → user manually uploads to `<job>/Parallax/<image-stem>.mp4` → local CLI
`videotool parallax-link <job> --clips-dir Parallax` swaps image scenes → matching clips at the
DATA layer (rewrites job.yaml storyboard), missing → Ken Burns. `/parallax-video` orchestrates.

**Why:** reuse Colab GPU for the expensive warp while keeping `/make-video` 100% untouched.

**How to apply:** This is a SEPARATE path from `enhance.parallax` / `parallaxize_timeline`
(numpy-local, in `render/parallax.py`) — do NOT conflate or modify that. The new path needs zero
render-code change because render already loop+trims a video scene (`commands.py:91`
`-stream_loop -1 -t`; `segmented.py:72`) and `StoryboardSceneSpec` already accepts image OR video
(`job_spec.py:79-80`). The data-layer swap mirrors `auto_storyboard`'s rewrite shape
(`storyboard_commands.py:64-95`, relativize via `_relative_or_original`).

Plan: `plans/260618-1628-GH-2-colab-depthflow-2-5d-clip-ingest/`. Project slash commands live at
`.claude/commands/*.md` (e.g. `make-video.md`) — NOT in `~/.claude/skills`.

---
name: parallax-video
description: "Local render of an audio-story episode with 2.5D parallax: same as make-video plus linking the pre-rendered DepthFlow clips in Parallax/. Use when the user asks for /parallax-video or a local render with the 'living photo' look."
argument-hint: "<folder> [hints: title, shorts, FX]"
---

# parallax-video

Follow `.agents/skills/make-video/SKILL.md` (local flow, Step 4b) with these differences only.
On Kaggle nothing differs: `enhance.parallax: true` in creative.yaml already links `Parallax/`.

- The clips are made OFF this machine (Colab `Colab/v4_depthflow_clips_colab.py`), one loopable
  clip per still, named `<image-stem>.mp4`, uploaded by the user into `<folder>/Parallax/`. This skill
  never generates clips.
- Stage `Parallax/` together with the other assets (`rclone copy`).
- After `storyboard auto`, run `videotool parallax-link "$JOB" --clips-dir Parallax`. It swaps each
  image scene for its clip; images without a clip stay Ken Burns. Note the swapped/missing counts.
- Do NOT set `enhance.parallax` (that is the slow on-box depth path; see
  `make-video/references/fx-parallax.md`).
- `Parallax/` missing or empty is not a blocker: warn "no parallax clips found — rendering stills as
  Ken Burns" and continue. A partial set (count ≠ `Image/`) → tell the user before rendering.
- Report how many scenes used a clip vs fell back to Ken Burns.

# FX (mood, atmosphere overlay) and parallax

Sources: memories `overlay-fx-library`, `overlay-hint-literal-family`, `melancholy-grain-bitrate-blowup`,
`parallax-video-full-fx-pitfalls`, `parallax-folder-always-check`, `parallax-2-5d-colab-versions`,
`render-speed-optimization-plan`; logs dao-si-chap16/22/28/32, chap52/54.

## Default: clean

No mood, no overlay unless the user's hint asks for FX (decision 2026-07-03). Never propose FX
unprompted.

## Overlay (`enhance.atmosphere` + `inputs.particle_overlay`)

- Library: `~/.local/share/videotool/overlays/` — families `rain- snow- fire- smoke- particles-
  dust- cosmos-` (CC0) and generated `fireflies-gen- ember-gen- dust-gen- qi-gen-`. `ls` it; do not
  rely on a list written here.
- **A hint naming a family is literal**: "overlay particles" = a `particles-*` file, not the channel's
  usual fireflies (dao-si-chap28). A hint naming a colour → measure the colour (below).
- **ASK-USER GATE:** propose ONE overlay in one line (file + why it fits the story) and WAIT for
  the user to confirm before rendering — unless the user said "không cần hỏi" / chose it already.
- Mood map as a starting point: melancholy→rain, winter/cozy→snow, action/horror→fire/smoke,
  rural night→fireflies-gen, talisman burning→ember-gen, mystical/qi→qi-gen/particles/cosmos/smoke,
  old film/abandoned→dust.
- Choosing without watching video: extract a frame (`ffmpeg -ss 3 -frames:v 1`), keep bright pixels,
  compute mean hue/saturation (purple ffc-46 = 270°, blue ffc-41 = 214°, the rest white), count
  bright specks, and frame-diff for motion. Mean luma (YAVG) cannot tell sparse particle clips apart.
- Kaggle: `enhance.overlay: <filename>` in creative.yaml; the box copies it into the job.
  Local: copy the file INTO the job folder and set `inputs.particle_overlay: <basename>` — a path
  outside the job fails validation with "Path escapes job folder".
- One overlay per video. Screen blends run in RGB (`gbrp`); never move them back to yuv420p
  (magenta tint).
- Cost: the blend is baked per scene in parallel since `788bb8c`. GPU + overlay is fine even at 3h
  (chap52); TPU does not slow down at all.

## Mood (`enhance.mood`)

`clean|melancholy|cozy|horror|action` expands to vignette/grain/glow/flicker/colour grade.
- Always `grain: false` — grain makes H264 incompressible (a 102-min render grew past 33 GB).
  creative.yaml's `apply_creative` already defaults grain off when a mood is set.
- With an overlay on, set `glow: false` (horror glow washes out fireflies; user preference 2026-06-24).

## Parallax — two different things

| | `Parallax/` folder + `parallax-link` | `enhance.parallax` on-box depth |
|---|---|---|
| Source | clips the user pre-renders on Colab (DepthFlow), one per image | DepthAnything + numpy warp at render time |
| Cost | free (data-layer swap) | ~3h15 for 109 images on the GPU box, not checkpointed |
| Use | always, when the folder exists | only with explicit user approval |

- The user's folders normally ship `Parallax/`. Before staging, count `Parallax/*.mp4` vs
  `Image/*` — they must match. Missing or short → **tell the user and ask**; do not enable on-box
  depth. The runner aborts in ~3 min when `enhance.parallax` is on and stills lack clips, unless
  creative.yaml has `enhance.parallax_on_box: true` (only after the user said yes).
- Kaggle creative: `enhance.parallax: true` with a full `Parallax/` → the runner links the clips,
  then turns `enhance.parallax` off so the intro/ending cards stay still ("enhance.parallax off" in
  the log is normal).
- Local: `/parallax-video` = `/make-video` + `videotool parallax-link "$JOB" --clips-dir Parallax`
  after the storyboard. Do not set `enhance.parallax` there.
- Clip filenames match image stems (`____SCENE_NNN_____N.mp4`). Do not trust folder names — verify
  content (grep chương in prompts, look at image 1): one Chap folder once held the wrong chapters.
  When renaming numbered files, extract the number with `grep -oE '[0-9]+$'` on the basename — `tr -dc
  0-9` also keeps the "4" of `.mp4`.

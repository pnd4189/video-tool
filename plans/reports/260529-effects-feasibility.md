# Effects feasibility (rain / wind / particles) — report only, deferred

Date: 2026-05-29. Context: item 6 of the make-video feature-adjustments round. The user asked
whether moving-image effects (rain, wind, drifting particles) are feasible without inflating
render time. Decision: report only this round; do NOT implement.

## Verdict: feasible, low marginal cost — defer implementation to a later round.

### Why it is cheap in the current architecture
- The segmented render path (used for 100+ scene audiobooks) already **encodes every scene clip
  individually** (`render/segmented.py:_build_scene_clip` runs `scene_filter` + fade through
  libx264). Adding an overlay filter to that existing encode is NOT an extra pass — it rides the
  encode already happening. Estimated cost: +10–20% CPU on the clip step, zero extra mux passes.
- The final mux stays `-c:v copy` (no re-encode), so the expensive part is untouched.
- The inline path (≤40 scenes) is a single filtergraph; an overlay is one more filter there too.

### Contrast with the rejected waveform overlay
The waveform/sound-wave overlay was rejected (`AGENTS.md`, decided 2026-05-28) because it must be
applied at the **mux** stage over the concatenated video, which forces re-encoding the whole
timeline (losing `-c:v copy`) → ~2x render time. Rain/wind do NOT have that problem because they
apply per-scene during the encode that already happens.

### Implementation candidates (for the future round)
1. **Looping overlay PNG sequence / transparent video** — most natural look. Overlay a tileable
   rain/snow clip with `overlay=...:shortest=0` + `loop`. Needs an asset (a rain loop). Best
   visual quality; adds one input + one `overlay` filter per clip.
2. **Procedurally generated** — `noise`/`fractal`/`geq` to fake drifting grain or light snow with
   no external asset. Cheapest (no extra input) but looks more synthetic.
3. **Subtle motion already exists** — zoompan (amplitude 0.30, pan 1.22) already defeats YouTube
   static detection, so effects are an aesthetic upgrade, not a functional need.

### Recommendation
Defer. If pursued: add an optional `effect: rain|snow|none` field on `StoryboardSceneSpec` (or a
job-level default), wire it into `scene_filter` so both render paths inherit it, gate it behind a
per-job opt-in, and benchmark a full chapter to confirm the <15% render-time budget. The `static`
intro/ending scenes should keep `effect: none` (designed frames).

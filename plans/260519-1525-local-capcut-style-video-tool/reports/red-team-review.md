---
title: "Red-Team Review"
status: final
created: "2026-05-19"
---

# Red-Team Review

## Findings

| Severity | Finding | Mitigation |
|---|---|---|
| High | Scope can silently grow into a CapCut clone. | V1 excludes full timeline UI, cloud, video background removal, and semantic B-roll search. |
| High | Asset downloads can cause YouTube copyright/Content ID issues. | Asset library requires license metadata and source attribution. YouTube Audio Library preferred for music/SFX. |
| High | FFmpeg graph complexity can become untestable string concatenation. | Build a typed timeline model and deterministic command builder; snapshot commands in tests. |
| Medium | VAAPI may be faster but lower quality or unstable per driver/profile. | CPU `libx264` default. VAAPI is opt-in after benchmark. |
| Medium | Offline Whisper can be slow on 16GB visible RAM. | Default to small/medium int8 models; one transcription job at a time; expose model setting. |
| Medium | GUI could duplicate CLI logic. | GUI calls the same job validation/render service. No separate business logic. |
| Medium | Long audio jobs can fill disk with temp media. | Plan temp workspace policy, cleanup, and disk-space preflight. |
| Low | Python module naming conflicts with global kebab-case preference. | Use Python-valid `snake_case` only inside importable modules; kebab-case elsewhere. |

## Rejected Ideas

- Embedding OpenShot/MLT in V1: too heavy for the target workflow.
- Remotion as required render layer: powerful, but pulls Node/React rendering into a Python-first tool.
- Full local AI stack in V1: too much install/runtime risk for the hardware.

## Whole-Plan Consistency Sweep

- Files expected: `plan.md`, `phase-01` through `phase-08`.
- Decision deltas checked: V1 scope, CPU default encoder, offline AI limits, CLI-first GUI-thin architecture.
- Unresolved contradictions at creation time: 0.

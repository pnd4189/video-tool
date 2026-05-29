# Validation Notes

## Summary

Validation pass checked the plan against the brainstorm report and current codebase. No blocking open questions remain for planning.

## Confirmed Requirements

- Expected output: `job.yaml` plus `outputs/youtube-16x9.mp4`, `captions.srt`, thumbnail, description, quality report, manifest.
- Acceptance: one command processes a Chap-style folder; video-marked scenes use video; image scenes move; audio is ducked/normalized; package artifacts exist.
- Scope: no CapCut, no cinematic effects, no Shorts first, no AI image-to-video, no monetization guarantee.
- Constraints: local Python/FFmpeg stack, deterministic mapping, no automatic network/model downloads.
- Touchpoints: CLI, job schema, storyboard import, timeline compile, segmented render, thumbnail/package, docs/tests.

## Validation Questions And Answers

1. **Should first pass render Shorts?**
   - No. Long-form YouTube 16:9 first. Shorts deferred.

2. **Should subtitles be burned into video?**
   - No. SRT-only by default for speed and simplicity.

3. **Can the command promise SRT without Whisper model?**
   - No. It can use existing SRT or run transcription only when model path is provided.

4. **Should mưa/gió effects be implemented now?**
   - No. Existing image motion + available videos is enough for MVP. Optional cheap overlays can come later.

5. **Should `StoryboardSceneSpec.image` be removed?**
   - No. Backward compatibility required. Add/normalize `media` only if tests protect old jobs.

## Remaining Assumptions

- Chap 1 folder shape is representative of future chapter folders.
- Existing 17 videos are already matched by scene number.
- Cover folder contains at least one usable image.
- CPU render speed is acceptable for first long-form output.

## Verdict

Plan is ready for implementation planning handoff. Recommended next command:

```bash
/ck:cook /home/dung/VIBE_CODING/video-tool/plans/260527-1635-audio-story-autopublisher-mvp/plan.md --tdd
```

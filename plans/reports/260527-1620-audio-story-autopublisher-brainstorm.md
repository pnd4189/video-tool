---
type: brainstorm-report
topic: audio-story-autopublisher
created: 2026-05-27 16:20
status: ready-for-plan
source_skill: ck:brainstorm
---

# Audio Story Autopublisher Brainstorm

## Summary

Recommended direction: build an **Audio Story Autopublisher** mode for `videotool`.

Goal is not cinematic video editing. Goal is one-command local production for long audio story uploads:

- voice is the product
- music bed supports voice
- thumbnail matters
- visuals only need enough motion/variation to avoid static/slideshow feel
- subtitles only need timing alignment, not beautiful typography
- no CapCut dependency

Best next implementation target:

```bash
videotool make-youtube "/path/to/Chap 1" --preset audio-story-fast
```

This should detect Chap folder inputs, create/update `job.yaml`, build video-aware storyboard, render long-form YouTube output, write SRT, pick cover thumbnail, and package upload artifacts.

## Codebase Context

Project type:

- Python package, CLI-first.
- `pyproject.toml` exposes `videotool = "videotool.cli.main:app"`.
- Core stack: Typer, Pydantic, PyYAML, Rich, FFmpeg.
- Encode is CPU-only `libx264`; no working GPU path.

Existing relevant modules:

- `src/videotool/cli/main.py` - command registration.
- `src/videotool/cli/commands.py` - command handlers.
- `src/videotool/cli/storyboard_commands.py` - `storyboard plan` and `storyboard auto`.
- `src/videotool/core/job_spec.py` - `JobSpec`, `StoryboardSceneSpec`, `AudioSpec`, `RenderSpec`.
- `src/videotool/core/storyboard.py` - prompt storyboard and even-split image storyboard.
- `src/videotool/core/services.py` - orchestration: validate, render, transcribe, package.
- `src/videotool/core/timeline.py` - `JobSpec` to render timeline.
- `src/videotool/render/video_filters.py` - image/video scene filter, zoompan motion.
- `src/videotool/render/segmented.py` - long storyboard render, clip-per-scene, concat, final audio mux.
- `src/videotool/render/audio_graph.py` - dB gain, ducking, loudnorm.
- `src/videotool/render/music_loop.py` - seamless music loop to voice duration.
- `src/videotool/package/thumbnails.py` - 5 thumbnail candidates from rendered video.
- `src/videotool/package/youtube.py` - package checks, LUFS measurement, description.

Current shipped capability:

- 66 tests pass from latest observed test run.
- Long storyboard path exists.
- Audio chain is strong enough for audio-story use: voice gain, music gain, sidechain duck, loudnorm target.
- Image motion exists via zoom/pan/ken-burns.
- Video paths can be rendered by `scene_filter` when storyboard media path points to video, though schema field is currently named `image`.
- Package step writes description, thumbnails, quality report, manifest.

Constraints discovered:

- Current `README.md` still describes older CLI surface. It is stale versus `docs/codebase-summary.md`.
- `docs/project-roadmap.md` had deferred semantic B-roll and CapCut compatibility. This request re-promotes deterministic folder-based media mapping, not semantic retrieval and not CapCut project compatibility.
- `core/services.py` is already large. Keep new orchestration thin or split into focused modules when implementation planning.
- Chap data lives on gdrive mount. Direct render from mount can be slower and less reliable than staging to local temp.

## Real User Objective

The user's actual production goal:

- Finish full YouTube-ready audio story videos with minimum manual work.
- Avoid opening CapCut.
- Prioritize narration/audio/music/thumbnail.
- Keep visuals simple but non-static.
- Use existing assets in Chap folders.

Visual quality target:

- Acceptable, not polished.
- Motion and visual changes exist mainly to avoid static-image/slideshow risk.
- Audience is audio-story listeners; they do not care much about visual finesse.

## Chap 1 Input Facts

Observed folder:

```text
/home/dung/cloud/gdrive/YOUTUBE AUDIO/BÌNH THIÊN SÁCH/BINH THIEN SACH - VO TOI/BẢN DỊCH/Chap 1/
```

Key inputs:

- Voice duration: about 6426 seconds, about 107 minutes 6 seconds.
- `Image/`: 114 images, 4K 3840x2160, about 102 MB.
- `Video/videos/`: 17 videos, about 41 MB total.
- `Instrument/`: 3 music tracks, about 12 MB.
- `.work/scene-plan.md`: 116 scene plan rows, marks scenes with available video.
- `.work/chapters_qa.json`: chapter/story text source.
- `Ảnh bìa/`: likely intended thumbnail source.
- `Ảnh end video/`: likely outro/end card source.

Implication:

- No need for AI semantic matching in first pass.
- Existing `.work/scene-plan.md` already gives deterministic scene structure and video placement hints.
- Use that before inventing any model-based matching.

## Policy And Platform Considerations

Useful official references:

- YouTube channel monetization policies: `https://support.google.com/youtube/answer/1311392`
- YouTube monetizable content guidance: `https://support.google.com/youtube/answer/2490020`
- YouTube spam, deceptive practices, and scams policy: `https://support.google.com/youtube/answer/2801973`

Practical reading:

- Static image plus audio is not automatically a technical upload violation.
- Monetization risk increases when content is repetitive, low-effort, reused, or template-like.
- Motion is only one signal. It does not replace rights, originality, narration value, or packaging quality.
- For this project, avoid producing a single still-image video. Use deterministic motion, scene changes, available video clips, and original story narration package.

Important caveat:

- The tool cannot guarantee YouTube monetization or avoid all policy issues. It can only reduce obvious low-effort/static presentation risk.

## Requirements Captured

Expected output:

- A CLI workflow that takes one Chap folder and produces upload-ready YouTube artifacts.

Concrete target output:

```text
Chap 1/
├── job.yaml
├── outputs/
│   ├── youtube-16x9.mp4
│   ├── captions.srt
│   ├── thumbnail-1280x720.jpg
│   ├── description.txt
│   ├── quality-report.json
│   └── package-manifest.json
└── .videotool/tmp/
```

Acceptance criteria:

- One command can process Chap 1 folder with existing assets.
- Detects voice, script, image folder, video folder, music folder, cover folder.
- Creates or updates `job.yaml`.
- Builds storyboard from `.work/scene-plan.md` when present.
- Uses video clips for scenes marked with video.
- Uses images for all remaining scenes.
- Every image scene has visible motion.
- Full video duration matches voice within 1-2 seconds.
- Audio voice is clear; music is low and ducked under voice.
- Subtitles are generated as SRT and pass validator.
- Thumbnail uses cover image if available, not random video frame first.
- Package step writes description, quality report, manifest.
- Render can resume scene clips if interrupted.

Scope boundary:

- In scope: long-form YouTube 16:9 first.
- In scope: minimal visual motion, simple transitions, optional simple overlay only if cheap.
- In scope: deterministic media mapping from folder and `.work`.
- Out of scope: CapCut project generation.
- Out of scope: full timeline editor.
- Out of scope: cinematic visual quality.
- Out of scope: AI image-to-video generation.
- Out of scope: semantic B-roll retrieval from unrelated libraries.
- Out of scope: guaranteed YouTube monetization.
- Out of scope for first pass: Shorts render, unless user explicitly wants it.

Non-negotiable constraints:

- Keep local-first.
- Use existing Python/FFmpeg stack.
- Do not require CapCut.
- Do not add niche dependencies for small logic.
- Avoid network calls and automatic model downloads.
- Keep deterministic and reviewable.
- Favor fastest path to upload-ready video.

Touchpoints:

- CLI: `src/videotool/cli/main.py`, `src/videotool/cli/commands.py`.
- New or extended command likely under `commands.py` or focused `chap_commands.py`.
- Job schema: `src/videotool/core/job_spec.py`.
- Folder detection: new focused core module, likely `src/videotool/core/chap_folder.py`.
- Storyboard import/mapping: `src/videotool/core/storyboard.py` or new focused module.
- Timeline/render compatibility: `src/videotool/core/timeline.py`, `src/videotool/render/video_filters.py`, `src/videotool/render/segmented.py`.
- Thumbnail package: `src/videotool/package/thumbnails.py`, `src/videotool/core/services.py`.
- Docs/tests: README/docs and targeted tests.

## Evaluated Approaches

### Approach A - Base Video Then CapCut Polish

Description:

- Tool renders base video.
- User opens CapCut only for effects and final polish.

Pros:

- Lowest tool development effort.
- CapCut handles visual effects easily.
- Good for highly polished videos.

Cons:

- User still touches CapCut.
- Render can happen twice.
- Manual work remains high for every chapter.

Verdict:

- Reject for this user goal. User explicitly wants no CapCut.

### Approach B - Full Cinematic Effects Engine

Description:

- Tool owns mưa/gió/sương/light leaks/camera shake/color grading/caption styling.
- Rule engine maps scene tag to effects.

Pros:

- Could fully replace CapCut.
- More visual variety.

Cons:

- Wrong priority.
- Longer development.
- Higher render time.
- More FFmpeg filter complexity.
- More bugs around long 107-minute renders.
- Audience does not require visual finesse.

Verdict:

- Reject for first pass. Overbuilt.

### Approach C - Audio Story Autopublisher

Description:

- Tool owns one-command production.
- Visuals are simple: images pan/zoom, available videos inserted, fade, optional cheap anti-static texture.
- Audio, thumbnail, package are treated as first-class.

Pros:

- Matches real user goal.
- Uses existing code.
- Fastest path to full upload.
- Low manual work.
- Low risk versus building a visual editor.
- Good foundation for later overlays.

Cons:

- Output will not look cinematic.
- Some scenes may still feel generic.
- YouTube policy risk is reduced but not eliminated.

Verdict:

- Recommended.

## Recommended Design

Build `audio-story-fast` workflow.

Suggested command:

```bash
videotool make-youtube "/path/to/Chap 1" --preset audio-story-fast
```

Optional flags for later:

```bash
videotool make-youtube "/path/to/Chap 1" --preview-minutes 5
videotool make-youtube "/path/to/Chap 1" --full
videotool make-youtube "/path/to/Chap 1" --no-subtitles
videotool make-youtube "/path/to/Chap 1" --music "Instrument/Mountain_Gate.mp3"
```

Recommended default behavior:

- `--preset audio-story-fast`
- output long-form `youtube-16x9` only
- captions mode `srt-only`
- image motion enabled
- video scene use enabled
- thumbnail from cover enabled
- render segmented when scene count exceeds threshold
- copy/stage only necessary files or use existing workspace paths carefully

## Folder Detection Rules

Given a Chap folder:

Voice:

- Prefer `*_qa.wav`.
- Else prefer largest `.wav`.
- Else prefer `*_qa.mp3`.
- Else largest audio file outside `Instrument/`.

Script:

- Prefer `*_qa.txt`.
- Else prefer `*_translated.txt`.
- Else largest `.txt` outside prompt files.

Images:

- Prefer `Image/`.
- Accept `.jpg`, `.jpeg`, `.png`, `.webp`.
- Natural sort.

Videos:

- Prefer `Video/videos/`.
- Accept `.mp4`, `.mov`, `.mkv`, `.webm`.
- Natural sort.

Music:

- Prefer `Instrument/`.
- Pick first natural-sort track for MVP, or configurable flag.
- Later: support playlist crossfade.

Thumbnail:

- Prefer `Ảnh bìa/`.
- Else `cover/`.
- Else first high-res image.
- Else generated candidate from output video.

Outro:

- Prefer `Ảnh end video/`.
- Defer actual outro append unless easy. First pass can ignore or use as final scene if explicitly configured.

Scene plan:

- Prefer `.work/scene-plan.md` because it marks video scenes.
- Fallback `.work/chapters_qa.json` for chapters/text.
- Fallback even-split image storyboard.

## Storyboard Strategy

First pass should be deterministic and boring.

Rules:

- Parse scene rows from `.work/scene-plan.md`.
- If row has `video? = ✓`, map to `Video/videos/scene_NNN.mp4` when file exists.
- Else map to `Image/scene_NNN_4K.jpg` or natural image N.
- If scene count exceeds available images, reuse last image or fallback to natural modulo only if explicitly allowed.
- Duration = voice duration divided across scene count unless per-scene timings exist.
- Last scene absorbs rounding remainder.
- Motion rotates across image scenes.
- Transition defaults to cut or fade, not crossfade, for segmented speed.

Recommended schema adjustment:

- Rename or add alias from `StoryboardSceneSpec.image` to a neutral `media` in plan.
- For backward compatibility, accept existing `image`.
- Implementation plan should decide exact migration carefully.

Why:

- Existing render already handles video if media path is video.
- The field name `image` is misleading and will confuse future work.

## Visual Anti-Static Strategy

Minimum viable anti-static:

- All image scenes use slow pan/zoom.
- All scene clips fade in/out up to 0.5s.
- Insert 17 existing videos at marked scenes.
- Keep scene duration roughly 50-60s for 107 minutes and 114 scenes.

Optional cheap additions:

- Very light `noise` filter.
- Very light contrast/saturation curve.
- Occasional dim/bright variation by scene tag.

Avoid for first pass:

- Heavy rain particle generation.
- Multiple overlay layers across full video.
- Per-scene cinematic rule engine.
- AI-generated motion.

If rain/wind is still desired:

- Only support pre-existing overlay video loops.
- Apply to selected scene tags, not entire 107 minutes.
- Keep it optional.
- Do not block MVP on this.

## Audio Strategy

Keep current audio stack:

- voice gain default `0 dB`
- music gain default `-18 dB`
- duck enabled
- loudnorm target `-14 LUFS`
- music loop pre-rendered to voice duration

Do not add two-pass loudnorm first:

- It doubles audio/render overhead.
- Current package measurement can warn.
- If YouTube loudness result is bad after real Chap 1, promote later.

Potential first-pass improvement:

- Add `audio-story-fast` defaults:
  - captions `srt-only`
  - output only `youtube-16x9`
  - render encoder `libx264-fast` for speed unless quality is unacceptable
  - package require SRT true

## Subtitle Strategy

Use SRT only for first pass:

- Generate `outputs/captions.srt`.
- Do not burn subtitles by default.
- User can upload SRT to YouTube.
- Saves render time and avoids visual styling work.

If burn-in is required later:

- Keep plain style.
- No karaoke.
- No dynamic emphasis.

## Thumbnail Strategy

For this use case thumbnail is more important than internal visuals.

MVP requirements:

- If cover folder exists, use best cover image to write `thumbnail-1280x720.jpg`.
- Scale/crop to 1280x720.
- Do not rely on random rendered frame as primary.
- Still generate candidates from video as fallback.

Later:

- Add simple title text overlay if user wants.
- Keep it optional.

## Packaging Strategy

Package output should include:

- `youtube-16x9.mp4`
- `captions.srt`
- `thumbnail-1280x720.jpg`
- `description.txt`
- `quality-report.json`
- `package-manifest.json`
- render logs

Description should include:

- title
- short description if available
- chapter timestamps from `.work/chapters_qa.json` if parseable
- license note
- tags if configured

## Performance Strategy

Expected Chap 1 render:

- Long-form 107-minute 1080p CPU render likely multi-hour.
- Existing docs estimate about real-time for 1h on this CPU for simple 1080p.
- Chap 1 likely 2-4h for one 16:9 output depending filters and gdrive IO.

Optimization priorities:

- Render only `youtube-16x9` first.
- Use `libx264-fast` when acceptable.
- Keep captions as SRT, not burn-in.
- Keep visual filters simple.
- Avoid full-length overlay effects.
- Stage from gdrive to local temp if IO causes stalls.
- Always produce preview before full render.

Recommended workflow:

```bash
videotool make-youtube "Chap 1" --preset audio-story-fast --preview-minutes 5
videotool make-youtube "Chap 1" --preset audio-story-fast --full
```

If preview looks acceptable:

- run full render
- package
- upload

## Risk Assessment

### Risk: YouTube still sees low-effort content

Cause:

- Motion alone may not satisfy platform quality/monetization expectations.

Mitigation:

- Use original narration/story package.
- Use many scenes, not one still image.
- Use 17 video clips where available.
- Use proper title, description, chapters, thumbnail.
- Avoid repetitive template signals across all videos if possible.

### Risk: Render time too long

Cause:

- 107 minutes, 4K inputs, CPU encode.

Mitigation:

- Long-form only first.
- Fast encoder profile.
- SRT-only subtitles.
- No heavy effects.
- Local temp staging.
- Segmented resume.

### Risk: Scene mapping wrong

Cause:

- `.work/scene-plan.md` parser brittle.
- File counts differ: scene plan says 116, images observed 114, videos 17.

Mitigation:

- Emit mapping report before render.
- Fail on missing critical voice/script.
- Warn not fail on missing optional scene media.
- Use deterministic fallback.
- Preview first 5 minutes.

### Risk: `StoryboardSceneSpec.image` field blocks video semantics

Cause:

- Field name says image, though render accepts videos.

Mitigation:

- Plan a backward-compatible `media` alias.
- Tests must cover old `image` jobs and new video media jobs.

### Risk: Gdrive mount stalls

Cause:

- ffprobe/reads from gdrive can be slow.

Mitigation:

- Stage media list and maybe selected assets to local workspace.
- Avoid probing every full file if not needed.
- Use file naming and known dimensions where safe.

## Implementation Considerations For Plan

Recommended phases for `/ck:plan`:

### Phase 1 - Chap Folder Detection

Deliver:

- Detect voice/script/images/videos/music/cover/scene-plan.
- Dry-run command prints detected assets.
- Tests with synthetic folder.

Likely files:

- new `src/videotool/core/chap_folder.py`
- update CLI command wiring
- tests for detection

### Phase 2 - Video-Aware Storyboard Import

Deliver:

- Parse `.work/scene-plan.md`.
- Build storyboard where video-marked scenes use `Video/videos/scene_NNN.mp4`.
- Fallback to image storyboard.
- Emit mapping summary.

Likely files:

- `src/videotool/core/storyboard.py` or new `storyboard_import.py`
- `src/videotool/core/job_spec.py`
- tests for video scene mapping

### Phase 3 - `make-youtube` Orchestration

Deliver:

- One command creates job, storyboard, SRT if possible, render/package sequence.
- Preview mode.
- Full mode.

Likely files:

- CLI command files
- `src/videotool/core/services.py` or focused service module
- tests for dry-run orchestration

### Phase 4 - Thumbnail From Cover

Deliver:

- Prefer cover folder for `thumbnail-1280x720.jpg`.
- Fallback to generated candidates.

Likely files:

- `src/videotool/package/thumbnails.py`
- package service
- tests with cover image fixture

### Phase 5 - Validation And Docs

Deliver:

- README updated.
- `docs/codebase-summary.md` updated.
- Chap 1 smoke instructions.
- Full test suite.
- 3-5 minute preview render validation.

## Success Metrics

Functional:

- Chap 1 can be processed from folder with one command.
- Generates all expected upload artifacts.
- Job and storyboard are inspectable.
- Video-marked scenes use video clips.
- Image scenes move.
- Audio duration and video duration are within 1-2 seconds.
- SRT validates.
- Package quality report exists.

Speed:

- Preview render completes quickly enough to inspect before full render.
- Full long-form render completes without manual intervention.
- No CapCut step required.

Operational:

- Resume works after interrupted segmented render.
- Logs are written per scene and mux.
- Missing optional assets produce warnings, not crashes.

Non-goals:

- Cinematic visuals.
- Perfect subtitles.
- Shorts output.
- CapCut compatibility.
- Monetization guarantee.

## Final Recommendation

Proceed with **Audio Story Autopublisher MVP**.

Hard recommendation:

- Do not build heavy effects first.
- Do not chase CapCut replacement quality.
- Do not implement semantic media retrieval.
- Do not render Shorts first.

Build the shortest path to:

```text
Chap folder -> long-form YouTube video + SRT + thumbnail + description + quality report
```

Once Chap 1 uploads cleanly, iterate only on real pain:

- if visual too static, add cheap overlay preset
- if render too slow, tune encoder/staging
- if YouTube loudness warning, add stronger audio gate
- if mapping wrong, improve scene-plan parser

## Open Questions

None blocking for planning.

Assumptions for plan:

- First implementation targets long-form YouTube 16:9 only.
- CapCut compatibility remains out of scope.
- Internal visual quality can stay basic.
- Thumbnail from cover folder is important.
- `Chap 1` is representative but implementation must generalize to similar Chap folders.

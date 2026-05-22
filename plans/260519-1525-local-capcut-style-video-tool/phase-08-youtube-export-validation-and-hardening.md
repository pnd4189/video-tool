---
phase: 8
title: "YouTube Export Validation And Hardening"
status: in-progress
priority: P1
effort: "2d"
dependencies: [1, 2, 3, 4, 5, 6]
---

# Phase 8: YouTube Export Validation And Hardening

## Context Links

- YouTube upload encoding: https://support.google.com/youtube/answer/1722171
- YouTube caption formats: https://support.google.com/youtube/answer/2734698
- YouTube thumbnails: https://support.google.com/youtube/answer/72431

## Overview

Make the output package suitable for direct YouTube upload review: media conformance, captions, thumbnail candidate, metadata draft, logs, and license/credits report.

## Requirements

- Functional: validate MP4 streams, check resolution/aspect, check audio codec/rate, SRT existence, thumbnail dimensions, package manifest, render quality report.
- Non-functional: no upload automation in V1, no false claim that YouTube acceptance is guaranteed.

## Architecture

```text
RenderResult
  -> ffprobe output validation
  -> thumbnail generator
  -> SRT/caption validation
  -> metadata draft
  -> license report
  -> package manifest
```

The package validator should be independent from the renderer so users can run it against existing files.

## Related Code Files

| Action | Path | Purpose | Test Impact |
|---|---|---|---|
| Create | `/home/dung/VIBE_CODING/video-tool/src/videotool/package/youtube.py` | YouTube package checks | Unit/integration |
| Create | `/home/dung/VIBE_CODING/video-tool/src/videotool/package/thumbnails.py` | Thumbnail candidate generation | Integration |
| Create | `/home/dung/VIBE_CODING/video-tool/src/videotool/package/reports.py` | Quality/package report | Unit tests |
| Create | `/home/dung/VIBE_CODING/video-tool/src/videotool/package/manifest.py` | Output manifest | Unit tests |
| Create | `/home/dung/VIBE_CODING/video-tool/tests/test_youtube_package.py` | Package tests | New |
| Modify | `/home/dung/VIBE_CODING/video-tool/src/videotool/cli/commands.py` | `package` command | CLI tests |

## YouTube Package Standard

For each job output folder:

```text
outputs/video-slug/
  youtube-16x9.mp4
  shorts-9x16.mp4
  captions.srt
  thumbnail-1280x720.jpg
  description.txt
  license-report.md
  render.log
  quality-report.json
  package-manifest.json
```

Video targets:
- 1920x1080 or 1080x1920.
- H.264 High Profile, yuv420p, AAC-LC stereo, 48 kHz.
- `+faststart` for MP4.
- Bitrate targets: 1080p30 about 8 Mbps, 1080p60 about 12 Mbps.

## Implementation Steps

1. Implement `ffprobe`-based output validator.
2. Validate dimensions, aspect ratio, fps, video codec, pixel format, audio codec, sample rate, duration.
3. Generate thumbnail candidates from timeline/keyframes or explicit source image.
4. Validate thumbnail as 16:9 and suitable dimensions; target 1280x720.
5. Validate SRT file existence and timestamp ordering.
6. Generate `description.txt` from job title, credits, and optional notes.
7. Generate `quality-report.json` with warnings and pass/fail checks.
8. Generate `package-manifest.json` listing all files, checksums, and source job.
9. Add CLI `package` command and make `render --package` optional.
10. Add end-to-end smoke test for a tiny YouTube package.

## Function Or Interface Checklist

- `validate_youtube_video(path, preset)`
- `generate_thumbnail(render_result, job_spec)`
- `validate_srt(path)`
- `write_description(job_spec, license_report)`
- `write_quality_report(checks)`
- `write_package_manifest(files)`

## Test Scenario Matrix

| Scenario | Type | Expected |
|---|---|---|
| valid package | Integration | pass |
| wrong resolution | Unit | warning/fail by preset |
| missing SRT | Unit | warning if captions optional, fail if required |
| invalid SRT ordering | Unit | fail |
| missing license report | Unit | fail |
| thumbnail wrong aspect | Unit | fail/warning |

## Dependency Map

- Depends on render, asset report, subtitles, and CLI phases.
- GUI can call package validator but does not own it.

## Success Criteria

- [x] Package validator can run independently on existing output folder.
- [ ] Rendered job includes all standard files.
- [x] Quality report clearly separates pass, warning, and fail.
- [x] Thumbnail candidate is generated for 16:9 YouTube videos.
- [x] End-to-end smoke test covers render + package.

## Risk Assessment

- Risk: claiming "YouTube-ready" too strongly. Mitigation: phrase as "conforms to local checks", not guaranteed platform acceptance.
- Risk: Shorts thumbnail behavior differs from long-form. Mitigation: generate 16:9 thumbnail for long-form; store frame candidates for Shorts only.
- Risk: YouTube specs change. Mitigation: isolate validation constants and cite source URLs in docs.

## Security Considerations

- No YouTube credentials or upload tokens in V1.
- Checksums help detect package drift.
- Reports should not include secret local paths outside project root.

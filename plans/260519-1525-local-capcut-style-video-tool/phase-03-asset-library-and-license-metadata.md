---
phase: 3
title: "Asset Library And License Metadata"
status: completed
priority: P1
effort: "2d"
dependencies: [1, 2]
---

# Phase 3: Asset Library And License Metadata

## Context Links

- [Research summary](./research/research-summary.md)
- Pexels license: https://www.pexels.com/license/
- Pixabay license: https://pixabay.com/service/license-summary/
- Freesound API: https://freesound.org/docs/api/overview.html
- YouTube Audio Library: https://support.google.com/youtube/answer/3376882

## Overview

Create an asset library that treats license metadata as first-class data. This avoids the common failure mode: a video renders correctly but is risky to upload.

## Requirements

- Functional: import local assets, index metadata, validate license policy, generate credits/license report.
- Non-functional: no hidden asset downloads, no ambiguous license state, supports manual assets in V1 and API adapters later.

## Architecture

```text
assets/
  broll/
  images/
  music/
  sfx/
  overlays/
  fonts/
  licenses/

asset-index.yaml
  -> AssetRecord[]
  -> license validation
  -> render-safe media index
```

V1 supports manual import and metadata editing. API downloaders for Pexels/Pixabay/Freesound are post-V1 extensions.

## Related Code Files

| Action | Path | Purpose | Test Impact |
|---|---|---|---|
| Create | `/home/dung/VIBE_CODING/video-tool/src/videotool/assets/library.py` | Asset index load/save/query | Unit tests |
| Create | `/home/dung/VIBE_CODING/video-tool/src/videotool/assets/licenses.py` | License policy checks | Unit tests |
| Create | `/home/dung/VIBE_CODING/video-tool/src/videotool/assets/importer.py` | Manual import helper | Unit/integration |
| Create | `/home/dung/VIBE_CODING/video-tool/src/videotool/assets/reports.py` | Credits report writer | Unit tests |
| Create | `/home/dung/VIBE_CODING/video-tool/examples/assets/asset-index.yaml` | Example metadata | Schema tests |
| Create | `/home/dung/VIBE_CODING/video-tool/tests/test_asset_library.py` | Index tests | New |
| Create | `/home/dung/VIBE_CODING/video-tool/tests/test_license_policy.py` | License tests | New |

## Asset Metadata Contract

```yaml
id: "broll-city-001"
path: "broll/city.mp4"
type: "video"
tags: ["city", "night"]
source_url: "https://example.com/source"
author: "creator name"
license: "pexels"
commercial_ok: true
attribution_required: false
attribution_text: ""
content_id_risk: "low"
imported_at: "2026-05-19"
```

## Implementation Steps

1. Define `AssetRecord`, `AssetType`, and `LicenseRecord`.
2. Support local `asset-index.yaml` load/save and validation.
3. Add media probing link: duration, width, height, fps, audio streams are attached by Phase 4.
4. Add license policy: `licensed-only`, `allow-missing-local`, `strict-attribution`.
5. Add import command: copy/link asset into category folder and create metadata stub.
6. Add credits report writer with grouped assets and attribution text.
7. Add warning classification: missing source, attribution required, commercial use unknown, high Content ID risk.
8. Add tests for CC0, CC-BY, Pexels/Pixabay-style, missing metadata, and blocked assets.

## Function Or Interface Checklist

- `AssetRecord`
- `AssetLibrary`
- `load_asset_index(path)`
- `validate_asset_policy(asset_library, policy)`
- `write_license_report(asset_library, output_path)`
- `import_local_asset(source_path, asset_type, metadata)`

## Test Scenario Matrix

| Scenario | Type | Expected |
|---|---|---|
| all assets licensed | Unit | policy passes |
| missing license in strict mode | Unit | policy fails |
| attribution required | Unit | credits report includes attribution |
| duplicated asset id | Unit | validation error |
| asset path outside library root | Security | reject |
| unknown license | Unit | warning or fail by policy |

## Dependency Map

- Depends on schema foundation from Phase 2.
- Blocks render safety gate and YouTube package report.

## Success Criteria

- [x] Asset index validates before render.
- [x] License report is produced for every rendered job.
- [x] Strict policy blocks missing/unknown license assets.
- [x] Manual import creates or updates metadata stubs.
- [x] Attribution text is preserved in generated report.
- [x] Tests cover license pass/fail cases.

## Risk Assessment

- Risk: false sense of copyright safety. Mitigation: report says "license metadata recorded", not "guaranteed claim-free".
- Risk: API terms change. Mitigation: adapters are optional and metadata stores retrieval date/source.
- Risk: asset index becomes tedious. Mitigation: import command creates metadata stub.

## Security Considerations

- Reject path traversal outside project/job roots.
- Never execute downloaded files.
- Do not store API keys in asset metadata; use environment variables later if API adapters need keys.

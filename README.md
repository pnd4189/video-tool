# VideoTool

Local audio-first video composer for repeatable YouTube and Shorts exports. V1 is CLI-first: a `job.yaml` describes voice audio, media, music, captions, render presets, package reports, and asset license policy. The thin GUI wraps the same services.

## Scope

Included in V1:

- Python CLI with `doctor`, `init-job`, `validate`, `probe`, `render`, `batch`, `transcribe`, `analyze-audio`, `package`, and `benchmark`.
- FFmpeg command generation and execution through safe argument lists.
- Manual asset license metadata and credits report.
- Offline subtitle adapter hooks with `faster-whisper` as an optional extra.
- YouTube package checks for videos, captions, thumbnails, license report, quality report, and manifest.

Out of scope for V1: cloud rendering, social upload, CapCut project compatibility, full timeline editor, semantic B-roll retrieval, and automatic model downloads.

## Install

Base install:

```bash
python3.12 -m venv .venv
. .venv/bin/activate
pip install -e .
```

Development install:

```bash
pip install -e '.[dev]'
```

Optional extras:

```bash
pip install -e '.[ai]'
pip install -e '.[gui]'
```

FFmpeg 6.1+ with `ffmpeg` and `ffprobe` must be available on `PATH`.

## Quick Start

```bash
videotool doctor
videotool init-job ./jobs/video-001 --voice voice.wav --media media --music music/background.mp3
videotool validate ./jobs/video-001/job.yaml
videotool render ./jobs/video-001/job.yaml --all --dry-run
videotool package ./jobs/video-001/job.yaml
```

CLI commands in V1:

- `videotool version`
- `videotool doctor`
- `videotool init-job`
- `videotool validate`
- `videotool probe`
- `videotool render`
- `videotool batch`
- `videotool transcribe`
- `videotool analyze-audio`
- `videotool package`
- `videotool benchmark`
- `videotool gui`
- `videotool storyboard plan`

## Storyboard Timeline

Name generated images by scene number so the tool can match them deterministically:

```text
media/scene-001.png
media/scene-002.png
media/scene-003.png
```

Create a storyboard job from prompt files:

```bash
videotool storyboard plan \
  --image-prompts ./chuong_031-040_image_prompts.txt \
  --video-prompts ./chuong_031-040_video_prompts.txt \
  --media ./media \
  --voice voice.wav \
  --music music/background.mp3 \
  --output job.yaml
```

The storyboard planner reads `[Scene N]` sections, maps camera/action text to a fixed set of safe motions (`zoom-in`, `zoom-out`, `slow-push`, `pan-left`, `pan-right`, `pan-up`, `pan-down`, `ken-burns`), and writes editable `storyboard` entries into `job.yaml`. AI/provider-based matching can be added later, but the first pass stays deterministic.

To burn subtitles into the rendered video, create `outputs/captions.srt` and set:

```yaml
captions:
  mode: srt-and-burn
```

Transcription never downloads models implicitly. Download a compatible `faster-whisper` model yourself, then pass its local folder:

```bash
videotool transcribe ./jobs/video-001/job.yaml --model ./models/faster-whisper-small
```

Package validation expects `outputs/captions.srt` by default. If that file is missing, `videotool package` fails the package check.

Generate tiny local test media:

```bash
scripts/generate-test-media.sh
```

The default render profile is `libx264-balanced` for portable YouTube uploads. VAAPI profiles are present as opt-in profile names, but should be benchmarked on the local machine before real use.

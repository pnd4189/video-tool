#!/usr/bin/env bash
set -euo pipefail

ROOT="${1:-fixtures/generated}"
mkdir -p "$ROOT/media" "$ROOT/music"

ffmpeg -y -f lavfi -i "sine=frequency=440:duration=3" "$ROOT/voice.wav"
ffmpeg -y -f lavfi -i "sine=frequency=220:duration=1" "$ROOT/music/background.mp3"
ffmpeg -y -f lavfi -i "testsrc=size=640x360:rate=30:duration=3" "$ROOT/media/broll.mp4"
ffmpeg -y -f lavfi -i "color=c=#203050:s=1280x720:d=1" -frames:v 1 -update 1 "$ROOT/media/scene-001.png"
ffmpeg -y -f lavfi -i "color=c=#503020:s=1280x720:d=1" -frames:v 1 -update 1 "$ROOT/media/scene-002.png"

cat > "$ROOT/job.yaml" <<'YAML'
version: 1
project:
  title: generated-smoke
  language: vi
inputs:
  voice: voice.wav
  media_dir: media
  music: music/background.mp3
outputs:
  - preset: youtube-16x9
  - preset: shorts-9x16
captions:
  mode: srt-only
assets:
  policy: allow-missing-local
render:
  encoder: libx264-fast
  temp_dir: .videotool/tmp
YAML

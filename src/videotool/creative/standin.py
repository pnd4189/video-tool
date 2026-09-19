"""A light stand-in of an episode folder, built without downloading any media.

Every file becomes a zero-byte placeholder except the text files the pipeline reads (SRT, scripts,
prompts, description template, scene plan), which are copied for real, and the narration, which
becomes a silent WAV of the exact length. Running the real preparation code on it shows what the
render box will do — which cue it drops, which card it misses — before anything is staged.
"""

from __future__ import annotations

import shutil
import struct
import subprocess
import wave
from dataclasses import dataclass, field
from pathlib import Path

AUDIO_EXTS = (".wav", ".mp3", ".m4a")
SKIP_PREFIXES = ("outputs/", ".videotool/", "_creative/")
SKIP_NAMES = ("job.yaml", "creative.yaml")
RCLONE_TIMEOUT_S = 300
WAV_HEAD_BYTES = 64 * 1024
MP4_PROBE_BYTES = 1024 * 1024


@dataclass
class StandIn:
    job_dir: Path
    files: list[str]
    voice: str
    voice_seconds: float
    warnings: list[str] = field(default_factory=list)


def is_remote(source: str) -> bool:
    return not Path(source).exists() and ":" in source


def _rclone(args: list[str], binary: bool = False) -> bytes | str:
    result = subprocess.run(["rclone", *args], capture_output=True, check=True, timeout=RCLONE_TIMEOUT_S)
    return result.stdout if binary else result.stdout.decode("utf-8", errors="replace")


def _join(source: str, rel: str) -> str:
    return f"{source.rstrip('/')}/{rel}" if not source.endswith(":") else f"{source}{rel}"


def list_files(source: str) -> list[str]:
    """Relative POSIX paths of every file under the source, published outputs excluded."""
    if is_remote(source):
        names = [n for n in str(_rclone(["lsf", "-R", "--files-only", "--fast-list", source])).splitlines() if n]
    else:
        root = Path(source)
        names = [p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()]
    return sorted(n for n in names if not n.startswith(SKIP_PREFIXES) and n not in SKIP_NAMES)


def is_text(rel: str) -> bool:
    """The files the pipeline actually reads: root SRT/TXT, scene anchors, the hidden scene plan."""
    if "/" not in rel and rel.lower().endswith((".srt", ".txt", "_scene_anchors.md")):
        return True
    return rel == ".work/scene-plan.md"


def fetch_texts(source: str, rels: list[str], job_dir: Path) -> None:
    """Copy the text files for real — one rclone call for a remote source."""
    if not rels:
        return
    if is_remote(source):
        listing = job_dir / ".standin-files.txt"
        listing.write_text("\n".join(rels) + "\n", encoding="utf-8")
        _rclone(["copy", source, str(job_dir), "--files-from", str(listing)])
        listing.unlink()
        return
    for rel in rels:
        (job_dir / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(Path(source) / rel, job_dir / rel)


def read_head(source: str, rel: str, nbytes: int) -> bytes:
    if is_remote(source):
        return bytes(_rclone(["cat", "--head", str(nbytes), _join(source, rel)], binary=True))
    with open(Path(source) / rel, "rb") as fh:
        return fh.read(nbytes)


def read_tail(source: str, rel: str, nbytes: int) -> bytes:
    if is_remote(source):
        return bytes(_rclone(["cat", "--tail", str(nbytes), _join(source, rel)], binary=True))
    path = Path(source) / rel
    with open(path, "rb") as fh:
        fh.seek(max(0, path.stat().st_size - nbytes))
        return fh.read()


def wav_seconds(head: bytes) -> float | None:
    """Duration from the RIFF header alone: walk the chunks (a LIST chunk may precede `data`)."""
    if len(head) < 12 or head[:4] != b"RIFF" or head[8:12] != b"WAVE":
        return None
    pos, byte_rate = 12, None
    while pos + 8 <= len(head):
        chunk_id, size = head[pos:pos + 4], struct.unpack("<I", head[pos + 4:pos + 8])[0]
        if chunk_id == b"fmt " and pos + 20 <= len(head):
            byte_rate = struct.unpack("<I", head[pos + 16:pos + 20])[0]
        if chunk_id == b"data":
            return size / byte_rate if byte_rate else None
        pos += 8 + size + (size & 1)
    return None


def mvhd_seconds(head: bytes) -> float | None:
    """Duration from an MP4/M4A `mvhd` box at the head of the file (faststart)."""
    i = head.find(b"mvhd")
    while i >= 4 and struct.unpack(">I", head[i - 4:i])[0] not in (108, 120):
        i = head.find(b"mvhd", i + 4)  # the 4 bytes happened to occur inside media data
    if i < 4 or i + 36 > len(head):
        return None
    version = head[i + 4]
    if version == 1:
        timescale, duration = struct.unpack(">IQ", head[i + 24:i + 36])
    else:
        timescale, duration = struct.unpack(">II", head[i + 16:i + 24])
    return duration / timescale if timescale else None


def media_seconds(source: str, rel: str) -> float | None:
    """Length of an audio/video file without downloading it: the WAV header, else the MP4 `mvhd`
    box (at the head when faststart, else in the tail), else ffprobe for a local file."""
    if rel.lower().endswith(".wav"):
        seconds = wav_seconds(read_head(source, rel, WAV_HEAD_BYTES))
    else:
        seconds = mvhd_seconds(read_head(source, rel, MP4_PROBE_BYTES))
        if seconds is None and rel.lower().endswith((".mp4", ".m4a", ".mov")):
            seconds = mvhd_seconds(read_tail(source, rel, MP4_PROBE_BYTES))
    if seconds is None and not is_remote(source):
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(Path(source) / rel)],
            capture_output=True, text=True, errors="replace",
        )
        try:
            seconds = float(probe.stdout.strip())
        except ValueError:
            seconds = None
    return seconds


def pick_voice(files: list[str]) -> str | None:
    root_audio = [f for f in files if "/" not in f and f.lower().endswith(AUDIO_EXTS)]
    for ext in AUDIO_EXTS:
        if f"voice{ext}" in root_audio:
            return f"voice{ext}"
    return root_audio[0] if root_audio else None


def write_silence(path: Path, seconds: float) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(1)
        w.setframerate(1000)
        w.writeframes(b"\x80" * round(seconds * 1000))


def _srt_end(job_dir: Path) -> float | None:
    from videotool.creative.rules import parse_srt, voice_end

    srts = sorted(job_dir.glob("*_vi_qa.srt")) or sorted(job_dir.glob("*.srt"))
    return voice_end(parse_srt(srts[0].read_text(encoding="utf-8"))) if srts else None


def build_standin(source: str, job_dir: Path) -> StandIn:
    """Materialize the stand-in under `job_dir` (must not exist yet)."""
    job_dir = Path(job_dir)
    job_dir.mkdir(parents=True)
    files = list_files(source)
    voice = pick_voice(files)
    if voice is None:
        raise FileNotFoundError(f"no narration audio ({', '.join(AUDIO_EXTS)}) at the root of {source}")
    texts = [rel for rel in files if is_text(rel)]
    fetch_texts(source, texts, job_dir)
    for rel in files:
        if rel in texts or rel == voice:
            continue
        dest = job_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"")
    warnings: list[str] = []
    seconds = media_seconds(source, voice)
    if seconds is None:
        seconds = _srt_end(job_dir)
        warnings.append(f"could not read the length of {voice} from its header; used the SRT end")
    if not seconds:
        raise ValueError(f"cannot tell how long {voice} is")
    write_silence(job_dir / voice, seconds)
    return StandIn(job_dir, files, voice, seconds, warnings)

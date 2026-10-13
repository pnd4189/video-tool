"""Post-render review: the frames worth eyeballing on one sheet, and loudness by section.

Runs on a finished episode (after sfx / package / metadata), on this machine, and never touches the
render. The sheet tiles the CTA cards, the intro and ending images, every chapter start and a few
mid-cue subtitle frames. One ebur128 pass over the final audio gives the integrated loudness and true
peak, the narration level, both CTA clips, and each SFX cue against the narration around it — and
against the pre-SFX master `videotool sfx` keeps, which measures exactly what the cue added. The
package QA only checks the integrated LUFS, so "an SFX louder than the voice" or "a CTA far quieter
than the narration" went unseen. Findings are warnings for whoever reviews; nothing is blocked.
"""
from __future__ import annotations

import json
import math
import re
import statistics
import subprocess
import tempfile
from dataclasses import dataclass, field, replace
from pathlib import Path

from videotool.core.errors import DependencyError, ValidationError
from videotool.core.job_spec import load_job
from videotool.core.media_probe import probe_media
from videotool.creative.rules import parse_srt
from videotool.package.youtube import YT_LUFS_TARGET, YT_LUFS_TOLERANCE, parse_integrated_lufs

TILE_W, TILE_H, COLS, MAX_SHOTS = 480, 270, 4, 24
TRUE_PEAK_MAX_DBTP = -0.5
CTA_GAP_LU = 4.0  # a CTA clip this far from the narration level reads as a volume jump
SFX_WINDOW_MAX_S = 4.0
SFX_FAINT_LU = 0.5  # the cue lifts its window less than this over the pre-SFX master: barely audible
SFX_LOUD_LU = 10.0  # the cue's momentary peak sits this far above the narration around it
_FRAME = re.compile(r"t:\s*([\d.]+)\s+TARGET:\S+\s+LUFS\s+M:\s*(\S+)\s+S:\s*(\S+)")
_LRA = re.compile(r"LRA:\s*(-?[\d.]+)\s*LU")
_PEAK = re.compile(r"Peak:\s*(-?[\d.]+|-inf)\s*dBFS")


@dataclass(frozen=True)
class Shot:
    t: float
    label: str


@dataclass
class Review:
    video: Path
    sheet: Path
    report: Path
    lines: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def pick_shots(duration: float, intro: float, outro: float, narration: float,
               chapters: list[tuple[float, str]], cues: list[tuple[float, float, str]]) -> list[Shot]:
    """Final-video times to look at: CTA cards, intro/ending images, chapter starts, three subtitles."""
    fixed = [Shot(intro + 5.0, "intro card"), Shot(intro + narration - 5.0, "ending card")]
    if intro > 0:
        fixed.insert(0, Shot(intro / 2, "CTA in"))
    if outro > 0:
        fixed.append(Shot(duration - outro / 2, "CTA out"))
    for frac in (1, 2, 3):
        if cues:
            start, end, _ = min(cues, key=lambda c: abs((c[0] + c[1]) / 2 - narration * frac / 4))
            fixed.append(Shot(intro + (start + end) / 2, f"subtitle {frac}/4"))
    chapter_shots = [Shot(intro + start + 3.0, _chapter_label(title)) for start, title in chapters]
    room = max(MAX_SHOTS - len(fixed), 1)
    if len(chapter_shots) > room:  # many chapters: spread the ones that fit over the episode
        step = (len(chapter_shots) - 1) / max(room - 1, 1)
        chapter_shots = [chapter_shots[round(i * step)] for i in range(room)]
    shots = sorted((s for s in fixed + chapter_shots if 0 <= s.t <= duration), key=lambda s: s.t)
    return [replace(s, t=min(max(s.t, 0.2), duration - 0.2)) for s in shots]


def _chapter_label(title: str) -> str:
    m = re.search(r"\d+", title)
    return f"ch {m.group()}" if m else re.sub(r"[^A-Za-z0-9 /-]", "", title)[:14] or "chapter"


def contact_sheet(video: Path, shots: list[Shot], out_png: Path) -> Path:
    font = _font_file()
    rows = max(1, math.ceil(len(shots) / COLS))
    out_png.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="vt-review-") as tmp:
        for i, shot in enumerate(shots):
            vf = f"scale={TILE_W}:{TILE_H}"
            if font:
                vf += (f",drawtext=fontfile='{font}':text='{_hms(shot.t)}  {shot.label}':x=8:y=8:"
                       "fontsize=20:fontcolor=white:box=1:boxcolor=black@0.6:boxborderw=4")
            _ffmpeg(["-ss", f"{shot.t:.3f}", "-i", str(video), "-frames:v", "1", "-vf", vf, f"{tmp}/{i:02d}.png"])
        for i in range(len(shots), rows * COLS):  # fill the grid so `tile` emits one full sheet
            _ffmpeg(["-f", "lavfi", "-i", f"color=black:s={TILE_W}x{TILE_H}", "-frames:v", "1", f"{tmp}/{i:02d}.png"])
        _ffmpeg(["-i", f"{tmp}/%02d.png", "-vf", f"tile={COLS}x{rows}:padding=4:color=black",
                 "-frames:v", "1", str(out_png)])
    return out_png


def loudness_timeline(path: Path, start: float | None = None, duration: float | None = None,
                      ) -> tuple[list[tuple[float, float, float]], dict]:
    """(t, momentary, short-term) every 100 ms from one ebur128 pass, plus the summary block."""
    window = (["-ss", f"{start:.3f}"] if start is not None else []) + (
        ["-t", f"{duration:.3f}"] if duration is not None else [])
    stderr = _ffmpeg(["-nostats", *window, "-i", str(path), "-vn", "-af",
                      "ebur128=framelog=info:peak=true", "-f", "null", "-"], timeout=3600)
    frames = [(float(t), _num(m), _num(s)) for t, m, s in _FRAME.findall(stderr)]
    lra, peak = _LRA.findall(stderr), _PEAK.findall(stderr)
    return frames, {"integrated_lufs": parse_integrated_lufs(stderr),
                    "lra_lu": float(lra[-1]) if lra else None,
                    "true_peak_dbtp": _num(peak[-1]) if peak else None}


def _level(frames: list[tuple[float, float, float]], lo: float, hi: float, col: int,
           skip: list[tuple[float, float]] = ()) -> float | None:
    values = [f[col] for f in frames if lo <= f[0] <= hi and math.isfinite(f[col]) and f[col] > -70
              and not any(a - 1.0 <= f[0] <= b + 1.0 for a, b in skip)]
    return round(statistics.median(values), 1) if values else None


def _peak(frames: list[tuple[float, float, float]], lo: float, hi: float) -> float | None:
    values = [f[1] for f in frames if lo <= f[0] <= hi and math.isfinite(f[1])]
    return max(values) if values else None


def section_report(frames: list[tuple[float, float, float]], summary: dict, *, intro: float, narration: float,
                   duration: float, outro: float, sfx: list[dict]) -> tuple[dict, list[str]]:
    windows = [(c["t"], c["t"] + c["length"]) for c in sfx]
    report = {**summary, "narration_lufs": _level(frames, intro + 5, intro + narration - 5, 2, windows)}
    warnings = []
    integrated, tp = summary.get("integrated_lufs"), summary.get("true_peak_dbtp")
    if integrated is None or abs(integrated - YT_LUFS_TARGET) > YT_LUFS_TOLERANCE:
        warnings.append(f"integrated loudness {integrated} LUFS, target {YT_LUFS_TARGET} ±{YT_LUFS_TOLERANCE}")
    if tp is not None and tp > TRUE_PEAK_MAX_DBTP:
        warnings.append(f"true peak {tp} dBTP is above {TRUE_PEAK_MAX_DBTP}")
    for name, lo, hi in (("cta_in_lufs", 3.0, intro), ("cta_out_lufs", duration - outro + 3.0, duration)):
        level = _level(frames, lo, hi, 2) if hi - lo >= 1.0 else None
        report[name] = level
        if level is not None and report["narration_lufs"] is not None and abs(level - report["narration_lufs"]) > CTA_GAP_LU:
            warnings.append(f"{name[:-5].replace('_', ' ')} sits at {level} LUFS, narration {report['narration_lufs']} LUFS")
    for cue in sfx:
        peak = _peak(frames, cue["t"], cue["t"] + cue["length"])
        around = _level(frames, cue["t"] - 12, cue["t"] - 1, 1, windows)
        cue["peak_lufs"] = peak
        cue["over_narration_lu"] = round(peak - around, 1) if peak is not None and around is not None else None
        if cue["over_narration_lu"] is not None and cue["over_narration_lu"] > SFX_LOUD_LU:
            warnings.append(f"SFX {cue['file']} at {_hms(cue['t'])} peaks {cue['over_narration_lu']} LU over the voice")
        if cue.get("added_lu") is not None and cue["added_lu"] < SFX_FAINT_LU:
            warnings.append(f"SFX {cue['file']} at {_hms(cue['t'])} adds only {cue['added_lu']} LU — barely audible")
    report["sfx"] = sfx
    return report, warnings


def run_review(job_path: Path, video: Path | None = None) -> Review:
    job_path = Path(job_path).resolve()
    root, job = job_path.parent, load_job(job_path)
    outputs = root / "outputs"
    if video is None:
        mp4s = sorted(outputs.glob("*.mp4"))
        if len(mp4s) != 1:
            raise ValidationError(f"expected one mp4 in {outputs}, found {[p.name for p in mp4s]}; pass --video")
        video = mp4s[0]
    duration = probe_media(video).duration
    intro = probe_media(root / job.inputs.intro_cta).duration if job.inputs.intro_cta else 0.0
    outro = probe_media(root / job.inputs.outro_cta).duration if job.inputs.outro_cta else 0.0
    narration = probe_media(root / job.inputs.voice).duration
    chapters_json = outputs / "chapters.json"
    chapters = ([(float(c["start"]), str(c["title"])) for c in json.loads(chapters_json.read_text(encoding="utf-8"))]
                if chapters_json.exists() else [(c.start, c.title) for c in job.project.chapters])
    srt = outputs / "captions.srt"
    cues = parse_srt(srt.read_text(encoding="utf-8")) if srt.exists() else []

    review_dir = root / ".videotool" / "review"
    sheet = contact_sheet(video, pick_shots(duration, intro, outro, narration, chapters, cues),
                          review_dir / "contact-sheet.png")
    frames, summary = loudness_timeline(video)
    master = root / ".videotool" / "sfx-master" / f"{job.outputs[0].preset}.mp4"
    sfx = []
    spec = job.enhance.sfx
    for cue in (spec.cues if spec is not None and spec.enabled else []):
        t, length = intro + cue.time, min(probe_media(root / cue.file).duration, SFX_WINDOW_MAX_S)
        entry = {"t": round(t, 2), "file": Path(cue.file).name, "gain_db": cue.gain_db, "length": round(length, 2)}
        if master.exists():
            base, _ = loudness_timeline(master, start=max(t - 1.0, 0.0), duration=length + 2.0)
            peak_base = _peak(base, min(1.0, t), min(1.0, t) + length)
            peak_final = _peak(frames, t, t + length)
            entry["added_lu"] = round(peak_final - peak_base, 1) if None not in (peak_base, peak_final) else None
        sfx.append(entry)
    report, warnings = section_report(frames, summary, intro=intro, narration=narration, duration=duration,
                                      outro=outro, sfx=sfx)
    report_path = review_dir / "review.json"
    report_path.write_text(json.dumps({"video": video.name, **report, "warnings": warnings},
                                      ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [f"sheet {sheet}",
             f"loudness {report['integrated_lufs']} LUFS integrated, true peak {report['true_peak_dbtp']} dBTP, "
             f"LRA {report['lra_lu']} LU; narration {report['narration_lufs']}, CTA in {report['cta_in_lufs']}, "
             f"CTA out {report['cta_out_lufs']} LUFS (short-term median)"]
    if sfx:
        added = [c["added_lu"] for c in sfx if c.get("added_lu") is not None]
        over = [c["over_narration_lu"] for c in sfx if c.get("over_narration_lu") is not None]
        lines.append(f"sfx {len(sfx)} cues; over the voice {min(over, default=0)}..{max(over, default=0)} LU"
                     + (f"; added over the pre-SFX master {min(added)}..{max(added)} LU" if added else ""))
    return Review(video, sheet, report_path, lines, warnings)


def _hms(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 3600}h{s // 60 % 60:02d}m{s % 60:02d}"


def _num(text: str) -> float:
    try:
        return float(text)
    except ValueError:
        return float("nan")


def _font_file() -> str | None:
    try:
        out = subprocess.run(["fc-match", "-f", "%{file}", "sans"], capture_output=True, text=True, errors="replace")
    except FileNotFoundError:
        return None
    path = out.stdout.strip()
    return path if path and Path(path).exists() and not re.search(r"[':\\,]", path) else None


def _ffmpeg(args: list[str], timeout: float = 600) -> str:
    try:
        result = subprocess.run(["ffmpeg", "-y", "-hide_banner", *args], capture_output=True, text=True,
                                errors="replace", timeout=timeout)
    except FileNotFoundError as exc:
        raise DependencyError("ffmpeg was not found. Install FFmpeg 6.1+ and retry.") from exc
    if result.returncode != 0:
        raise ValidationError(f"ffmpeg failed: {' '.join(args[:6])} …\n{result.stderr[-800:]}")
    return result.stderr

"""`videotool creative lint`: replay the render box's preparation on a stand-in of the episode.

source (local folder or rclone remote) -> stand-in job -> prepare_job(cloud) -> apply_creative ->
parallax-link -> checks -> description preview -> report. Nothing is staged and no media is read,
so a wrong title, a dropped climax cue or a missing intro card shows up before the render slot.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from videotool.creative import lint_checks as lc
from videotool.creative.apply import OVERLAY_LIBRARY, SFX_LIBRARY, apply_creative, infer_pack
from videotool.creative.parallax import keep_title_cards_static, story_stills
from videotool.creative.prepare import prepare_job, read_job, run_cli, write_job
from videotool.creative.rules import CreativeError
from videotool.creative.series import find_registry, load_series, match_series
from videotool.creative.standin import build_standin, media_seconds


@dataclass
class LintReport:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    summary: dict = field(default_factory=dict)
    description: str | None = None

    def add(self, found: tuple[list[str], list[str]]) -> None:
        self.errors += found[0]
        self.warnings += found[1]


@contextlib.contextmanager
def _stdout_to_stderr():
    """Route prints AND child-process output to stderr so `--json` keeps stdout clean."""
    sys.stdout.flush()
    saved = os.dup(1)
    os.dup2(2, 1)
    try:
        with contextlib.redirect_stdout(sys.stderr):
            yield
    finally:
        sys.stdout.flush()
        os.dup2(saved, 1)
        os.close(saved)


def _rel(job_dir: Path, value: str | None) -> str | None:
    if not value:
        return None
    path = Path(value)
    return path.relative_to(job_dir).as_posix() if path.is_absolute() else path.as_posix()


def _description(job_dir: Path, data: dict, cta_s: float) -> str | None:
    from videotool.package.youtube import format_chapters_block, render_description_template
    from videotool.render.cta_compose import offset_chapters

    template = next(iter(sorted(job_dir.glob("*_DESCRIPTION_TEMPLATE.txt"))), None)
    if template is None:
        return None
    chapters_path = job_dir / "outputs" / "chapters.json"
    chapters = [(c["start"], c["title"]) for c in json.loads(chapters_path.read_text(encoding="utf-8"))] \
        if chapters_path.exists() else []
    project = data.get("project") or {}
    return render_description_template(
        template.read_text(encoding="utf-8"),
        chapters_block=format_chapters_block(offset_chapters(chapters, cta_s) if cta_s else chapters),
        recap_prev=project.get("recap_previous", ""), summary=project.get("description", ""),
    )


def _prepare(job: Path, creative: dict, sfx_library: Path, overlay_library: Path) -> dict:
    data = prepare_job(job, creative.get("inputs"), "cloud")
    apply_creative(job, data, creative, sfx_library, overlay_library)
    write_job(job / "job.yaml", data)
    if (job / "Parallax").is_dir():
        run_cli(["parallax-link", str(job / "job.yaml"), "--clips-dir", str(job / "Parallax")])
    keep_title_cards_static(job, job / "job.yaml")
    return read_job(job / "job.yaml")


def lint(
    source: str,
    creative_path: Path,
    series_path: Path | None = None,
    sfx_library: Path = SFX_LIBRARY,
    overlay_library: Path = OVERLAY_LIBRARY,
    keep: bool = False,
) -> LintReport:
    report = LintReport()
    creative = yaml.safe_load(Path(creative_path).read_text(encoding="utf-8")) or {}
    work = Path(tempfile.mkdtemp(prefix="videotool-lint-"))
    job = work / "job"
    try:
        with _stdout_to_stderr():
            standin = build_standin(source, job)
            report.warnings += standin.warnings
            try:
                data = _prepare(job, creative, Path(sfx_library), Path(overlay_library))
            except (CreativeError, RuntimeError, subprocess.CalledProcessError) as exc:
                report.errors.append(f"preparation failed: {exc}")
                return report
            inputs = data.get("inputs") or {}
            cta = {key: _cta_seconds(report, source, _rel(job, inputs.get(key))) for key in ("intro_cta", "outro_cta")}
        _run_checks(report, source, job, creative, data, standin, cta, series_path, Path(sfx_library))
        if keep:
            report.summary["stand_in"] = str(job)
        return report
    finally:
        if not keep:
            shutil.rmtree(work, ignore_errors=True)


def _cta_seconds(report: LintReport, source: str, rel: str | None) -> float | None:
    """0.0 without that CTA; None (plus a warning) when the clip's length cannot be read."""
    if not rel:
        return 0.0
    seconds = media_seconds(source, rel)
    if seconds is None:
        report.warnings.append(f"could not read the length of {rel}; times shown without that CTA")
    return seconds


def _run_checks(report, source, job, creative, data, standin, cta, series_path, sfx_library) -> None:
    end_s = standin.voice_seconds
    cta_s = cta["intro_cta"] or 0.0
    registry = series_path or find_registry()
    entry = match_series(load_series(registry), standin.files) if registry else None
    if registry is None:
        report.warnings.append("series.yaml not found — title/metadata not checked")
    report.description = _description(job, data, cta_s)
    pack = ((creative.get("enhance") or {}).get("sfx") or {}).get("pack") or \
        (entry or {}).get("sfx_pack") or infer_pack(job)
    sfx_errors, sfx_warnings, explained = lc.check_sfx(creative, sfx_library / pack, end_s)
    report.add((sfx_errors, sfx_warnings))
    report.add(lc.check_cjk(creative, report.description or ""))
    if registry is not None:
        report.add(lc.check_series(creative, entry))
    report.add(lc.check_description(report.description))
    report.add(lc.check_music(creative, job, (data.get("inputs") or {}).get("music"), end_s))
    report.add(lc.check_title_cards(job, creative, data.get("inputs") or {}))
    stills = story_stills(job, data)
    report.add(lc.check_parallax(creative, data, stills))

    board = data.get("storyboard") or []
    videos = [s for s in board if s.get("video")]
    chapters = job / "outputs" / "chapters.json"
    report.summary.update({
        "source": source,
        "series": (entry or {}).get("id"),
        "voice_seconds": round(end_s, 2),
        "intro_cta_seconds": cta["intro_cta"],
        "outro_cta_seconds": cta["outro_cta"],
        "timing": data.get("timing"),
        "scenes": {"total": len(board), "stills": stills,
                   "parallax": sum(1 for s in videos if str(s["video"]).startswith("Parallax/")),
                   "video": len(videos)},
        "music_cues": len(((data.get("audio") or {}).get("music_schedule")) or []),
        "sfx": {"authored": len(explained), "kept": sum(1 for _, r in explained if r is None), "pack": pack},
        "chapters": len(json.loads(chapters.read_text(encoding="utf-8"))) if chapters.exists() else 0,
        "description_chars": len((report.description or "").split("==== TAGS")[0].rstrip()),
    })

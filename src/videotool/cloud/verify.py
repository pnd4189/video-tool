"""Verify a published Kaggle output without downloading the media."""

from __future__ import annotations

import json
import re

from videotool.cloud import remote
from videotool.cloud.config import REMOTE_TIMEOUT_S
from videotool.cloud.remote import Runner
from videotool.creative.standin import mvhd_seconds

DURATION_TOLERANCE_S = 2.0
CJK = re.compile(r"[一-鿿]")


def _find_mp4(names: list[str]) -> str | None:
    """The published episode mp4 — named after the title, or the preset fallback."""
    mp4s = [n for n in names if n.lower().endswith(".mp4")]
    return next((n for n in mp4s if n != "shorts-9x16.mp4"), None)


def _listing(runner: Runner, output: str) -> dict[str, int]:
    """name -> size in bytes for every file in the output folder (tab-separated: names hold `;`)."""
    text = remote.rclone_text(runner, ["lsf", "--format", "sp", "--separator", "\t", output],
                              timeout=REMOTE_TIMEOUT_S)
    files: dict[str, int] = {}
    for line in text.splitlines():
        size, _, name = line.partition("\t")
        if name.strip():
            files[name.strip()] = int(size) if size.strip().isdigit() else -1
    return files


def verify_output(runner: Runner, state: dict) -> dict:
    """{ok, findings: [str], warnings: [str]}. Failures keep the config; warnings do not."""
    findings: list[str] = []
    warnings: list[str] = []
    output = state["output"]
    files = _listing(runner, output)
    names = list(files)

    mp4 = _find_mp4(names)
    if not mp4:
        return {"ok": False, "findings": [f"không thấy mp4 trong {output}"], "warnings": []}
    state["mp4"] = mp4
    state["mp4_bytes"] = files[mp4]
    if files[mp4] <= 0:
        findings.append(f"mp4 {mp4} rỗng (0 byte)")
    duration = mvhd_seconds(remote.remote_head(runner, f"{output}/{mp4}", 4 * 1024 * 1024))
    expected = state.get("expected_seconds")
    if duration is None:
        warnings.append("không đọc được độ dài mp4 từ mvhd")
    elif expected and abs(duration - expected) > DURATION_TOLERANCE_S:
        findings.append(f"độ dài mp4 {duration:.1f}s ≠ kỳ vọng {expected:.1f}s (CTA + giọng đọc)")

    report = _json(runner, f"{output}/quality-report.json")
    if not isinstance(report, list):
        findings.append("thiếu/không đọc được quality-report.json")
    else:
        report = [c for c in report if isinstance(c, dict)]
        for check in report:
            if str(check.get("status")) == "fail":
                findings.append(f"QA {check.get('name')}: {check.get('message', 'fail')}")
        loud = next((c for c in report if c.get("name") == "loudness_lufs"), None)
        if loud:
            m = re.search(r"-?\d+\.\d+", str(loud.get("message", "")))
            if m and not -15.0 <= float(m.group()) <= -13.0:
                findings.append(f"loudness {m.group()} LUFS ngoài -14±1")
            elif not any(f.startswith("QA loudness") for f in findings):
                warnings.append("quality-report không đo được loudness (non-bug đã biết trên box)")

    description = remote.remote_text(runner, f"{output}/description.txt", REMOTE_TIMEOUT_S)
    if not description:
        findings.append("thiếu description.txt")
    else:
        body = description.split("==== TAGS")[0].rstrip()
        if CJK.search(description):
            findings.append("description còn chữ Trung")
        if len(body) >= 5000:
            findings.append(f"description {len(body)} ký tự trước TAGS (giới hạn 5000)")
        if re.search(r"\{\{[A-Z_]+\}\}", description):
            findings.append("description còn placeholder")
    if state.get("intro_cta_seconds") and "captions.youtube.srt" not in names:
        findings.append("có intro CTA nhưng thiếu captions.youtube.srt")
    if "thumbnail-1280x720.jpg" not in names:
        findings.append("thiếu thumbnail-1280x720.jpg")

    return {"ok": not findings, "findings": findings, "warnings": warnings}


def _json(runner: Runner, path: str) -> list | dict | None:
    try:
        return json.loads(remote.remote_text(runner, path, REMOTE_TIMEOUT_S))
    except (remote.RemoteError, ValueError, OSError):
        return None

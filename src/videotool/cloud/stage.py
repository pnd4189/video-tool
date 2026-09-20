"""`videotool cloud stage`: lint-gated staging of a Kaggle render, no agent needed at watch time.

source -> lint (must be 0 errors) -> guards (repo, Drive modules, kernel, both config files,
checkpoint, template) -> upload creative (+ template) -> write the runtime's config (never
`repo_ref`) -> state=staged -> "open kernel X, Save & Run All". Every guard is read-only and runs
before the first write, so a blocked stage leaves nothing behind on Drive.
"""

from __future__ import annotations

import json
import re
import tempfile
import time
from pathlib import Path

import yaml

from videotool.cloud import remote
from videotool.cloud.config import CLOUD_MODULES, GITHUB_REMOTE, KERNELS, RUNTIMES, config_name, shared_root
from videotool.cloud.finish import _points_at, _read_config
from videotool.cloud.remote import Runner
from videotool.creative.lint import lint
from videotool.runs import state as run_state
from videotool.runs.notify import notify


def _default_slug(source: str, series: str | None) -> str:
    m = re.search(r"[Cc]hap\s*(\d+)", source)
    chap = m.group(1) if m else re.sub(r"\W+", "-", source.strip("/").split("/")[-1]).strip("-").lower()
    return f"{series or 'ep'}-chap{chap}"


def _expected_seconds(summary: dict) -> float | None:
    """Intro CTA + narration + outro CTA; None when a CTA length is unknown (verify then skips
    the duration check instead of failing a good render)."""
    parts = [summary.get("intro_cta_seconds"), summary.get("voice_seconds"), summary.get("outro_cta_seconds")]
    return None if any(p is None for p in parts) else float(sum(parts))


def stage(
    source: str,
    creative_path: Path,
    runtime: str = "tpu",
    slug: str | None = None,
    scene_workers: int | None = None,
    resume: bool = False,
    dry_run: bool = False,
    template: Path | None = None,
    runner: Runner = remote.real_runner,
) -> int:
    """Returns a process exit code: 0 staged (or dry-run plan), 1 blocked, 2 bad usage."""
    if runtime not in RUNTIMES:
        print(f"runtime must be one of {RUNTIMES}")
        return 2
    creative = yaml.safe_load(Path(creative_path).read_text(encoding="utf-8")) or {}
    title = str((creative.get("project") or {}).get("title", ""))

    print(f"lint: {source}")
    report = lint(source, Path(creative_path))
    for line in report.errors:
        print(f"ERROR   {line}")
    if report.errors:
        return 1
    for line in report.warnings:
        print(f"WARNING {line} (chấp nhận khi stage)")

    summary = report.summary
    slug = slug or _default_slug(source, summary.get("series"))
    shared = shared_root()
    kernel, cfg_name = KERNELS[runtime], config_name(runtime)
    expected = _expected_seconds(summary)
    print(f"slug {slug} · {kernel} · {cfg_name} · kỳ vọng "
          f"{f'{expected:.1f}s' if expected else 'không rõ (thiếu độ dài CTA)'}")

    violations = _guards(runner, shared, runtime, slug, title, resume, source, template)
    for problem in violations:
        print(f"BLOCK   {problem}")
    if violations and not dry_run:
        return 1

    config = {
        "source": source,
        "output": f"{source.rstrip('/')}/outputs",
        "checkpoint": f"{shared}/checkpoints/{slug}",
        "creative": f"{shared}/creative/{slug}.yaml",
    }
    if runtime == "tpu":
        config["allow_cpu"] = True
        config["scene_workers"] = scene_workers or 32

    if dry_run:
        print("--dry-run: sẽ làm:")
        print(f"  - upload {creative_path} -> {config['creative']}")
        if template:
            print(f"  - upload template {Path(template).name} -> {source}/ (nếu chưa có)")
        print(f"  - write {shared}/{cfg_name}: {json.dumps(config, ensure_ascii=False)}")
        print(f"  - state {run_state.path_for(slug)}: staged")
        if violations:
            print("--dry-run: nhưng sẽ BỊ CHẶN vì các lý do BLOCK ở trên")
        return 1 if violations else 0

    remote.write_remote_file(runner, Path(creative_path), config["creative"])
    if template and _remote_template(runner, source, Path(template)) is None:
        remote.write_remote_file(runner, Path(template), f"{source.rstrip('/')}/{Path(template).name}")
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as fh:
        json.dump(config, fh, ensure_ascii=False, indent=2)
        tmp = Path(fh.name)
    remote.write_remote_file(runner, tmp, f"{shared}/{cfg_name}")
    tmp.unlink()

    run_state.save(run_state.new(
        slug, source=source, output=config["output"], checkpoint=config["checkpoint"],
        creative=config["creative"], runtime=runtime, kernel=kernel, config_name=cfg_name,
        title=title, voice_seconds=summary.get("voice_seconds"),
        intro_cta_seconds=summary.get("intro_cta_seconds"), outro_cta_seconds=summary.get("outro_cta_seconds"),
        expected_seconds=expected, scenes=summary.get("scenes"), chapters=summary.get("chapters"),
        staged_at=time.time(),
    ))
    print(f"Đã stage {slug}. Mở kernel {kernel} → Save & Run All. watchd sẽ canh và báo.")
    st = run_state.load(slug)
    if st:
        notify(runner, st, "staged", f"[{slug}] đã stage — mở Kaggle bấm Save & Run All ({kernel})")
    return 0


def _slug_of(config: dict) -> str:
    return str(config.get("checkpoint", "?")).rstrip("/").rsplit("/", 1)[-1]


def _guards(runner: Runner, shared: str, runtime: str, slug: str, title: str, resume: bool,
            source: str, template: Path | None) -> list[str]:
    """Every reason not to stage, collected read-only before anything is written."""
    problems: list[str] = []
    gh, local = remote.github_head(runner), remote.local_origin_main(runner)
    if gh is None:
        problems.append(f"không ls-remote được {GITHUB_REMOTE} (riêng tư? mạng?) — box sẽ chết lúc pip")
    elif gh != local:
        problems.append(f"main local ({local}) ≠ origin/main ({gh}) — fetch/push trước khi stage")

    for module in CLOUD_MODULES:
        name = Path(module).name
        remote_md5 = remote.md5_on_remote(runner, f"{shared}/{name}")
        if remote_md5 is None:
            problems.append(f"chưa đọc được md5 của {name} trên Drive (thiếu file, hoặc Drive chưa tính "
                            "hash) — thử lại sau vài phút; thiếu thì deploy")
        elif remote_md5 != remote.md5_of_blob(runner, module):
            problems.append(f"{name} trên Drive không khớp origin/main — deploy lại")

    kernel = KERNELS[runtime]
    status = remote.kernel_status(runner, kernel)
    if status in ("queued", "running"):
        problems.append(f"kernel {kernel} đang {status} — không stage đè")
    elif status is None:
        problems.append(f"không đọc được trạng thái kernel {kernel}")

    mine = _read_config(runner, f"{shared}/{config_name(runtime)}")
    if mine and not _points_at(mine, slug):
        problems.append(f"{config_name(runtime)} đang giữ tập {_slug_of(mine)} (chưa chạy, hoặc giữ để "
                        f"resume) — xong tập đó hoặc `videotool cloud finish {_slug_of(mine)}` trước")
    other = "tpu" if runtime == "gpu" else "gpu"
    theirs = _read_config(runner, f"{shared}/{config_name(other)}")
    if theirs and _points_at(theirs, slug):
        problems.append(f"{config_name(other)} (kernel {other}) đang trỏ đúng tập {slug} này")

    if not resume:
        problems += _foreign_checkpoint(runner, shared, slug, title)
    if template:
        existing = _remote_template(runner, source, Path(template))
        if existing is not None and existing != Path(template).read_text(encoding="utf-8"):
            problems.append(f"template {Path(template).name} đã có trên nguồn với nội dung khác — không ghi đè")
    return problems


def _foreign_checkpoint(runner: Runner, shared: str, slug: str, title: str) -> list[str]:
    """A checkpoint under this slug that belongs to another episode (compared by title)."""
    try:
        job = remote.remote_text(runner, f"{shared}/checkpoints/{slug}/job.yaml", 120)
    except remote.RemoteError:
        return []
    old = re.search(r"^  title:\s*\"?(.+?)\"?\s*$", job or "", re.M)
    if old and title and old.group(1).strip() != title.strip():
        return [f"checkpoint {slug} là của '{old.group(1).strip()[:60]}' — dùng --resume để chạy tiếp, "
                "hoặc đổi slug"]
    return []


def _remote_template(runner: Runner, source: str, template: Path) -> str | None:
    """The template already on the source folder, or None when there is none."""
    try:
        return remote.remote_text(runner, f"{source.rstrip('/')}/{template.name}", 120)
    except remote.RemoteError:
        return None

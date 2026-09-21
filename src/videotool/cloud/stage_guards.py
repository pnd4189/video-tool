"""Read-only reasons not to stage a Kaggle render, all collected before `stage` writes anything."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from videotool.cloud import remote
from videotool.cloud.config import CLOUD_MODULES, GITHUB_REMOTE, KERNELS, config_name, gdrive_mount, gdrive_remote
from videotool.cloud.finish import _points_at, _read_config
from videotool.cloud.remote import Runner

REMOTE_SPEC = re.compile(r"^[A-Za-z0-9_.-]+(?:,[^:]*)?:")


def to_remote(source: str) -> str | None:
    """The render box reads Drive only through rclone: a folder on the local gdrive mount becomes its
    `gdrive:` path. Any other local folder cannot reach the box (None). ĐẠO SĨ Chap 22 was staged
    with the mount path and its kernel had nothing to copy."""
    if REMOTE_SPEC.match(source) and not Path(source).exists():
        return source
    path = Path(source).expanduser().resolve()
    mount = gdrive_mount()
    if not path.is_relative_to(mount):
        return None
    rel = path.relative_to(mount).as_posix()
    return gdrive_remote() + ("" if rel == "." else rel)


def slug_of(config: dict) -> str:
    return str(config.get("checkpoint", "?")).rstrip("/").rsplit("/", 1)[-1]


def guards(runner: Runner, shared: str, runtime: str, slug: str, title: str, resume: bool, fresh: bool,
           source: str, template: Path | None) -> tuple[list[str], bool]:
    """(every reason not to stage, whether the checkpoint must be purged first)."""
    problems: list[str] = []
    gh, local = remote.github_head(runner), remote.local_origin_main(runner)
    if gh is None:
        problems.append(f"không ls-remote được {GITHUB_REMOTE} (riêng tư? mạng?) — box sẽ chết lúc pip")
    elif gh != local:
        problems.append(f"main local ({local}) ≠ origin/main ({gh}) — fetch/push trước khi stage")
    unmerged = remote.unmerged_box_code(runner)
    if unmerged:
        problems.append(f"{len(unmerged)} file code chưa lên main ({', '.join(unmerged[:3])}…) — box cài "
                        "videotool từ main nên sẽ chạy code CŨ so với bản lint vừa chạy; push trước")

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
        problems.append(f"{config_name(runtime)} đang giữ tập {slug_of(mine)} (chưa chạy, hoặc giữ để "
                        f"resume) — xong tập đó hoặc `videotool cloud finish {slug_of(mine)}` trước")
    other = "tpu" if runtime == "gpu" else "gpu"
    theirs = _read_config(runner, f"{shared}/{config_name(other)}")
    if theirs and _points_at(theirs, slug):
        problems.append(f"{config_name(other)} (kernel {other}) đang trỏ đúng tập {slug} này")

    checkpoint, purge = checkpoint_problems(runner, shared, slug, title, resume, fresh)
    problems += checkpoint
    if template:
        existing = remote_template(runner, source, Path(template))
        if existing is not None and existing != Path(template).read_text(encoding="utf-8"):
            problems.append(f"template {Path(template).name} đã có trên nguồn với nội dung khác — không ghi đè")
    return problems, purge


def checkpoint_problems(runner: Runner, shared: str, slug: str, title: str, resume: bool,
                        fresh: bool) -> tuple[list[str], bool]:
    """(problems, purge). A checkpoint that already holds this episode's pinned job.yaml makes the
    box RESUME with it and skip the new creative — the ĐS22 intro-card fix could not have landed."""
    try:
        job = remote.remote_text(runner, f"{shared}/checkpoints/{slug}/job.yaml", 120)
    except remote.RemoteError:
        return [], False
    try:  # parsed, not pattern-matched: the box dumps a title holding ": " in single quotes
        old_title = str(((yaml.safe_load(job or "") or {}).get("project") or {}).get("title") or "").strip()
    except yaml.YAMLError:
        old_title = ""
    if old_title and title and old_title != title.strip():
        if resume:
            return [], False
        return [f"checkpoint {slug} là của '{old_title[:60]}' — dùng --resume để chạy tiếp, hoặc đổi --slug "
                "(--fresh không xoá checkpoint của tập khác)"], False
    if resume:
        return [], False
    if fresh:
        return [], True
    return [f"checkpoint {slug} đã có job.yaml ghim từ lần chạy trước — box sẽ RESUME bằng bản đó và bỏ qua "
            "creative mới. --resume: chạy tiếp bản cũ; --fresh: xoá checkpoint của tập này rồi dùng creative mới"], False


def remote_template(runner: Runner, source: str, template: Path) -> str | None:
    """The template already on the source folder, or None when there is none."""
    try:
        return remote.remote_text(runner, f"{source.rstrip('/')}/{template.name}", 120)
    except remote.RemoteError:
        return None

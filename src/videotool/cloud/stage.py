"""`videotool cloud stage`: lint-gated staging of a Kaggle render, no agent needed at watch time.

source -> lint (must be 0 errors) -> guards (repo, Drive modules, kernel, both config files,
checkpoint, template) -> upload creative (+ template) -> write the runtime's config (never
`repo_ref`) -> state=staged -> "open kernel X, Save & Run All". Every guard is read-only and runs
before the first write, so a blocked stage leaves nothing behind on Drive.

One stage per episode at a time (a lock), and the creative is snapshotted first: what was linted is
exactly what gets uploaded, even if the file is edited meanwhile. The last line printed is always
`KẾT QUẢ: …` so an agent quoting the run cannot mistake a blocked stage for a staged one.
"""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import re
import shutil
import tempfile
import time
from pathlib import Path

import yaml

from videotool.cloud import remote
from videotool.cloud.config import KERNELS, RUNTIMES, config_name, shared_root
from videotool.cloud.remote import Runner
from videotool.cloud.stage_guards import guards, remote_template, to_remote
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


@contextlib.contextmanager
def _episode_lock(key: str):
    """True while this process holds the one staging slot for `key`; False when another has it."""
    run_state.ensure_dir()
    path = run_state.state_dir() / f".stage-{hashlib.sha1(key.encode('utf-8')).hexdigest()[:12]}.lock"
    with open(path, "w", encoding="utf-8") as fh:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def _result(code: int, message: str) -> int:
    print(f"KẾT QUẢ: {message}")
    return code


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
    fresh: bool = False,
) -> int:
    """Returns a process exit code: 0 staged (or dry-run plan), 1 blocked, 2 bad usage."""
    if runtime not in RUNTIMES:
        return _result(2, f"CHƯA STAGE — runtime phải là một trong {RUNTIMES}")
    if resume and fresh:
        return _result(2, "CHƯA STAGE — --resume và --fresh loại trừ nhau")
    remote_source = to_remote(source)
    if remote_source is None:
        return _result(2, f"CHƯA STAGE — {source} không nằm trên Drive: box Kaggle chỉ đọc được gdrive:")
    if remote_source != source:
        print(f"source trên mount → box sẽ đọc {remote_source}")
    with _episode_lock(remote_source) as held:
        if not held:
            return _result(1, "CHƯA STAGE — một lệnh stage khác cho tập này đang chạy; chờ nó xong rồi xem "
                              "`videotool renders`")
        with tempfile.TemporaryDirectory(prefix="videotool-stage-") as tmp:
            snapshot = Path(tmp) / "creative.yaml"
            shutil.copy(creative_path, snapshot)
            try:
                code, message = _stage(source, remote_source, snapshot, runtime, slug, scene_workers,
                                       resume, fresh, dry_run, template, runner)
            except remote.RemoteError as exc:
                code, message = 1, (f"CHƯA STAGE — một lệnh ghi Drive lỗi ({exc}); có thể đã ghi một phần, "
                                    "stage lại cùng lệnh")
    return _result(code, message)


def _stage(source: str, remote_source: str, snapshot: Path, runtime: str, slug: str | None,
           scene_workers: int | None, resume: bool, fresh: bool, dry_run: bool, template: Path | None,
           runner: Runner) -> tuple[int, str]:
    creative = yaml.safe_load(snapshot.read_text(encoding="utf-8")) or {}
    title = str((creative.get("project") or {}).get("title", ""))

    print(f"lint: {source}")
    report = lint(source, snapshot, template=Path(template) if template else None)
    for line in report.errors:
        print(f"ERROR   {line}")
    if report.errors:
        return 1, f"CHƯA STAGE — lint có {len(report.errors)} lỗi"
    for line in report.warnings:
        print(f"WARNING {line} (chấp nhận khi stage)")

    summary = report.summary
    slug = slug or _default_slug(remote_source, summary.get("series"))
    shared = shared_root()
    kernel, cfg_name = KERNELS[runtime], config_name(runtime)
    expected = _expected_seconds(summary)
    print(f"slug {slug} · {kernel} · {cfg_name} · kỳ vọng "
          f"{f'{expected:.1f}s' if expected else 'không rõ (thiếu độ dài CTA)'}")

    violations, purge = guards(runner, shared, runtime, slug, title, resume, fresh, remote_source, template)
    for problem in violations:
        print(f"BLOCK   {problem}")
    if violations and not dry_run:
        return 1, f"CHƯA STAGE — {len(violations)} lý do BLOCK ở trên"

    config = {
        "source": remote_source,
        "output": f"{remote_source.rstrip('/')}/outputs",
        "checkpoint": f"{shared}/checkpoints/{slug}",
        "creative": f"{shared}/creative/{slug}.yaml",
    }
    if runtime == "tpu":
        config["allow_cpu"] = True
        config["scene_workers"] = scene_workers or 32

    if dry_run:
        print("--dry-run: sẽ làm:")
        if purge:
            print(f"  - xoá checkpoint {config['checkpoint']} (--fresh)")
        print(f"  - upload creative -> {config['creative']}")
        if template:
            print(f"  - upload template {Path(template).name} -> {remote_source}/ (nếu chưa có)")
        print(f"  - write {shared}/{cfg_name}: {json.dumps(config, ensure_ascii=False)}")
        print(f"  - state {run_state.path_for(slug)}: staged")
        if violations:
            return 1, "DRY-RUN — nhưng sẽ BỊ CHẶN vì các lý do BLOCK ở trên"
        return 0, "DRY-RUN — chưa ghi gì"

    if purge:
        print(f"--fresh: xoá checkpoint {config['checkpoint']}")
        remote.purge_checkpoint(runner, shared, slug)
    remote.write_remote_file(runner, snapshot, config["creative"])
    if template and remote_template(runner, remote_source, Path(template)) is None:
        remote.write_remote_file(runner, Path(template), f"{remote_source.rstrip('/')}/{Path(template).name}")
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as fh:
        json.dump(config, fh, ensure_ascii=False, indent=2)
        tmp = Path(fh.name)
    remote.write_remote_file(runner, tmp, f"{shared}/{cfg_name}")
    tmp.unlink()

    staged_at = time.time()
    st = run_state.new(
        slug, source=remote_source, output=config["output"], checkpoint=config["checkpoint"],
        creative=config["creative"], runtime=runtime, kernel=kernel, config_name=cfg_name,
        title=title, voice_seconds=summary.get("voice_seconds"),
        intro_cta_seconds=summary.get("intro_cta_seconds"), outro_cta_seconds=summary.get("outro_cta_seconds"),
        expected_seconds=expected, scenes=summary.get("scenes"), chapters=summary.get("chapters"),
        creative_sha256=hashlib.sha256(snapshot.read_bytes()).hexdigest(), staged_at=staged_at,
    )
    run_state.save(st)
    print(f"Đã stage {slug}. Mở kernel {kernel} → Save & Run All. watchd sẽ canh và báo.")
    notify(runner, st, "staged", f"[{slug}] đã stage — mở Kaggle bấm Save & Run All ({kernel})")
    return 0, f"ĐÃ STAGE {slug} lúc {time.strftime('%H:%M:%S', time.localtime(staged_at))}"

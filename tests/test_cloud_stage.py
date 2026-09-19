"""Stage: lint gate, guards, config shape per runtime, template handling, state file."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import pytest
import yaml

from videotool.cloud import stage as stage_mod
from videotool.runs import state as run_state

from cloud_fakes import FakeRunner  # noqa: TID252

SOURCE = "gdrive:series/Chap 55"
SHARED = "gdrive:_VIDEOTOOL_SHARED"
OK_MD5 = "0" * 31 + "1"


@dataclass
class FakeLint:
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    summary: dict = field(default_factory=lambda: {"series": "binh-thien", "voice_seconds": 600.0,
                                                   "intro_cta_seconds": 8.7, "outro_cta_seconds": 14.7})
    description: str = ""


def _creative(tmp_path: Path) -> Path:
    path = tmp_path / "creative.yaml"
    path.write_text(yaml.safe_dump({
        "project": {"title": "Bình Thiên Sách Tập 55: Hook"},
        "inputs": {"outro_cta": "CTA voice/Outro CTA - with voice.mp4"},
    }, allow_unicode=True), encoding="utf-8")
    return path


def _ok_runner() -> FakeRunner:
    """A world where every guard passes: public repo, synced main, matching modules, idle kernels."""
    return FakeRunner({
        ("git", "ls-remote"): (0, "abc1234 refs/heads/main\n"),
        ("git", "-C"): (0, ""),  # rev-parse / show both fine at this prefix level
        ("rclone", "md5sum"): (0, f"{OK_MD5}  file\n"),
        ("kaggle", "kernels", "status"): (0, 'k has status "KernelWorkerStatus.COMPLETE"'),
        ("rclone", "cat"): (1, ""),  # no other config, no checkpoint job
        ("hermes", "send"): (0, ""),
    })


def _patch(monkeypatch, tmp_path, report=None):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    monkeypatch.setattr(stage_mod, "lint", lambda source, path: report or FakeLint())
    # identical md5s everywhere: patch md5_of_blob to the fixture value
    monkeypatch.setattr(stage_mod.remote, "md5_of_blob", lambda runner, git_path: OK_MD5)
    monkeypatch.setattr(stage_mod.remote, "github_head", lambda runner: "abc1234")
    monkeypatch.setattr(stage_mod.remote, "local_origin_main", lambda runner: "abc1234")


def test_tpu_writes_the_tpu_config_without_repo_ref(tmp_path, monkeypatch):
    _patch(monkeypatch, tmp_path)
    runner = _ok_runner()
    code = stage_mod.stage(SOURCE, _creative(tmp_path), "tpu", runner=runner)
    assert code == 0
    config = json.loads(runner.uploads[f"{SHARED}/render_job.tpu.json"])
    assert "repo_ref" not in config
    assert config["allow_cpu"] is True and config["scene_workers"] == 32
    assert config["checkpoint"] == f"{SHARED}/checkpoints/binh-thien-chap55"
    st = run_state.load("binh-thien-chap55")
    assert st["status"] == "staged" and st["expected_seconds"] == pytest.approx(600.0 + 8.7 + 14.7)
    assert runner.seen("hermes", "send")


def test_gpu_uses_render_job_json_and_no_cpu_keys(tmp_path, monkeypatch):
    _patch(monkeypatch, tmp_path)
    runner = _ok_runner()
    assert stage_mod.stage(SOURCE, _creative(tmp_path), "gpu", runner=runner) == 0
    assert f"{SHARED}/render_job.json" in runner.uploads
    config = json.loads(runner.uploads[f"{SHARED}/render_job.json"])
    assert "allow_cpu" not in config and "scene_workers" not in config


def test_dry_run_writes_nothing(tmp_path, monkeypatch):
    _patch(monkeypatch, tmp_path)
    runner = _ok_runner()
    assert stage_mod.stage(SOURCE, _creative(tmp_path), "tpu", dry_run=True, runner=runner) == 0
    assert not runner.seen("rclone", "copyto")
    assert run_state.load("binh-thien-chap55") is None


def test_lint_errors_stop_before_any_remote_call(tmp_path, monkeypatch):
    _patch(monkeypatch, tmp_path, FakeLint(errors=["project.title is not in the series title list"]))
    runner = _ok_runner()
    assert stage_mod.stage(SOURCE, _creative(tmp_path), "tpu", runner=runner) == 1
    assert runner.calls == []


def test_busy_kernel_blocks(tmp_path, monkeypatch):
    _patch(monkeypatch, tmp_path)
    runner = _ok_runner()
    busy = {("kaggle", "kernels", "status"): (0, 'k has status "KernelWorkerStatus.RUNNING"')}
    runner.responses.update(busy)
    assert stage_mod.stage(SOURCE, _creative(tmp_path), "tpu", runner=runner) == 1
    assert not runner.seen("rclone", "copyto")


def test_module_md5_mismatch_blocks(tmp_path, monkeypatch):
    _patch(monkeypatch, tmp_path)
    runner = _ok_runner()
    runner.responses[("rclone", "md5sum")] = (0, f"{'f' * 32}  file\n")
    assert stage_mod.stage(SOURCE, _creative(tmp_path), "tpu", runner=runner) == 1


def test_main_ahead_of_origin_blocks(tmp_path, monkeypatch):
    _patch(monkeypatch, tmp_path)
    monkeypatch.setattr(stage_mod.remote, "local_origin_main", lambda runner: "deadbee")
    assert stage_mod.stage(SOURCE, _creative(tmp_path), "tpu", runner=_ok_runner()) == 1


def test_other_runtime_config_same_slug_blocks(tmp_path, monkeypatch):
    _patch(monkeypatch, tmp_path)
    runner = _ok_runner()
    runner.responses[(("rclone", "cat", f"{SHARED}/render_job.json"))] = \
        (0, json.dumps({"checkpoint": f"{SHARED}/checkpoints/binh-thien-chap55"}))
    assert stage_mod.stage(SOURCE, _creative(tmp_path), "tpu", runner=runner) == 1


def test_foreign_checkpoint_blocks_unless_resume(tmp_path, monkeypatch):
    _patch(monkeypatch, tmp_path)
    foreign_job = f"project:\n  title: \"Tập KHÁC\"\n"
    runner = FakeRunner({
        ("git", "ls-remote"): (0, "abc1234 refs/heads/main\n"),
        ("git", "-C"): (0, "abc1234\n"),
        ("rclone", "md5sum"): (0, f"{OK_MD5}  f\n"),
        ("kaggle", "kernels", "status"): (0, 'k has status "KernelWorkerStatus.COMPLETE"'),
        ("rclone", "cat"): (0, foreign_job),
        ("hermes", "send"): (0, ""),
    })
    assert stage_mod.stage(SOURCE, _creative(tmp_path), "tpu", runner=runner) == 1
    assert stage_mod.stage(SOURCE, _creative(tmp_path), "tpu", resume=True, runner=runner) == 0


def test_template_same_content_is_noop_different_content_blocks_before_any_write(tmp_path, monkeypatch):
    _patch(monkeypatch, tmp_path)
    template = tmp_path / "T_DESCRIPTION_TEMPLATE.txt"
    template.write_text("TEMPLATE A", encoding="utf-8")
    runner = _ok_runner()
    runner.responses[("rclone", "cat", f"{SOURCE}/T_DESCRIPTION_TEMPLATE.txt")] = (0, "TEMPLATE A")
    assert stage_mod.stage(SOURCE, _creative(tmp_path), "tpu", template=template, runner=runner) == 0
    assert f"{SOURCE}/T_DESCRIPTION_TEMPLATE.txt" not in runner.uploads  # identical: no re-upload

    runner2 = _ok_runner()
    runner2.responses[("rclone", "cat", f"{SOURCE}/T_DESCRIPTION_TEMPLATE.txt")] = (0, "TEMPLATE B (sửa tay)")
    assert stage_mod.stage(SOURCE, _creative(tmp_path), "tpu", template=template, runner=runner2) == 1
    assert not runner2.seen("rclone", "copyto")  # blocked before the creative was uploaded


def test_absent_template_is_uploaded(tmp_path, monkeypatch):
    _patch(monkeypatch, tmp_path)
    template = tmp_path / "T_DESCRIPTION_TEMPLATE.txt"
    template.write_text("TEMPLATE A", encoding="utf-8")
    runner = _ok_runner()
    assert stage_mod.stage(SOURCE, _creative(tmp_path), "tpu", template=template, runner=runner) == 0
    assert runner.uploads[f"{SOURCE}/T_DESCRIPTION_TEMPLATE.txt"] == "TEMPLATE A"


def test_same_runtime_config_holding_another_episode_blocks(tmp_path, monkeypatch):
    _patch(monkeypatch, tmp_path)
    runner = _ok_runner()
    runner.responses[("rclone", "cat", f"{SHARED}/render_job.tpu.json")] = \
        (0, json.dumps({"checkpoint": f"{SHARED}/checkpoints/binh-thien-chap54"}))
    assert stage_mod.stage(SOURCE, _creative(tmp_path), "tpu", runner=runner) == 1
    assert not runner.seen("rclone", "copyto")


def test_same_runtime_config_of_this_episode_is_restaged(tmp_path, monkeypatch):
    _patch(monkeypatch, tmp_path)
    runner = _ok_runner()
    runner.responses[("rclone", "cat", f"{SHARED}/render_job.tpu.json")] = \
        (0, json.dumps({"checkpoint": f"{SHARED}/checkpoints/binh-thien-chap55"}))
    assert stage_mod.stage(SOURCE, _creative(tmp_path), "tpu", runner=runner) == 0


def test_unreadable_drive_md5_blocks_with_its_own_message(tmp_path, monkeypatch, capsys):
    _patch(monkeypatch, tmp_path)
    runner = _ok_runner()
    runner.responses[("rclone", "md5sum")] = (1, "")
    assert stage_mod.stage(SOURCE, _creative(tmp_path), "tpu", runner=runner) == 1
    assert "chưa đọc được md5" in capsys.readouterr().out


def test_unknown_cta_length_leaves_expected_duration_unknown(tmp_path, monkeypatch):
    _patch(monkeypatch, tmp_path, FakeLint(summary={"series": "binh-thien", "voice_seconds": 600.0,
                                                    "intro_cta_seconds": 8.7, "outro_cta_seconds": None}))
    assert stage_mod.stage(SOURCE, _creative(tmp_path), "tpu", runner=_ok_runner()) == 0
    assert run_state.load("binh-thien-chap55")["expected_seconds"] is None

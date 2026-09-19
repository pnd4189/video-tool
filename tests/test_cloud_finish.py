"""Guarded cleanup: only after a verified publish, an idle kernel, and a config still ours."""

from __future__ import annotations

import json

from videotool.cloud import finish as finish_mod

from cloud_fakes import FakeRunner  # noqa: TID252

SHARED = "gdrive:_VIDEOTOOL_SHARED"
DONE = {"slug": "s", "status": "done", "kernel": "k/1", "config_name": "render_job.json",
        "checkpoint": f"{SHARED}/checkpoints/s"}


def _config(runner_map):
    return {("rclone", "cat"): (0, json.dumps(runner_map))}


def test_deletes_config_when_all_conditions_hold():
    runner = FakeRunner({
        ("kaggle", "kernels", "status"): (0, 'k/1 has status "KernelWorkerStatus.COMPLETE"'),
        **_config({"checkpoint": f"{SHARED}/checkpoints/s"}),
    })
    finish_mod.finish(runner, dict(DONE), SHARED)
    assert runner.seen("rclone", "delete", f"{SHARED}/render_job.json")


def test_refuses_when_kernel_is_busy():
    runner = FakeRunner({
        ("kaggle", "kernels", "status"): (0, 'k/1 has status "KernelWorkerStatus.RUNNING"'),
        **_config({"checkpoint": f"{SHARED}/checkpoints/s"}),
    })
    try:
        finish_mod.finish(runner, dict(DONE), SHARED)
        raise AssertionError("should have refused")
    except finish_mod.RefuseCleanup as exc:
        assert "running" in str(exc)
    assert not runner.seen("rclone", "delete")


def test_refuses_when_config_now_points_elsewhere():
    runner = FakeRunner({
        ("kaggle", "kernels", "status"): (0, 'k/1 has status "KernelWorkerStatus.COMPLETE"'),
        **_config({"checkpoint": f"{SHARED}/checkpoints/OTHER-slug"}),
    })
    try:
        finish_mod.finish(runner, dict(DONE), SHARED)
        raise AssertionError("should have refused")
    except finish_mod.RefuseCleanup as exc:
        assert "khác" in str(exc)
    assert not runner.seen("rclone", "delete")


def test_refuses_when_not_done_and_ignores_missing_config():
    try:
        finish_mod.finish(FakeRunner(), {"slug": "s", "status": "failed", "kernel": "k",
                                         "config_name": "render_job.json"}, SHARED)
        raise AssertionError("should have refused")
    except finish_mod.RefuseCleanup:
        pass
    runner = FakeRunner({("kaggle", "kernels", "status"): (0, 'k has status "KernelWorkerStatus.COMPLETE"'),
                         ("rclone", "cat"): (1, "")})
    finish_mod.finish(runner, DONE, SHARED)  # config already gone — nothing to do, no raise
    assert not runner.seen("rclone", "delete")


def test_points_at_matches_slug_in_either_field():
    assert finish_mod._points_at({"checkpoint": f"{SHARED}/checkpoints/s"}, "s")
    assert finish_mod._points_at({"creative": f"{SHARED}/creative/s.yaml"}, "s")
    assert not finish_mod._points_at({"checkpoint": f"{SHARED}/checkpoints/s2"}, "s")


def test_refuses_when_kernel_status_is_unreadable():
    runner = FakeRunner({
        ("kaggle", "kernels", "status"): (0, "something the parser does not know"),
        **_config({"checkpoint": f"{SHARED}/checkpoints/s"}),
    })
    try:
        finish_mod.finish(runner, dict(DONE), SHARED)
        raise AssertionError("should have refused")
    except finish_mod.RefuseCleanup as exc:
        assert "không đọc được" in str(exc)
    assert not runner.seen("rclone", "delete")

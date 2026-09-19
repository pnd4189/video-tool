"""The `cloud` / `renders` commands through Typer, the layer users and hooks actually call."""

from __future__ import annotations

from typer.testing import CliRunner

from videotool.cli.main import app
from videotool.runs import state

runner = CliRunner()


def test_bare_renders_prints_the_table(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    result = runner.invoke(app, ["renders"])
    assert result.exit_code == 0 and "không có render nào" in result.output
    st = state.new("bt-chap55", title="Tập 55")
    state.save(st)
    result = runner.invoke(app, ["renders"])
    assert result.exit_code == 0 and "[đang chạy]" in result.output and "bt-chap55" in result.output


def test_renders_status_and_finish_reject_unknown_slugs(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    assert runner.invoke(app, ["renders", "status", "nope"]).exit_code == 2
    assert runner.invoke(app, ["cloud", "finish", "nope"]).exit_code == 2


def test_renders_hook_never_fails(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    result = runner.invoke(app, ["renders", "hook", "--cli", "claude", "--event", "prompt"])
    assert result.exit_code == 0 and result.output == ""


def test_stage_rejects_an_unknown_runtime(tmp_path):
    creative = tmp_path / "creative.yaml"
    creative.write_text("project: {title: T}\n", encoding="utf-8")
    result = runner.invoke(app, ["cloud", "stage", "gdrive:x/Chap 1", "--creative", str(creative),
                                 "--runtime", "cpu"])
    assert result.exit_code == 2

"""`renders hook`: per-CLI formats, seen markers, and never breaking a session."""

from __future__ import annotations

import json

from videotool.runs import state
from videotool.runs import hook as hook_mod

from cloud_fakes import FakeRunner  # noqa: TID252


def _stage(slug: str, status: str = "running", **extra):
    st = state.new(slug, title=f"{slug} title", **extra)
    state.save(st)
    state.transition(st, status)
    state.save(st)
    return st


def test_start_lists_active_and_warns_when_daemon_down(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    _stage("bt-chap55")
    runner = FakeRunner({("systemctl", "--user", "is-active"): (3, "inactive")})
    out = hook_mod.start_context(runner)
    assert "bt-chap55" in out and "không chạy" in out


def test_start_with_daemon_up_has_no_warning(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    _stage("bt-chap55")
    runner = FakeRunner({("systemctl", "--user", "is-active"): (0, "active")})
    assert "CẢNH BÁO" not in hook_mod.start_context(runner)


def test_prompt_reports_only_changes_and_marks_seen(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    _stage("a-chap1")
    first = hook_mod.prompt_context("claude")
    assert "a-chap1" in first
    assert hook_mod.prompt_context("claude") == ""  # nothing new
    _stage("b-chap2")
    second = hook_mod.prompt_context("claude")
    assert "b-chap2" in second and "a-chap1" not in second


def test_prompt_seen_marker_is_per_cli(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    _stage("a-chap1")
    assert hook_mod.prompt_context("claude")
    assert "a-chap1" in hook_mod.prompt_context("agy")  # the other CLI still gets its news


def test_output_formats(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    _stage("a-chap1")
    runner = FakeRunner({("systemctl", "--user", "is-active"): (0, "active")})
    claude = json.loads(hook_mod.hook_output("claude", "start", "", runner))
    assert "additionalContext" in claude["hookSpecificOutput"]
    agy = json.loads(hook_mod.hook_output("agy", "start", "", runner))
    assert agy["injectSteps"][0]["ephemeralMessage"]


def test_auto_event_reads_the_agy_payload(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    assert hook_mod.choose_event("agy", json.dumps({"invocationNum": 1})) == "start"
    assert hook_mod.choose_event("agy", json.dumps({"invocationNum": 4})) == "prompt"
    assert hook_mod.choose_event("agy", "not-json") == "prompt"
    assert hook_mod.choose_event("claude", "") == "prompt"


def test_silent_when_no_news_and_never_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    (tmp_path / "videotool/renders").mkdir(parents=True)
    (tmp_path / "videotool/renders/broken.json").write_text("{", encoding="utf-8")
    runner = FakeRunner()
    assert hook_mod.hook_output("claude", "start", "", runner) == ""
    assert hook_mod.hook_output("agy", "prompt", "", runner) == ""


def test_fast_entry_point_always_exits_zero(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    assert hook_mod.main(["--cli", "bogus"]) == 0          # bad args: swallowed
    assert hook_mod.main(["--cli", "claude", "--event", "prompt"]) == 0  # no renders: silent
    assert capsys.readouterr().out == ""
    _stage("a-chap1")
    assert hook_mod.main(["--cli", "claude", "--event", "prompt"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert "a-chap1" in out["hookSpecificOutput"]["additionalContext"]


def test_prompt_surfaces_a_render_that_just_finished(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    st = _stage("a-chap1")
    assert hook_mod.prompt_context("claude")
    import time as _time
    _time.sleep(1.1)  # updated_at must move past the seen marker's 1s tolerance
    state.transition(st, "done", "verify ĐẠT")
    state.save(st)
    news = hook_mod.prompt_context("claude")
    assert "a-chap1" in news and "done" in news

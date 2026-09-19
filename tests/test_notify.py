"""Notification fallback chain: Telegram → desktop → recorded in the state file."""

from __future__ import annotations

from videotool.runs import notify as notify_mod
from videotool.runs import state

from cloud_fakes import FakeRunner  # noqa: TID252


def test_hermes_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    runner = FakeRunner({("hermes", "send"): (0, "")})
    st = state.new("s")
    notify_mod.notify(runner, st, "done", "xong")
    assert runner.seen("hermes", "send", "--to", "telegram")
    assert st["last_channel"] == "telegram" and "undelivered" not in st


def test_notify_send_fallback(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    runner = FakeRunner({("hermes", "send"): (1, "boom"), ("notify-send",): (0, "")})
    st = state.new("s")
    notify_mod.notify(runner, st, "done", "xong")
    assert runner.seen("notify-send") and st["last_channel"] == "notify-send"


def test_undelivered_is_recorded_and_never_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    runner = FakeRunner({("hermes", "send"): (1, "boom"), ("notify-send",): (1, "nope")})
    st = state.new("s")
    notify_mod.notify(runner, st, "done", "xong")
    assert st["undelivered"][-1]["message"] == "xong"
    assert st["last_event"]["detail"] == "xong"


def test_each_event_notified_once(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    runner = FakeRunner()
    st = state.new("s")
    notify_mod.notify(runner, st, "started", "chạy rồi")
    calls = len(runner.calls)
    notify_mod.notify(runner, st, "started", "chạy rồi")
    assert len(runner.calls) == calls  # duplicate suppressed
    notify_mod.notify(runner, st, "done", "xong")  # a different event goes out
    assert len(runner.calls) > calls

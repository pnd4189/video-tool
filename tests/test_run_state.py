"""Render state files: atomic writes, transitions, listing, summaries."""

from __future__ import annotations

import json

from videotool.runs import state


def test_save_load_roundtrip_and_atomicity(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    st = state.new("bt-chap55", title="Tập 55")
    state.save(st)
    assert state.load("bt-chap55")["title"] == "Tập 55"
    assert not list((tmp_path / "videotool/renders").glob("*.tmp"))


def test_load_returns_none_for_missing_or_corrupt(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    assert state.load("nope") is None
    state.ensure_dir()
    state.path_for("broken").write_text("{not json", encoding="utf-8")
    assert state.load("broken") is None


def test_transition_records_history_once(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    st = state.new("s")
    assert state.transition(st, "running", "kernel lên máy")
    assert not state.transition(st, "running")
    assert st["history"][0]["to"] == "running" and st["history"][0]["note"]


def test_list_states_filters_status_and_corrupt(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    for slug in ("a", "b", "c"):
        state.save(state.new(slug))
    state.save({**state.load("b"), "status": "done"})
    state.path_for("broken").write_text("[]", encoding="utf-8")
    assert [s["slug"] for s in state.list_states()] == ["a", "c"]
    assert [s["slug"] for s in state.list_states(statuses=("done",))] == ["b"]


def test_already_notified_guards_events(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    st = state.new("s")
    assert not state.already_notified(st, "done")
    state.record_event(st, "done")
    assert state.already_notified(st, "done")


def test_summary_line_compacts_the_essentials(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    st = state.new("bt-chap55", title="Tập 55", status="running")
    st["progress"] = {"clips": 120}
    line = state.summary_line(st)
    assert "bt-chap55" in line and "Tập 55" in line and "running" in line and "120 clip" in line

from pathlib import Path

from videotool.gui.queue import RenderQueue


def test_cancel_pending_job(monkeypatch, tmp_path: Path) -> None:
    queue = RenderQueue()
    monkeypatch.setattr("threading.Thread.start", lambda self: None)
    state = queue.enqueue_job(tmp_path / "job.yaml", [])
    assert queue.cancel_job(state.job_id) is True
    assert queue.get_job_status(state.job_id).status == "canceled"

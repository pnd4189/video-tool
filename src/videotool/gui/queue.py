from __future__ import annotations

import threading
import uuid
from pathlib import Path

from videotool.core.services import run_render
from videotool.gui.state import RenderJobState


class RenderQueue:
    def __init__(self) -> None:
        self.jobs: dict[str, RenderJobState] = {}
        self._lock = threading.Lock()
        self._active = False

    def enqueue_job(self, job_path: Path, presets: list[str]) -> RenderJobState:
        state = RenderJobState(str(uuid.uuid4()), job_path, presets)
        with self._lock:
            self.jobs[state.job_id] = state
        threading.Thread(target=self._run_next, daemon=True).start()
        return state

    def cancel_job(self, job_id: str) -> bool:
        state = self.jobs.get(job_id)
        if state and state.status == "pending":
            state.status = "canceled"
            return True
        return False

    def get_job_status(self, job_id: str) -> RenderJobState | None:
        return self.jobs.get(job_id)

    def _run_next(self) -> None:
        with self._lock:
            if self._active:
                return
            self._active = True
        try:
            while True:
                pending = next((job for job in self.jobs.values() if job.status == "pending"), None)
                if not pending:
                    return
                pending.status = "running"
                try:
                    run_render(pending.job_path, pending.presets or None)
                    pending.status = "completed"
                except Exception as exc:  # GUI boundary maps service errors into state.
                    pending.status = "failed"
                    pending.error = str(exc)
        finally:
            with self._lock:
                self._active = False

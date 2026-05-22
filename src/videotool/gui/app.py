from __future__ import annotations

from pathlib import Path

from videotool.gui.queue import RenderQueue

queue = RenderQueue()


def create_app():
    try:
        from fastapi import FastAPI, Form
        from fastapi.responses import HTMLResponse
    except ImportError as exc:
        raise RuntimeError("Install GUI extras first: pip install -e '.[gui]'") from exc

    app = FastAPI(title="VideoTool")

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return """
        <form method="post" action="/queue">
          <input name="job_path" placeholder="/path/to/job.yaml" />
          <button type="submit">Queue render</button>
        </form>
        """

    @app.post("/queue")
    def enqueue(job_path: str = Form(...)) -> dict[str, str]:
        state = queue.enqueue_job(Path(job_path), [])
        return {"job_id": state.job_id, "status": state.status}

    @app.get("/queue/{job_id}")
    def status(job_id: str) -> dict[str, object]:
        state = queue.get_job_status(job_id)
        return state.__dict__ if state else {"error": "not found"}

    return app


def launch_gui() -> None:
    import uvicorn

    uvicorn.run(create_app(), host="127.0.0.1", port=8765)

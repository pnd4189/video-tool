from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class RenderJobState:
    job_id: str
    job_path: Path
    presets: list[str]
    status: str = "pending"
    log: list[str] = field(default_factory=list)
    error: str = ""

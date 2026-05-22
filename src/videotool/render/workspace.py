from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Workspace:
    root: Path

    @property
    def logs_dir(self) -> Path:
        return self.root / "logs"

    def prepare(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)

    def has_space(self, required_bytes: int = 1_000_000_000) -> bool:
        return shutil.disk_usage(self.root.parent).free >= required_bytes

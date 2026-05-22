from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class QualityCheck:
    name: str
    status: str
    message: str


def write_quality_report(checks: list[QualityCheck], output_path: Path) -> None:
    output_path.write_text(json.dumps([asdict(check) for check in checks], indent=2), encoding="utf-8")

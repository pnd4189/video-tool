from __future__ import annotations

import hashlib
import json
from pathlib import Path


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_package_manifest(files: list[Path], source_job: Path, output_path: Path) -> None:
    # Snapshot inputs before any I/O so the manifest never tries to hash itself mid-write
    # or any file that disappears during the package step.
    resolved_output = output_path.resolve()
    snapshot = [
        path for path in files
        if path.exists() and path.resolve() != resolved_output
    ]
    payload = {
        "source_job": str(source_job),
        "files": [
            {"path": str(path), "sha256": file_sha256(path), "bytes": path.stat().st_size}
            for path in snapshot
        ],
    }
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

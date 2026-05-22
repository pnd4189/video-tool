from __future__ import annotations

import shutil
from datetime import date
from pathlib import Path

from videotool.assets.library import AssetLibrary, AssetRecord, load_asset_index, save_asset_index


def import_local_asset(
    source_path: Path,
    library_root: Path,
    asset_type: str,
    asset_id: str,
    metadata: dict[str, object] | None = None,
    copy_file: bool = True,
) -> AssetRecord:
    metadata = metadata or {}
    target_dir = library_root / f"{asset_type}s"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / source_path.name
    if copy_file:
        shutil.copy2(source_path, target)
    record = AssetRecord(
        id=asset_id,
        path=target.relative_to(library_root),
        type=asset_type,  # type: ignore[arg-type]
        imported_at=date.today().isoformat(),
        **metadata,
    )
    index_path = library_root / "asset-index.yaml"
    library = load_asset_index(index_path)
    records = [existing for existing in library.records if existing.id != asset_id]
    records.append(record)
    save_asset_index(AssetLibrary(records=records), index_path)
    return record

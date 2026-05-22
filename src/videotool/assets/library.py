from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator


class AssetRecord(BaseModel):
    id: str = Field(min_length=1)
    path: Path
    type: Literal["video", "image", "music", "sfx", "overlay", "font"]
    tags: list[str] = Field(default_factory=list)
    source_url: str = ""
    author: str = ""
    license: str = ""
    commercial_ok: bool | None = None
    attribution_required: bool = False
    attribution_text: str = ""
    content_id_risk: Literal["low", "medium", "high", "unknown"] = "unknown"
    imported_at: str = ""

    @field_validator("path")
    @classmethod
    def relative_path_only(cls, value: Path) -> Path:
        if value.is_absolute() or ".." in value.parts:
            raise ValueError("Asset path must stay inside the asset library.")
        return value


class AssetLibrary(BaseModel):
    records: list[AssetRecord] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_ids(self) -> "AssetLibrary":
        ids = [record.id for record in self.records]
        if len(ids) != len(set(ids)):
            raise ValueError("Asset ids must be unique.")
        return self

    def by_type(self, asset_type: str) -> list[AssetRecord]:
        return [record for record in self.records if record.type == asset_type]


def load_asset_index(path: Path) -> AssetLibrary:
    if not path.exists():
        return AssetLibrary()
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    if isinstance(data, dict):
        data = data.get("assets", [])
    return AssetLibrary(records=[AssetRecord.model_validate(item) for item in data])


def validate_asset_paths(library: AssetLibrary, library_root: Path) -> list[str]:
    root = library_root.resolve()
    errors: list[str] = []
    for record in library.records:
        resolved = (root / record.path).resolve()
        if not resolved.is_relative_to(root):
            errors.append(f"Asset path escapes library root: {record.id}")
    return errors


def save_asset_index(library: AssetLibrary, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"assets": [record.model_dump(mode="json") for record in library.records]}
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

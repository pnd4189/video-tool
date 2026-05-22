from pathlib import Path

from videotool.assets.library import load_asset_index


def test_asset_index_loads() -> None:
    library = load_asset_index(Path("examples/assets/asset-index.yaml"))
    assert library.records[0].id == "broll-city-001"
    assert library.by_type("video")

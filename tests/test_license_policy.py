from videotool.assets.library import AssetRecord
from videotool.assets.licenses import validate_asset_policy


def test_strict_policy_blocks_missing_license() -> None:
    record = AssetRecord(id="local-1", path="clip.mp4", type="video")
    issues = validate_asset_policy([record], "licensed-only")
    assert issues
    assert issues[0].severity == "fail"


def test_attribution_text_required_in_strict_attribution() -> None:
    record = AssetRecord(
        id="cc-by-1",
        path="clip.mp4",
        type="video",
        license="cc-by",
        commercial_ok=True,
        attribution_required=True,
    )
    issues = validate_asset_policy([record], "strict-attribution")
    assert issues[0].asset_id == "cc-by-1"


def test_unknown_license_fails_in_licensed_only() -> None:
    record = AssetRecord(id="bad-license", path="clip.mp4", type="video", license="mystery", commercial_ok=True)
    issues = validate_asset_policy([record], "licensed-only")
    assert any("Unknown license" in issue.message for issue in issues)

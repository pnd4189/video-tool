from __future__ import annotations

from dataclasses import dataclass

from videotool.core.errors import LicensePolicyError

KNOWN_LICENSES = {"cc0", "cc-by", "pexels", "pixabay", "youtube-audio-library", "original", "licensed"}


@dataclass(frozen=True)
class LicenseIssue:
    asset_id: str
    severity: str
    message: str


def validate_asset_policy(records: list[object], policy: str) -> list[LicenseIssue]:
    issues: list[LicenseIssue] = []
    for record in records:
        asset_id = getattr(record, "id")
        license_name = getattr(record, "license", "")
        commercial_ok = getattr(record, "commercial_ok", None)
        attribution_required = getattr(record, "attribution_required", False)
        content_id_risk = getattr(record, "content_id_risk", "unknown")
        if policy == "licensed-only" and (not license_name or commercial_ok is not True):
            issues.append(LicenseIssue(asset_id, "fail", "Missing license or commercial-use approval."))
        if policy == "licensed-only" and license_name and license_name not in KNOWN_LICENSES:
            issues.append(LicenseIssue(asset_id, "fail", f"Unknown license '{license_name}'."))
        if policy == "strict-attribution" and attribution_required and not getattr(record, "attribution_text", ""):
            issues.append(LicenseIssue(asset_id, "fail", "Attribution is required but attribution_text is empty."))
        if content_id_risk == "high":
            issues.append(LicenseIssue(asset_id, "warning", "High Content ID risk recorded."))
    return issues


def raise_on_blocking_issues(issues: list[LicenseIssue]) -> None:
    blocked = [issue for issue in issues if issue.severity == "fail"]
    if blocked:
        details = "; ".join(f"{issue.asset_id}: {issue.message}" for issue in blocked)
        raise LicensePolicyError(details)

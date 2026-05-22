from __future__ import annotations

from pathlib import Path

from videotool.assets.library import AssetLibrary
from videotool.assets.licenses import LicenseIssue


def write_license_report(library: AssetLibrary, output_path: Path, issues: list[LicenseIssue] | None = None) -> None:
    issues = issues or []
    lines = [
        "# License Report",
        "",
        "This report records provided license metadata. It does not guarantee platform claim-free upload.",
        "",
    ]
    for record in library.records:
        lines.extend(
            [
                f"## {record.id}",
                f"- Path: {record.path}",
                f"- Type: {record.type}",
                f"- Source: {record.source_url or 'not recorded'}",
                f"- Author: {record.author or 'not recorded'}",
                f"- License: {record.license or 'not recorded'}",
                f"- Commercial OK: {record.commercial_ok}",
                f"- Attribution: {record.attribution_text or 'not required/recorded'}",
                f"- Content ID risk: {record.content_id_risk}",
                "",
            ]
        )
    if issues:
        lines.extend(["## Issues", ""])
        lines.extend(f"- {issue.severity.upper()} {issue.asset_id}: {issue.message}" for issue in issues)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

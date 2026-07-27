"""setup() must build a valid pip spec for every documented ``repo_ref`` form.

A bare ``@main`` used to reach pip as ``"@main[ai]"`` -> ``Invalid requirement`` and abort the
render at ``vc.setup()`` before stage-in (ĐẠO SĨ Chap 18 ver 12, 2026-07-27). The fix expands a
bare ``@ref`` to the default repo's git URL; the git+/whl/package-name paths stay as they were.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Colab"))

import videotool_cloud as vc  # noqa: E402


def _videotool_spec(monkeypatch, repo_ref: str) -> str:
    """Capture the videotool pip spec setup() builds, without running pip."""
    seen: list[str] = []
    monkeypatch.setattr(vc, "_pip_install", lambda spec, wheelhouse=None: seen.append(spec))
    # ffmpeg is present on the cloud box; keep setup() past its post-install check.
    monkeypatch.setattr(vc.shutil, "which", lambda name: "/usr/bin/ffmpeg")
    vc.setup(repo_ref=repo_ref)
    # setup() installs videotool first, then faster-whisper; the videotool spec is index 0.
    return seen[0]


def test_bare_ref_expands_to_default_repo_url(monkeypatch) -> None:
    # "@main" must NOT reach pip as "@main[ai]"; expand to the default repo's git URL.
    assert _videotool_spec(monkeypatch, "@main") == \
        "videotool[ai] @ git+https://github.com/pnd4189/video-tool@main"


def test_bare_sha_ref_expands(monkeypatch) -> None:
    assert _videotool_spec(monkeypatch, "@abc123def") == \
        "videotool[ai] @ git+https://github.com/pnd4189/video-tool@abc123def"


def test_git_url_spec_unchanged(monkeypatch) -> None:
    assert _videotool_spec(monkeypatch, "git+https://github.com/pnd4189/video-tool@main") == \
        "videotool[ai] @ git+https://github.com/pnd4189/video-tool@main"


def test_whl_spec_unchanged(monkeypatch) -> None:
    assert _videotool_spec(monkeypatch, "/w/videotool-1.0-py3-none-any.whl") == \
        "/w/videotool-1.0-py3-none-any.whl[ai]"

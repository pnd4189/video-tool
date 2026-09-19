"""The Kaggle notebooks import the cloud modules BEFORE `videotool_cloud.setup()` installs the
videotool package. A module-level `import videotool…` in those modules, or importing
`cloud_director` (which needs the package) before setup, kills the render box with an ImportError.
"""

from __future__ import annotations

import ast
from pathlib import Path

COLAB = Path(__file__).resolve().parents[1] / "Colab"


def _top_level_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    return names


def test_pre_setup_modules_do_not_import_videotool_at_load() -> None:
    for name in ("videotool_cloud.py", "cloud_render_runner.py"):
        imported = _top_level_modules(COLAB / name)
        assert "videotool" not in imported, name
        assert "cloud_director" not in imported, name


def test_render_job_imports_cloud_director_only_after_setup() -> None:
    tree = ast.parse((COLAB / "cloud_render_runner.py").read_text(encoding="utf-8"))
    render_job = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "render_job")
    setup_line = next(
        n.lineno for n in ast.walk(render_job)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "setup"
    )
    import_lines = [
        n.lineno for n in ast.walk(render_job)
        if isinstance(n, ast.Import) and any(a.name == "cloud_director" for a in n.names)
    ]
    assert import_lines, "render_job no longer imports cloud_director"
    assert all(line > setup_line for line in import_lines)

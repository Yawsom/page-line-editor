"""Guard the repository-wide production docstring convention."""

from __future__ import annotations

import ast
from pathlib import Path


def _production_python_files() -> tuple[Path, ...]:
    """Return production Python modules, the legacy CLI, and repository scripts."""
    return (
        Path("align_report.py"),
        *sorted(Path("scripts").glob("*.py")),
        *sorted(Path("src").rglob("*.py")),
    )


def test_every_production_callable_has_a_docstring() -> None:
    """Require documentation for every function and method shipped by the project."""
    missing: list[str] = []
    for path in _production_python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if ast.get_docstring(node, clean=False) is None:
                missing.append(f"{path}:{node.lineno}: {node.name}")
    assert not missing, "Production callables without docstrings:\n" + "\n".join(missing)

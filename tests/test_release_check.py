from __future__ import annotations

import importlib.util
from pathlib import Path


def _release_check_module():
    script = Path(__file__).resolve().parents[1] / "scripts" / "check_release.py"
    spec = importlib.util.spec_from_file_location("check_release", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _release_root(tmp_path: Path) -> Path:
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname = 'test-project'\nversion = '0.1.0a1'\n",
        encoding="utf-8",
    )
    (tmp_path / "CHANGELOG.md").write_text(
        "# Changelog\n\n## 0.1.0a1\n",
        encoding="utf-8",
    )
    (tmp_path / "LICENSE").write_text("Test license\n", encoding="utf-8")
    return tmp_path


def test_release_check_accepts_matching_alpha_metadata(tmp_path: Path, monkeypatch) -> None:
    module = _release_check_module()
    monkeypatch.setattr(module, "ROOT", _release_root(tmp_path))

    assert module.main(["--tag", "v0.1.0a1"]) == 0


def test_release_check_requires_matching_tag_and_license(tmp_path: Path, monkeypatch) -> None:
    module = _release_check_module()
    root = _release_root(tmp_path)
    (root / "LICENSE").unlink()
    monkeypatch.setattr(module, "ROOT", root)

    assert module.main(["--tag", "v0.1.0a2"]) == 1

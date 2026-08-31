from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location(
    "check_no_private_data", ROOT / "scripts" / "check_no_private_data.py"
)
assert _SPEC is not None and _SPEC.loader is not None
_GUARD = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_GUARD)


def test_generated_html_and_manifest_are_private_except_docs() -> None:
    assert (
        _GUARD.violation("local_data/readme.txt")
        == "content inside a private/generated data directory"
    )
    assert _GUARD.violation("reports/pages/93v.html") == "generated artefact .html"
    assert _GUARD.violation("alignment.json") == "generated correction report"
    assert _GUARD.violation("manifest.json") == "generated correction report"
    assert _GUARD.violation("session.page-editor.json") == "generated editor project file"
    assert _GUARD.violation("docs/user_guide.html") is None
    assert _GUARD.violation("docs/notes.md") is None

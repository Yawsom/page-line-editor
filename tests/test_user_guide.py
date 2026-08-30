from pathlib import Path

import pytest

GUIDE = Path(__file__).parents[1] / "docs" / "user_guide.md"


@pytest.mark.parametrize(
    "documented_control",
    (
        "Ctrl/Command+T",
        "| Pan Canvas | H |",
        "| Select / Edit | V |",
        "| Move Whole Line | M |",
        "| Add Vertex | A |",
        "| Delete Vertex | D |",
        "| Replace Polygon | P |",
        "| Replace Baseline | B |",
        "Up selects the previous",
        "Down selects the next",
        "| Accept selected change | Enter/Return",
        "| Reject selected change | Backspace",
        "Unicode NFC normalization",
        "--corrected-dir",
        "--delete-noise-extras",
        "--delete-all-extras",
    ),
)
def test_user_guide_tracks_user_tools_and_shortcuts(documented_control: str) -> None:
    assert documented_control in GUIDE.read_text(encoding="utf-8")

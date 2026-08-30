from __future__ import annotations

import unicodedata

from page_line_editor.ui.diff_markup import compare_text


def test_compare_text_nfc_treats_equivalent_arabic_as_equal() -> None:
    composed = "café"
    decomposed = unicodedata.normalize("NFD", composed)
    difference = compare_text(decomposed, composed)
    assert difference.before
    assert all(segment.kind == "equal" for segment in difference.before)
    assert all(segment.kind == "equal" for segment in difference.after)

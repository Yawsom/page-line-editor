from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QFrame, QLabel

from page_line_editor.ui.canvas import EditMode
from page_line_editor.ui.main_window import MainWindow
from page_line_editor.ui.panels import ProjectOpenDialog
from page_line_editor.ui.themes import Theme


@dataclass
class SampleLine:
    id: str = "arabic-line"
    text: str = "قديم"
    polygon: tuple[tuple[int, int], ...] = ((10, 10), (190, 10), (190, 80), (10, 80))
    baseline: tuple[tuple[int, int], ...] = ((20, 65), (180, 65))
    diff_text: str = "قديم → جديد"
    proposal_state: str = "applied"
    correction_status: str = "OCR"
    pre_correction_text: str = "قديم"


def make_window(qtbot):  # type: ignore[no-untyped-def]
    window = MainWindow()
    pixmap = QPixmap(220, 120)
    pixmap.fill(Qt.GlobalColor.white)
    window.load_page(pixmap, [SampleLine()])
    qtbot.addWidget(window)
    window.show()
    return window


def test_toolbar_exposes_save_correction_and_geometry_modes(
    qtbot,
) -> None:  # type: ignore[no-untyped-def]
    window = make_window(qtbot)
    assert window.save_action.text() == "Save"
    assert window.correct_page_action.text() == "Auto-correct Page"
    assert set(window.mode_actions) == set(EditMode)
    assert window.polygons_action.isChecked()
    assert window.baselines_action.isChecked()
    assert window.toolBarArea(window.tools_toolbar) == Qt.ToolBarArea.LeftToolBarArea
    assert all(not action.icon().isNull() for action in window.mode_actions.values())


def test_left_tool_palette_switches_canvas_interaction(qtbot) -> None:  # type: ignore[no-untyped-def]
    window = make_window(qtbot)
    window.mode_actions[EditMode.PAN].trigger()
    assert window.canvas.edit_mode is EditMode.PAN
    assert window.mode_actions[EditMode.PAN].isChecked()
    window.mode_actions[EditMode.MOVE_LINE].trigger()
    assert window.canvas.edit_mode is EditMode.MOVE_LINE
    assert window.mode_actions[EditMode.MOVE_LINE].isChecked()


def test_text_commit_and_undo_marks_window_dirty(qtbot) -> None:  # type: ignore[no-untyped-def]
    window = make_window(qtbot)
    item = window.canvas.page_scene.line_items[0]
    item.setSelected(True)
    spy = QSignalSpy(window.lineTextChanged)
    window.canvas.overlay.editor.setPlainText("جديد")
    window.canvas.overlay.commit()
    assert item.adapter.text == "جديد"
    assert not window.undo_stack.isClean()
    assert spy.count() == 1
    window.undo_stack.undo()
    assert item.adapter.text == "قديم"


def test_applied_correction_has_diff_and_revert_signal(
    qtbot,
) -> None:  # type: ignore[no-untyped-def]
    window = make_window(qtbot)
    item = window.canvas.page_scene.line_items[0]
    item.setSelected(True)
    assert window.canvas.overlay.diff_label.text() == "قديم → جديد"
    assert window.canvas.overlay.status_badge.text() == "OCR"
    assert window.canvas.overlay.corrected_label.text() == "قديم"
    assert window.canvas.overlay.original_label.text() == "قديم"
    assert window.canvas.overlay.addition_gutter.text() == "+"
    assert window.canvas.overlay.deletion_gutter.text() == "−"
    assert any(
        color in window.canvas.overlay.diff_card.styleSheet()
        for color in ("#e6ffec", "#12261b")
    )
    assert any(
        color in window.canvas.overlay.status_badge.styleSheet()
        for color in ("#0969da", "#58a6ff")
    )
    assert window.canvas.overlay.reject_button.isVisible()
    spy = QSignalSpy(window.rejectCorrectionRequested)
    window.canvas.overlay.reject_button.click()
    assert spy.count() == 1
    assert spy.at(0)[0] == "arabic-line"


def test_review_panel_shows_correction_above_original_with_removed_tag(
    qtbot,
) -> None:  # type: ignore[no-untyped-def]
    window = make_window(qtbot)
    proposal = SimpleNamespace(
        primary_line_id="arabic-line",
        status=SimpleNamespace(value="EXTRA"),
        after_text=None,
        before_text="نص زائد",
        actionable=True,
        after=(SimpleNamespace(deleted=True),),
    )
    application = SimpleNamespace(
        proposal=proposal,
        decision=SimpleNamespace(value="applied"),
    )
    window.set_correction_review(SimpleNamespace(applications=(application,)))

    card = window.review_panel.findChild(QFrame, "correctionReviewCard")
    assert card is not None
    labels = [label.text() for label in card.findChildren(QLabel)]
    assert "REMOVED" in labels
    assert "Removed from PAGE XML" in labels
    assert "نص زائد" in labels
    addition = card.findChild(QFrame, "reviewAdditionRow")
    deletion = card.findChild(QFrame, "reviewDeletionRow")
    assert addition is not None and deletion is not None
    assert card.layout().indexOf(addition) < card.layout().indexOf(deletion)


def test_removed_line_geometry_disappears_when_scene_refreshes(qtbot) -> None:  # type: ignore[no-untyped-def]
    window = make_window(qtbot)
    assert window.canvas.page_scene.line_item("arabic-line") is not None
    window.refresh_lines([])
    assert window.canvas.page_scene.line_item("arabic-line") is None
    assert not window.canvas.page_scene.line_items


def test_report_only_extra_is_not_mislabeled_as_removed(qtbot) -> None:  # type: ignore[no-untyped-def]
    window = make_window(qtbot)
    proposal = SimpleNamespace(
        primary_line_id="arabic-line",
        status=SimpleNamespace(value="EXTRA"),
        after_text=None,
        before_text="سطر يحتاج مراجعة",
        actionable=False,
        after=(SimpleNamespace(deleted=False),),
    )
    application = SimpleNamespace(
        proposal=proposal,
        decision=SimpleNamespace(value="report_only"),
    )
    window.set_correction_review(SimpleNamespace(applications=(application,)))
    labels = [label.text() for label in window.review_panel.findChildren(QLabel)]

    assert "EXTRA" in labels
    assert "REMOVED" not in labels
    assert "Not automatically removed" in labels


def test_theme_switch_preserves_active_editor_buffer(qtbot) -> None:  # type: ignore[no-untyped-def]
    window = make_window(qtbot)
    window.canvas.page_scene.line_items[0].setSelected(True)
    window.canvas.overlay.editor.setPlainText("غير محفوظ")
    window.set_theme(Theme.DARK)
    window.set_theme(Theme.LIGHT)
    assert window.canvas.overlay.editor.toPlainText() == "غير محفوظ"
    # Do not let qtbot's teardown exercise the real interactive close warning.
    window.canvas.overlay.cancel()


def test_save_commits_active_buffer_before_signal(qtbot) -> None:  # type: ignore[no-untyped-def]
    window = make_window(qtbot)
    item = window.canvas.page_scene.line_items[0]
    item.setSelected(True)
    window.canvas.overlay.editor.setPlainText("محفوظ")
    spy = QSignalSpy(window.saveRequested)
    window.request_save()
    assert item.adapter.text == "محفوظ"
    assert spy.count() == 1
    window.undo_stack.setClean()


def test_project_dialog_accepts_separate_existing_folders(
    qtbot,
    tmp_path,
) -> None:  # type: ignore[no-untyped-def]
    images = tmp_path / "images"
    xml = tmp_path / "page"
    images.mkdir()
    xml.mkdir()
    dialog = ProjectOpenDialog()
    qtbot.addWidget(dialog)
    dialog.image_row.edit.setText(str(images))
    dialog.xml_row.edit.setText(str(xml))
    dialog.audit_row.edit.setText(str(tmp_path / "history"))
    dialog.accept()
    assert dialog.result() == dialog.DialogCode.Accepted
    paths = dialog.paths()
    assert paths.image_directory == images
    assert paths.xml_directory == xml
    assert paths.normalize_nfc is True

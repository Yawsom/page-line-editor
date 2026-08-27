from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QKeySequence, QPixmap
from PySide6.QtTest import QSignalSpy, QTest
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


def make_window(qtbot, line: SampleLine | None = None):  # type: ignore[no-untyped-def]
    window = MainWindow()
    pixmap = QPixmap(220, 120)
    pixmap.fill(Qt.GlobalColor.white)
    window.load_page(pixmap, [line or SampleLine()])
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


@pytest.mark.parametrize("mode", [mode for mode in EditMode if mode is not EditMode.SELECT])
def test_every_line_tool_switches_cleanly_back_to_select(
    qtbot,
    mode: EditMode,
) -> None:  # type: ignore[no-untyped-def]
    window = make_window(qtbot)
    tool_button = window.tools_toolbar.widgetForAction(window.mode_actions[mode])
    select_button = window.tools_toolbar.widgetForAction(
        window.mode_actions[EditMode.SELECT]
    )
    assert tool_button is not None and select_button is not None

    QTest.mouseClick(tool_button, Qt.MouseButton.LeftButton)
    assert window.canvas.edit_mode is mode
    QTest.mouseClick(select_button, Qt.MouseButton.LeftButton)
    assert window.canvas.edit_mode is EditMode.SELECT
    position = window.canvas.mapFromScene(QPointF(80, 45))
    QTest.mouseClick(window.canvas.viewport(), Qt.MouseButton.LeftButton, pos=position)
    assert window.canvas.page_scene.selected_line_item() is not None
    assert window.canvas.page_scene.selected_line_item()._handles  # type: ignore[union-attr]


def test_actual_tool_buttons_edit_then_recover_from_interrupted_pan(qtbot) -> None:  # type: ignore[no-untyped-def]
    window = make_window(qtbot)
    canvas = window.canvas
    item = canvas.page_scene.line_items[0]
    item.setSelected(True)

    add_button = window.tools_toolbar.widgetForAction(
        window.mode_actions[EditMode.ADD_VERTEX]
    )
    select_button = window.tools_toolbar.widgetForAction(
        window.mode_actions[EditMode.SELECT]
    )
    pan_button = window.tools_toolbar.widgetForAction(window.mode_actions[EditMode.PAN])
    assert add_button is not None and select_button is not None and pan_button is not None

    before_count = len(item.adapter.polygon)
    QTest.mouseClick(add_button, Qt.MouseButton.LeftButton)
    add_position = canvas.mapFromScene(QPointF(100, 10))
    QTest.mouseClick(canvas.viewport(), Qt.MouseButton.LeftButton, pos=add_position)
    assert len(item.adapter.polygon) == before_count + 1

    QTest.mouseClick(pan_button, Qt.MouseButton.LeftButton)
    canvas._panning = True
    canvas._pan_button = Qt.MouseButton.LeftButton
    assert canvas._panning
    window.mode_actions[EditMode.SELECT].trigger()
    assert canvas.edit_mode is EditMode.SELECT
    assert not canvas._panning
    line_position = canvas.mapFromScene(QPointF(80, 45))
    QTest.mouseClick(canvas.viewport(), Qt.MouseButton.LeftButton, pos=line_position)
    assert canvas.page_scene.selected_line_item() is item
    assert item._handles
    window.undo_stack.setClean()


def test_geometry_and_transcription_modes_toggle_with_shortcuts(qtbot) -> None:  # type: ignore[no-untyped-def]
    window = make_window(qtbot)
    item = window.canvas.page_scene.line_items[0]
    item.setSelected(True)
    shortcuts = {
        shortcut.toString(QKeySequence.SequenceFormat.PortableText)
        for shortcut in window.transcription_mode_action.shortcuts()
    }
    assert {"Ctrl+T", "Meta+T"} <= shortcuts

    window.transcription_mode_action.trigger()
    assert window.transcription_mode_action.isChecked()
    assert not window.tools_toolbar.isVisible()
    assert not item.show_polygon and not item.show_baseline
    assert item.isVisible() and not item.shape().isEmpty()
    assert not item._handles

    window.transcription_mode_action.trigger()
    assert not window.transcription_mode_action.isChecked()
    assert window.tools_toolbar.isVisible()
    assert item.show_polygon and item.show_baseline
    assert window.canvas.edit_mode is EditMode.SELECT


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
    assert "قديم" in window.canvas.overlay.original_label.text()
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


def test_character_diff_and_accepted_neutral_line(qtbot) -> None:  # type: ignore[no-untyped-def]
    line = SampleLine(text="جديد", pre_correction_text="قديم")
    window = make_window(qtbot, line)
    item = window.canvas.page_scene.line_items[0]
    item.setSelected(True)

    assert window.canvas.overlay.editor.extraSelections()
    assert "line-through" in window.canvas.overlay.original_label.text()
    assert window.canvas.overlay.deletion_row.isVisible()
    assert window.canvas.overlay.status_badge.isVisible()

    line.proposal_state = "accepted"
    window.canvas.overlay.refresh()
    assert not window.canvas.overlay.editor.extraSelections()
    assert not window.canvas.overlay.deletion_row.isVisible()
    assert not window.canvas.overlay.status_badge.isVisible()
    assert not window.canvas.overlay.addition_gutter.text().strip()


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
    assert any("نص&nbsp;زائد" in label for label in labels)
    assert any("line-through" in label for label in labels)
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


def test_kept_review_record_collapses_to_neutral_line(qtbot) -> None:  # type: ignore[no-untyped-def]
    window = make_window(qtbot)
    proposal = SimpleNamespace(
        primary_line_id="arabic-line",
        status=SimpleNamespace(value="OCR"),
        after_text="جديد",
        before_text="قديم",
        actionable=True,
        after=(SimpleNamespace(deleted=False),),
    )
    application = SimpleNamespace(
        proposal=proposal,
        decision=SimpleNamespace(value="kept"),
    )
    window.set_correction_review(SimpleNamespace(applications=(application,)))
    card = window.review_panel.findChild(QFrame, "correctionReviewCard")

    assert card is not None
    assert card.findChild(QFrame, "reviewNeutralRow") is not None
    assert card.findChild(QFrame, "reviewDeletionRow") is None


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

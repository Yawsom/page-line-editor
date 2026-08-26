from __future__ import annotations

from dataclasses import dataclass

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtTest import QSignalSpy

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
    assert window.canvas.overlay.reject_button.isVisible()
    spy = QSignalSpy(window.rejectCorrectionRequested)
    window.canvas.overlay.reject_button.click()
    assert spy.count() == 1
    assert spy.at(0)[0] == "arabic-line"


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

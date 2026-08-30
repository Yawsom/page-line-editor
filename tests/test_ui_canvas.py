from __future__ import annotations

from dataclasses import dataclass

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QPixmap, QUndoStack
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QGraphicsItem

from page_line_editor.ui.canvas import EditMode, ImageLoadError, PageCanvasView


@dataclass
class SampleLine:
    id: str
    text: str
    polygon: tuple[tuple[float, float], ...]
    baseline: tuple[tuple[float, float], ...]
    diff_text: str = ""
    proposal_state: str = ""


def sample_line() -> SampleLine:
    return SampleLine(
        id="line-1",
        text="السلام عليكم",
        polygon=((20, 20), (180, 20), (180, 90), (20, 90)),
        baseline=((30, 75), (170, 75)),
    )


def second_line() -> SampleLine:
    return SampleLine(
        id="line-2",
        text="سطر ثان",
        polygon=((25, 105), (175, 105), (175, 150), (25, 150)),
        baseline=((35, 140), (165, 140)),
    )


def make_view(qtbot):  # type: ignore[no-untyped-def]
    view = PageCanvasView()
    stack = QUndoStack(view)
    view.set_undo_stack(stack)
    pixmap = QPixmap(240, 160)
    pixmap.fill(Qt.GlobalColor.white)
    view.resize(720, 520)
    view.set_page(pixmap, [sample_line()])
    qtbot.addWidget(view)
    view.show()
    qtbot.waitExposed(view)
    return view, stack


@pytest.mark.parametrize("scene_point", [(80, 50), (20, 50), (100, 75)])
def test_polygon_interior_border_and_baseline_select_same_line(
    qtbot,
    scene_point,
) -> None:  # type: ignore[no-untyped-def]
    view, _ = make_view(qtbot)
    view.page_scene.clearSelection()
    viewport_point = view.mapFromScene(QPointF(*scene_point))
    QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=viewport_point)
    selected = view.page_scene.selected_line_item()
    assert selected is not None
    assert selected.adapter.id == "line-1"


def test_selection_shows_rtl_editor_below_geometry(qtbot) -> None:  # type: ignore[no-untyped-def]
    view, _ = make_view(qtbot)
    item = view.page_scene.line_items[0]
    item.setSelected(True)
    qtbot.waitUntil(view.overlay.isVisible)
    view.update_overlay_position()
    lowest_vertex = max(
        view.mapFromScene(QPointF(*point)).y()
        for point in item.polygon + item.baseline
    )
    assert view.overlay.y() - lowest_vertex == 2
    assert view.overlay.editor.layoutDirection() == Qt.LayoutDirection.RightToLeft
    assert view.overlay.editor.toPlainText() == "السلام عليكم"
    assert not view.overlay.deletion_row.isVisible()
    assert not view.overlay.status_badge.isVisible()
    assert not view.overlay.addition_gutter.text().strip()


def test_geometry_edit_is_one_undo_step(qtbot) -> None:  # type: ignore[no-untyped-def]
    view, stack = make_view(qtbot)
    item = view.page_scene.line_items[0]
    before = item.adapter.polygon
    item.insert_vertex("polygon", 1, (100, 20))
    assert stack.count() == 1
    assert len(item.adapter.polygon) == len(before) + 1
    stack.undo()
    assert item.adapter.polygon == before
    stack.redo()
    assert len(item.adapter.polygon) == len(before) + 1


def test_minimum_vertex_constraints_and_replace_shape(
    qtbot,
) -> None:  # type: ignore[no-untyped-def]
    view, stack = make_view(qtbot)
    item = view.page_scene.line_items[0]
    assert item.delete_vertex("baseline", 0) is False
    assert stack.count() == 0
    item.setSelected(True)
    view.set_edit_mode(EditMode.REPLACE_BASELINE)
    view._replacement_points = [(35, 70), (100, 72), (165, 70)]
    assert view.finish_replacement() is True
    assert item.adapter.baseline == ((35.0, 70.0), (100.0, 72.0), (165.0, 70.0))


def test_handles_ignore_view_transform(qtbot) -> None:  # type: ignore[no-untyped-def]
    view, _ = make_view(qtbot)
    item = view.page_scene.line_items[0]
    item.setSelected(True)
    assert item._handles
    flag = QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations
    assert item._handles[0].flags() & flag
    original_bounds = item._handles[0].boundingRect()
    view.set_zoom(view.zoom_factor * 4)
    assert item._handles[0].boundingRect() == original_bounds


def test_vertex_handle_remains_live_through_drag(qtbot) -> None:  # type: ignore[no-untyped-def]
    view, stack = make_view(qtbot)
    item = view.page_scene.line_items[0]
    item.setSelected(True)
    handle = item._handles[0]
    start = view.mapFromScene(handle.scenePos())
    destination = start + QPointF(24, 18).toPoint()

    QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(view.viewport(), destination, delay=20)
    QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=destination)

    assert item.adapter.polygon[0] != (20.0, 20.0)
    assert stack.count() == 1
    assert not handle.isVisible() or handle in item._handles


def test_editor_font_and_width_follow_selected_geometry(qtbot) -> None:  # type: ignore[no-untyped-def]
    view, _ = make_view(qtbot)
    item = view.page_scene.line_items[0]
    item.setSelected(True)
    view.set_zoom(1.0)
    small_font = view.overlay.editor.font().pixelSize()
    view.set_zoom(2.0)
    large_font = view.overlay.editor.font().pixelSize()
    line_rect = view.mapFromScene(item.sceneBoundingRect()).boundingRect()

    assert large_font > small_font
    assert view.overlay.width() == max(320, line_rect.width())
    assert "\n" not in view.overlay.editor.text()
    view.overlay.editor.setPlainText("سطر\nواحد")
    assert view.overlay.editor.toPlainText() == "سطر واحد"


def test_pan_tool_left_drags_page_background(qtbot) -> None:  # type: ignore[no-untyped-def]
    view, _ = make_view(qtbot)
    view.set_edit_mode(EditMode.PAN)
    view.set_zoom(3.0)
    start = view.mapFromScene(QPointF(220, 140))
    before = view.verticalScrollBar().value()
    QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(view.viewport(), start - QPointF(0, 80).toPoint(), delay=20)
    QTest.mouseRelease(
        view.viewport(),
        Qt.MouseButton.LeftButton,
        pos=start - QPointF(0, 80).toPoint(),
    )
    assert view.verticalScrollBar().value() > before
    assert not view._panning


def test_control_drag_temporarily_pans_from_select_tool(qtbot) -> None:  # type: ignore[no-untyped-def]
    view, _ = make_view(qtbot)
    view.set_zoom(3.0)
    assert view.edit_mode is EditMode.SELECT
    start = view.mapFromScene(QPointF(220, 140))
    before = view.verticalScrollBar().value()
    QTest.mousePress(
        view.viewport(),
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.ControlModifier,
        start,
    )
    QTest.mouseMove(view.viewport(), start - QPointF(0, 80).toPoint(), delay=20)
    QTest.mouseRelease(
        view.viewport(),
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.ControlModifier,
        start - QPointF(0, 80).toPoint(),
    )
    assert view.verticalScrollBar().value() > before
    assert view.edit_mode is EditMode.SELECT


def test_selection_switches_exclusively_and_shift_extends(qtbot) -> None:  # type: ignore[no-untyped-def]
    view, _ = make_view(qtbot)
    pixmap = view.page_scene.image_item.pixmap()  # type: ignore[union-attr]
    view.set_page(pixmap, [sample_line(), second_line()])
    first = view.mapFromScene(QPointF(80, 50))
    second = view.mapFromScene(QPointF(80, 125))

    QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=first)
    assert {item.adapter.id for item in view.page_scene.selectedItems()} == {"line-1"}
    second = view.mapFromScene(QPointF(80, 125))
    QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=second)
    assert {item.adapter.id for item in view.page_scene.selectedItems()} == {"line-2"}
    first = view.mapFromScene(QPointF(80, 50))
    QTest.mouseClick(
        view.viewport(),
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.ShiftModifier,
        first,
    )
    assert {item.adapter.id for item in view.page_scene.selectedItems()} == {
        "line-1",
        "line-2",
    }

    background = view.mapFromScene(QPointF(220, 10))
    QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=background)
    assert not view.page_scene.selectedItems()
    assert not view.overlay.isVisible()


def test_up_and_down_arrows_select_lines_in_page_order(qtbot) -> None:  # type: ignore[no-untyped-def]
    view, _ = make_view(qtbot)
    pixmap = view.page_scene.image_item.pixmap()  # type: ignore[union-attr]
    view.set_page(pixmap, [sample_line(), second_line()])
    first, second = view.page_scene.line_items
    first.setSelected(True)
    view.setFocus()

    QTest.keyClick(view, Qt.Key.Key_Down)
    assert view.page_scene.selected_line_item() is second
    QTest.keyClick(view, Qt.Key.Key_Down)
    assert view.page_scene.selected_line_item() is second
    QTest.keyClick(view, Qt.Key.Key_Up)
    assert view.page_scene.selected_line_item() is first


def test_arrow_navigation_from_editor_commits_text_and_keeps_focus(qtbot) -> None:  # type: ignore[no-untyped-def]
    view, _ = make_view(qtbot)
    pixmap = view.page_scene.image_item.pixmap()  # type: ignore[union-attr]
    view.set_page(pixmap, [sample_line(), second_line()])
    first, second = view.page_scene.line_items
    first.setSelected(True)
    view.activateWindow()
    view.overlay.editor.setFocus()
    qtbot.waitUntil(view.overlay.editor.hasFocus)
    view.overlay.editor.setPlainText("نص معدل")
    spy = QSignalSpy(view.overlay.textCommitRequested)

    QTest.keyClick(view.overlay.editor, Qt.Key.Key_Down)

    assert spy.count() == 1
    assert spy.at(0)[1] == "نص معدل"
    assert view.page_scene.selected_line_item() is second
    assert view.overlay.editor.hasFocus()


def test_arrow_navigation_without_selection_chooses_nearest_boundary(qtbot) -> None:  # type: ignore[no-untyped-def]
    view, _ = make_view(qtbot)
    pixmap = view.page_scene.image_item.pixmap()  # type: ignore[union-attr]
    view.set_page(pixmap, [sample_line(), second_line()])

    view.select_adjacent_line(1)
    assert view.page_scene.selected_line_item() is view.page_scene.line_items[0]
    view.page_scene.clearSelection()
    view.select_adjacent_line(-1)
    assert view.page_scene.selected_line_item() is view.page_scene.line_items[-1]


def test_whole_line_only_moves_with_dedicated_move_tool(qtbot) -> None:  # type: ignore[no-untyped-def]
    view, stack = make_view(qtbot)
    item = view.page_scene.line_items[0]
    start = view.mapFromScene(QPointF(80, 50))
    end = start + QPointF(35, 20).toPoint()
    before = item.adapter.polygon

    QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(view.viewport(), end, delay=20)
    QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=end)
    assert item.adapter.polygon == before
    assert stack.count() == 0

    view.set_edit_mode(EditMode.MOVE_LINE)
    QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(view.viewport(), end, delay=20)
    QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=end)
    assert item.adapter.polygon != before
    assert stack.count() == 1


def test_line_context_menu_exposes_extensible_actions(qtbot) -> None:  # type: ignore[no-untyped-def]
    view, _ = make_view(qtbot)
    item = view.page_scene.line_items[0]
    menu = view.build_line_context_menu(item)
    qtbot.addWidget(menu)
    actions = {action.text(): action for action in menu.actions() if action.text()}

    assert {
        "Edit transcription",
        "Select only",
        "Center on line",
        "Use Move Whole Line tool",
        "Use Add Vertex tool",
        "Copy TextLine ID",
    } <= set(actions)
    actions["Edit transcription"].trigger()
    assert view.page_scene.selected_line_item() is item
    assert view.overlay.editor.textCursor().hasSelection()

    spy = QSignalSpy(view.editModeRequested)
    actions["Use Move Whole Line tool"].trigger()
    assert spy.count() == 1
    assert spy.at(0)[0] is EditMode.MOVE_LINE


def test_null_page_image_is_reported_instead_of_silent_blank(qtbot) -> None:  # type: ignore[no-untyped-def]
    view = PageCanvasView()
    qtbot.addWidget(view)
    with pytest.raises(ImageLoadError, match="Could not decode page image"):
        view.set_page(QPixmap(), [sample_line()])

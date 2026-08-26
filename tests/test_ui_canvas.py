from __future__ import annotations

from dataclasses import dataclass

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QPixmap, QUndoStack
from PySide6.QtTest import QTest
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
    line_bottom = view.mapFromScene(item.sceneBoundingRect().bottomLeft()).y()
    assert view.overlay.y() >= line_bottom
    assert view.overlay.editor.layoutDirection() == Qt.LayoutDirection.RightToLeft
    assert view.overlay.editor.toPlainText() == "السلام عليكم"


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


def test_left_drag_on_page_background_pans_canvas(qtbot) -> None:  # type: ignore[no-untyped-def]
    view, _ = make_view(qtbot)
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


def test_null_page_image_is_reported_instead_of_silent_blank(qtbot) -> None:  # type: ignore[no-untyped-def]
    view = PageCanvasView()
    qtbot.addWidget(view)
    with pytest.raises(ImageLoadError, match="Could not decode page image"):
        view.set_page(QPixmap(), [sample_line()])

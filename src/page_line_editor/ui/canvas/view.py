"""Interactive PAGE image view with zoom, pan, rotation, and geometry tools."""

from __future__ import annotations

import math
from enum import StrEnum

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPen,
    QTransform,
    QUndoStack,
    QWheelEvent,
)
from PySide6.QtWidgets import QGraphicsPathItem, QGraphicsPixmapItem, QGraphicsView

from page_line_editor.domain.geometry import GeometryError, Point, Polygon, Polyline

from ..adapters import Geometry, LineAdapter, PointTuple
from ..commands import GeometryEditCommand
from .line_item import LineGraphicsItem
from .scene import PageScene
from .transcription_overlay import TranscriptionOverlay
from .vertex_handle import VertexHandle


class EditMode(StrEnum):
    SELECT = "select"
    ADD_VERTEX = "add_vertex"
    DELETE_VERTEX = "delete_vertex"
    REPLACE_POLYGON = "replace_polygon"
    REPLACE_BASELINE = "replace_baseline"


def _segment_distance(
    point: QPointF,
    start: PointTuple,
    end: PointTuple,
) -> tuple[float, PointTuple]:
    ax, ay = start
    bx, by = end
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return math.hypot(point.x() - ax, point.y() - ay), start
    t = max(0.0, min(1.0, ((point.x() - ax) * dx + (point.y() - ay) * dy) / (dx * dx + dy * dy)))
    nearest = (ax + t * dx, ay + t * dy)
    return math.hypot(point.x() - nearest[0], point.y() - nearest[1]), nearest


class PageCanvasView(QGraphicsView):
    zoomChanged = Signal(float)
    rotationChanged = Signal(int)
    selectedLineChanged = Signal(object)
    lineGeometryChanged = Signal(str, object, object)
    geometryEditRejected = Signal(str)

    def __init__(self, parent=None) -> None:
        self.page_scene = PageScene(parent)
        super().__init__(self.page_scene, parent)
        self.setObjectName("pageCanvas")
        self.setRenderHints(
            self.renderHints()
            | QPainter.RenderHint.Antialiasing
            | QPainter.RenderHint.SmoothPixmapTransform
        )
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.BoundingRectViewportUpdate)
        self.setBackgroundBrush(Qt.GlobalColor.darkGray)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.viewport().setCursor(Qt.CursorShape.OpenHandCursor)
        self._zoom = 1.0
        self._rotation = 0
        self._mode = EditMode.SELECT
        self._undo_stack: QUndoStack | None = None
        self._panning = False
        self._pan_button: Qt.MouseButton | None = None
        self._pan_last = QPoint()
        self._replacement_points: list[PointTuple] = []
        self._replacement_preview: QGraphicsPathItem | None = None

        self.overlay = TranscriptionOverlay(self.viewport())
        self.page_scene.lineSelected.connect(self._line_selected)
        self.page_scene.geometryEditRequested.connect(self._geometry_edit_requested)
        self.horizontalScrollBar().valueChanged.connect(self.update_overlay_position)
        self.verticalScrollBar().valueChanged.connect(self.update_overlay_position)

    @property
    def edit_mode(self) -> EditMode:
        return self._mode

    @property
    def zoom_factor(self) -> float:
        return self._zoom

    @property
    def view_rotation(self) -> int:
        return self._rotation

    def set_undo_stack(self, stack: QUndoStack) -> None:
        self._undo_stack = stack

    def set_edit_mode(self, mode: EditMode | str) -> None:
        self.cancel_replacement()
        self._mode = EditMode(mode)
        cursor = (
            Qt.CursorShape.CrossCursor
            if self._mode is not EditMode.SELECT
            else Qt.CursorShape.OpenHandCursor
        )
        self.viewport().setCursor(cursor)

    def set_page(self, image, lines, on_change=None) -> None:
        self.overlay.set_line(None)
        self.page_scene.set_page(image, lines, on_change)
        self.reset_rotation()
        self.fit_page()

    def set_overlay_visibility(self, polygons: bool, baselines: bool) -> None:
        self.page_scene.set_overlay_visibility(polygons, baselines)

    def zoom_in(self) -> None:
        self.set_zoom(self._zoom * 1.2)

    def zoom_out(self) -> None:
        self.set_zoom(self._zoom / 1.2)

    def set_zoom(self, zoom: float) -> None:
        self._zoom = min(20.0, max(0.03, zoom))
        self._apply_transform()

    def rotate_left(self) -> None:
        self._rotation = (self._rotation - 90) % 360
        self._apply_transform()
        self.rotationChanged.emit(self._rotation)

    def rotate_right(self) -> None:
        self._rotation = (self._rotation + 90) % 360
        self._apply_transform()
        self.rotationChanged.emit(self._rotation)

    def reset_rotation(self) -> None:
        self._rotation = 0
        self._apply_transform()
        self.rotationChanged.emit(0)

    def fit_page(self) -> None:
        image = self.page_scene.image_item
        if image is None or image.boundingRect().isEmpty():
            return
        rect = image.boundingRect()
        rotated = QTransform().rotate(self._rotation).mapRect(rect)
        available = self.viewport().rect().adjusted(12, 12, -12, -12)
        if available.width() <= 0 or available.height() <= 0:
            return
        self._zoom = min(available.width() / rotated.width(), available.height() / rotated.height())
        self._apply_transform()
        self.centerOn(rect.center())

    def _apply_transform(self) -> None:
        transform = QTransform()
        transform.rotate(self._rotation)
        transform.scale(self._zoom, self._zoom)
        self.setTransform(transform)
        for item in self.page_scene.line_items:
            item.set_view_scale(self._zoom)
        self.zoomChanged.emit(self._zoom)
        self.update_overlay_position()

    def update_overlay_position(self) -> None:
        # Scroll bars can emit once during Qt's C++ teardown after their scene
        # child has already been destroyed.
        try:
            item = self.page_scene.selected_line_item()
        except RuntimeError:
            return
        if item is None or not self.overlay.isVisible():
            return
        line_rect = self.mapFromScene(item.sceneBoundingRect()).boundingRect()
        self.overlay.anchor_below(line_rect, self.viewport().width())

    def ensure_editor_visible(self) -> None:
        item = self.page_scene.selected_line_item()
        if item is None:
            return
        height_scene = max(120.0, self.overlay.sizeHint().height() / max(self._zoom, 0.01))
        rect = item.sceneBoundingRect().united(
            QRectF(
                item.sceneBoundingRect().left(),
                item.sceneBoundingRect().bottom(),
                1,
                height_scene,
            )
        )
        self.ensureVisible(rect, 16, 16)
        self.update_overlay_position()

    def _line_selected(self, item: LineGraphicsItem | None) -> None:
        adapter = item.adapter if item is not None else None
        self.overlay.set_line(adapter)
        if item is not None:
            self.update_overlay_position()
            self.ensure_editor_visible()
        self.selectedLineChanged.emit(adapter)

    def _geometry_edit_requested(
        self,
        item: LineGraphicsItem,
        before: Geometry,
        after: Geometry,
        label: str,
    ) -> None:
        introduced = self._geometry_issues(after) - self._geometry_issues(before)
        if introduced:
            item.set_geometry(*before)
            self.geometryEditRejected.emit("; ".join(sorted(introduced)))
            return

        def notify(adapter: LineAdapter) -> None:
            item.sync_from_adapter()
            self.lineGeometryChanged.emit(adapter.id, adapter.polygon, adapter.baseline)
            self.update_overlay_position()

        if self._undo_stack is not None:
            self._undo_stack.push(GeometryEditCommand(item.adapter, before, after, notify, label))
        else:
            item.adapter.set_geometry(*after)
            notify(item.adapter)

    def _geometry_issues(self, geometry: Geometry) -> set[str]:
        polygon_points, baseline_points = geometry
        issues: set[str] = set()
        try:
            polygon = Polygon(Point(round(x), round(y)) for x, y in polygon_points)
        except GeometryError as error:
            return {str(error)}
        baseline: Polyline | None = None
        if baseline_points:
            try:
                baseline = Polyline(Point(round(x), round(y)) for x, y in baseline_points)
            except GeometryError as error:
                issues.add(str(error))
        if polygon.is_self_intersecting():
            issues.add("Polygon cannot self-intersect")
        image = self.page_scene.image_item
        if image is not None:
            width, height = image.pixmap().width(), image.pixmap().height()
            points = list(polygon.points) + list(baseline.points if baseline else ())
            if any(not (0 <= point.x < width and 0 <= point.y < height) for point in points):
                issues.add("Geometry must remain inside the image")
        if baseline is not None and any(
            not polygon.contains(point) for point in baseline.points
        ):
            issues.add("Baseline must remain inside its line polygon")
        return issues

    def wheelEvent(self, event: QWheelEvent) -> None:
        zoom_modifiers = (
            Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier
        )
        if event.modifiers() & zoom_modifiers:
            self.set_zoom(self._zoom * (1.2 if event.angleDelta().y() > 0 else 1 / 1.2))
            event.accept()
            return
        super().wheelEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.MiddleButton:
            self._begin_pan(event, Qt.MouseButton.MiddleButton)
            return
        if event.button() == Qt.MouseButton.LeftButton and self._mode is EditMode.SELECT:
            clicked = self.itemAt(event.position().toPoint())
            if clicked is None or isinstance(clicked, QGraphicsPixmapItem):
                self._begin_pan(event, Qt.MouseButton.LeftButton)
                return
        if event.button() == Qt.MouseButton.LeftButton and self._mode is not EditMode.SELECT:
            scene_pos = self.mapToScene(event.position().toPoint())
            if self._mode is EditMode.ADD_VERTEX:
                self._add_vertex(scene_pos)
            elif self._mode is EditMode.DELETE_VERTEX:
                self._delete_vertex(event.position().toPoint(), scene_pos)
            else:
                self._add_replacement_point(scene_pos)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._panning:
            current = event.position().toPoint()
            delta = current - self._pan_last
            self._pan_last = current
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - delta.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - delta.y())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._panning and event.button() == self._pan_button:
            self._panning = False
            self._pan_button = None
            cursor = (
                Qt.CursorShape.OpenHandCursor
                if self._mode is EditMode.SELECT
                else Qt.CursorShape.CrossCursor
            )
            self.viewport().setCursor(cursor)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _begin_pan(self, event: QMouseEvent, button: Qt.MouseButton) -> None:
        self._panning = True
        self._pan_button = button
        self._pan_last = event.position().toPoint()
        self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
        event.accept()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if self._mode in (EditMode.REPLACE_POLYGON, EditMode.REPLACE_BASELINE):
            self.finish_replacement()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if self._replacement_points and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.finish_replacement()
            event.accept()
            return
        if self._replacement_points and event.key() == Qt.Key.Key_Escape:
            self.cancel_replacement()
            event.accept()
            return
        super().keyPressEvent(event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.update_overlay_position()

    def _add_vertex(self, position: QPointF) -> None:
        item = self.page_scene.selected_line_item()
        if item is None:
            return
        candidates: list[tuple[float, str, int, PointTuple]] = []
        for kind, points, closed in (
            ("polygon", item.polygon, True),
            ("baseline", item.baseline, False),
        ):
            segment_count = len(points) if closed else max(0, len(points) - 1)
            for index in range(segment_count):
                distance, nearest = _segment_distance(
                    position,
                    points[index],
                    points[(index + 1) % len(points)],
                )
                candidates.append((distance, kind, index + 1, nearest))
        if candidates:
            _, kind, index, nearest = min(candidates, key=lambda candidate: candidate[0])
            item.insert_vertex(kind, index, nearest)

    def _delete_vertex(self, viewport_position: QPoint, scene_position: QPointF) -> None:
        clicked = self.itemAt(viewport_position)
        if isinstance(clicked, VertexHandle):
            clicked.owner.delete_vertex(clicked.kind, clicked.index)
            return
        item = self.page_scene.selected_line_item()
        if item is None:
            return
        candidates: list[tuple[float, str, int]] = []
        for kind, points in (("polygon", item.polygon), ("baseline", item.baseline)):
            for index, (x, y) in enumerate(points):
                distance = math.hypot(scene_position.x() - x, scene_position.y() - y)
                candidates.append((distance, kind, index))
        if candidates:
            distance, kind, index = min(candidates)
            if distance <= 12 / max(self._zoom, 0.01):
                item.delete_vertex(kind, index)

    def _add_replacement_point(self, position: QPointF) -> None:
        if self.page_scene.selected_line_item() is None:
            return
        self._replacement_points.append((max(0, position.x()), max(0, position.y())))
        path = QPainterPath()
        path.moveTo(*self._replacement_points[0])
        for point in self._replacement_points[1:]:
            path.lineTo(*point)
        if self._replacement_preview is None:
            pen = QPen(Qt.GlobalColor.magenta, 2)
            self._replacement_preview = self.page_scene.addPath(path, pen)
            self._replacement_preview.setZValue(30)
        else:
            self._replacement_preview.setPath(path)

    def finish_replacement(self) -> bool:
        item = self.page_scene.selected_line_item()
        kind = "polygon" if self._mode is EditMode.REPLACE_POLYGON else "baseline"
        success = item is not None and item.replace_shape(kind, self._replacement_points)
        self.cancel_replacement()
        return bool(success)

    def cancel_replacement(self) -> None:
        self._replacement_points.clear()
        if self._replacement_preview is not None:
            self.page_scene.removeItem(self._replacement_preview)
            self._replacement_preview = None

"""One selectable graphics item that paints a PAGE line polygon and baseline."""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPainterPathStroker, QPen, QPolygonF
from PySide6.QtWidgets import QGraphicsItem, QGraphicsObject, QStyleOptionGraphicsItem, QWidget

from ..adapters import Geometry, LineAdapter, PointTuple
from ..themes import Theme, overlay_colors
from .vertex_handle import VertexHandle


def _path(points: Sequence[PointTuple], close: bool = False) -> QPainterPath:
    result = QPainterPath()
    if not points:
        return result
    result.moveTo(*points[0])
    for point in points[1:]:
        result.lineTo(*point)
    if close:
        result.closeSubpath()
    return result


class LineGraphicsItem(QGraphicsObject):
    """A logical TextLine with a unified polygon/border/baseline hit shape."""

    geometryEditRequested = Signal(object, object, str)
    activated = Signal(object)

    def __init__(self, adapter: LineAdapter, theme: Theme | str = Theme.SYSTEM) -> None:
        super().__init__()
        self.adapter = adapter
        self._polygon = adapter.polygon
        self._baseline = adapter.baseline
        self._hit_width = 10.0
        self._drag_before: Geometry | None = None
        self._drag_origin = QPointF()
        self._handles: list[VertexHandle] = []
        self._whole_line_movable = False
        self._vertex_editable = True
        self.colors = overlay_colors(theme)
        self.show_polygon = True
        self.show_baseline = True
        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QGraphicsItem.GraphicsItemFlag.ItemIsFocusable
        )
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.setZValue(2)

    @property
    def polygon(self) -> tuple[PointTuple, ...]:
        return self._polygon

    @property
    def baseline(self) -> tuple[PointTuple, ...]:
        return self._baseline

    def geometry(self) -> Geometry:
        return self._polygon, self._baseline

    def sync_from_adapter(self) -> None:
        self.set_geometry(self.adapter.polygon, self.adapter.baseline)

    def set_geometry(
        self,
        polygon: Sequence[PointTuple],
        baseline: Sequence[PointTuple],
    ) -> None:
        self.prepareGeometryChange()
        self._polygon = tuple((float(x), float(y)) for x, y in polygon)
        self._baseline = tuple((float(x), float(y)) for x, y in baseline)
        self._sync_handles()
        self.update()

    def set_theme(self, theme: Theme | str) -> None:
        self.colors = overlay_colors(theme)
        for handle in self._handles:
            handle.update()
        self.update()

    def set_view_scale(self, scale: float) -> None:
        width = 10.0 / max(scale, 0.001)
        if abs(width - self._hit_width) > 0.01:
            self.prepareGeometryChange()
            self._hit_width = width

    def set_overlay_visibility(self, polygon: bool, baseline: bool) -> None:
        self.show_polygon = polygon
        self.show_baseline = baseline
        # Keep the logical line hit area active in transcription mode even
        # when its visual geometry is intentionally hidden.
        self.setVisible(True)
        self.update()

    def set_interaction_mode(
        self,
        *,
        whole_line_movable: bool,
        vertex_editable: bool,
    ) -> None:
        self.cancel_active_drag()
        self._whole_line_movable = whole_line_movable
        self._vertex_editable = vertex_editable
        self.setCursor(
            Qt.CursorShape.SizeAllCursor
            if whole_line_movable
            else Qt.CursorShape.ArrowCursor
        )
        self._rebuild_handles(self.isSelected() and vertex_editable)

    def cancel_active_drag(self) -> None:
        """Restore an interrupted vertex/line gesture before changing tools."""

        before = self._drag_before
        self._drag_before = None
        if before is not None and before != self.geometry():
            self.set_geometry(*before)
        self.setCursor(
            Qt.CursorShape.SizeAllCursor
            if self._whole_line_movable
            else Qt.CursorShape.ArrowCursor
        )

    def boundingRect(self) -> QRectF:
        points = self._polygon + self._baseline
        if not points:
            return QRectF()
        rect = QPolygonF([QPointF(*point) for point in points]).boundingRect()
        margin = self._hit_width / 2 + 3
        return rect.adjusted(-margin, -margin, margin, margin)

    def shape(self) -> QPainterPath:
        result = QPainterPath()
        if self._polygon:
            polygon_path = _path(self._polygon, close=True)
            stroker = QPainterPathStroker()
            stroker.setWidth(self._hit_width)
            # Use geometric union instead of addPath's odd-even composition.
            # Otherwise a baseline overlapping the polygon interior can become
            # a literal hole in the selectable hit area.
            result = result.united(polygon_path)
            result = result.united(stroker.createStroke(polygon_path))
        if self._baseline:
            stroker = QPainterPathStroker()
            stroker.setWidth(self._hit_width)
            result = result.united(stroker.createStroke(_path(self._baseline)))
        return result

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionGraphicsItem,
        widget: QWidget | None = None,
    ) -> None:
        del option, widget
        selected = self.isSelected()
        state = self.adapter.proposal_state
        color = self.colors["selected"] if selected else self.colors["polygon"]
        if not selected and state in {"proposed", "applied", "pending"}:
            color = self.colors["proposed"]
        style = (
            Qt.PenStyle.DashLine
            if state in {"proposed", "applied", "pending"}
            else Qt.PenStyle.SolidLine
        )
        if self.show_polygon and self._polygon:
            pen = QPen(color, 2.2 if selected else 1.4, style)
            pen.setCosmetic(True)
            painter.setPen(pen)
            fill = QColor(color)
            fill.setAlpha(24 if not selected else 40)
            painter.setBrush(fill)
            painter.drawPolygon(QPolygonF([QPointF(*point) for point in self._polygon]))
        if self.show_baseline and self._baseline:
            baseline_color = self.colors["selected"] if selected else self.colors["baseline"]
            pen = QPen(baseline_color, 2.8 if selected else 2.0, style)
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(_path(self._baseline))

    def itemChange(self, change, value):
        result = super().itemChange(change, value)
        if change == QGraphicsItem.GraphicsItemChange.ItemSelectedHasChanged:
            self._rebuild_handles(bool(value))
            if bool(value):
                self.activated.emit(self)
        return result

    def _rebuild_handles(self, visible: bool) -> None:
        for handle in self._handles:
            handle.setVisible(False)
            handle.deleteLater()
        self._handles.clear()
        if not visible or not self._vertex_editable:
            return
        for kind, points in (("polygon", self._polygon), ("baseline", self._baseline)):
            for index, point in enumerate(points):
                handle = VertexHandle(self, kind, index)
                handle.setPos(*point)
                self._handles.append(handle)

    def _sync_handles(self) -> None:
        if not self.isSelected():
            return
        expected = [
            (kind, index, point)
            for kind, points in (("polygon", self._polygon), ("baseline", self._baseline))
            for index, point in enumerate(points)
        ]
        current_keys = [(handle.kind, handle.index) for handle in self._handles]
        expected_keys = [(kind, index) for kind, index, _point in expected]
        if current_keys != expected_keys:
            self._rebuild_handles(True)
            return
        # Preserve the live handle object during a drag. Rebuilding it here
        # deletes the item which owns Qt's mouse grab after the first move.
        for handle, (_kind, _index, point) in zip(self._handles, expected, strict=True):
            handle.setPos(*point)

    def begin_vertex_drag(self, kind: str, index: int) -> None:
        del kind, index
        self._drag_before = self.geometry()

    def preview_vertex(self, kind: str, index: int, scene_position: QPointF) -> None:
        polygon = list(self._polygon)
        baseline = list(self._baseline)
        points = polygon if kind == "polygon" else baseline
        if 0 <= index < len(points):
            points[index] = (max(0.0, scene_position.x()), max(0.0, scene_position.y()))
            self.set_geometry(polygon, baseline)

    def finish_vertex_drag(self, label: str) -> None:
        before = self._drag_before
        self._drag_before = None
        if before is not None and before != self.geometry():
            self.geometryEditRequested.emit(before, self.geometry(), label)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            extend = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
            if extend and self.isSelected():
                self.setSelected(False)
                event.accept()
                return
            scene = self.scene()
            if not extend and scene is not None:
                scene.clearSelection()
            self.setSelected(True)
            if self._whole_line_movable:
                self._drag_before = self.geometry()
                self._drag_origin = event.scenePos()
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._drag_before is not None and event.buttons() & Qt.MouseButton.LeftButton:
            delta = event.scenePos() - self._drag_origin
            polygon, baseline = self._drag_before
            moved_polygon = tuple(
                (max(0, x + delta.x()), max(0, y + delta.y())) for x, y in polygon
            )
            moved_baseline = tuple(
                (max(0, x + delta.x()), max(0, y + delta.y())) for x, y in baseline
            )
            self.set_geometry(moved_polygon, moved_baseline)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._drag_before is not None:
            self.setCursor(Qt.CursorShape.SizeAllCursor)
            self.finish_vertex_drag("Move line")
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def insert_vertex(self, kind: str, index: int, point: PointTuple) -> None:
        before = self.geometry()
        polygon, baseline = map(list, before)
        target = polygon if kind == "polygon" else baseline
        target.insert(index, point)
        after = (tuple(polygon), tuple(baseline))
        self.geometryEditRequested.emit(before, after, "Add vertex")

    def delete_vertex(self, kind: str, index: int) -> bool:
        before = self.geometry()
        polygon, baseline = map(list, before)
        target = polygon if kind == "polygon" else baseline
        if kind == "polygon":
            distinct = (
                len(target) - 1 if len(target) > 1 and target[0] == target[-1] else len(target)
            )
            minimum = 3
            if distinct <= minimum or not 0 <= index < len(target):
                return False
        else:
            if len(target) <= 2 or not 0 <= index < len(target):
                return False
        del target[index]
        after = (tuple(polygon), tuple(baseline))
        self.geometryEditRequested.emit(before, after, "Delete vertex")
        return True

    def replace_shape(self, kind: str, points: Sequence[PointTuple]) -> bool:
        minimum = 3 if kind == "polygon" else 2
        if len(points) < minimum:
            return False
        before = self.geometry()
        polygon, baseline = before
        after = (tuple(points), baseline) if kind == "polygon" else (polygon, tuple(points))
        self.geometryEditRequested.emit(before, after, "Replace shape")
        return True

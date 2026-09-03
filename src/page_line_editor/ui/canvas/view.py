"""Interactive PAGE image view with zoom, pan, rotation, and geometry tools."""

from __future__ import annotations

import math
from enum import StrEnum

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QContextMenuEvent,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPen,
    QTransform,
    QUndoStack,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QApplication,
    QGraphicsPathItem,
    QGraphicsPixmapItem,
    QGraphicsView,
    QMenu,
    QWidget,
)

from page_line_editor.domain.geometry import GeometryError, Point, Polygon, Polyline

from ..adapters import Geometry, LineAdapter, PointTuple
from ..commands import GeometryEditCommand
from .line_item import LineGraphicsItem
from .scene import PageScene
from .transcription_overlay import TranscriptionOverlay
from .vertex_handle import VertexHandle


class EditMode(StrEnum):
    PAN = "pan"
    SELECT = "select"
    MOVE_LINE = "move_line"
    ADD_VERTEX = "add_vertex"
    DELETE_VERTEX = "delete_vertex"
    REPLACE_POLYGON = "replace_polygon"
    REPLACE_BASELINE = "replace_baseline"


def _segment_distance(
    point: QPointF,
    start: PointTuple,
    end: PointTuple,
) -> tuple[float, PointTuple]:
    """Return distance and nearest point between a point and a line segment."""
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
    editModeRequested = Signal(object)
    keepCorrectionRequested = Signal(str)
    rejectCorrectionRequested = Signal(str)

    def __init__(self, parent=None) -> None:
        """Initialize the PageCanvasView instance."""
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
        self.viewport().setCursor(Qt.CursorShape.ArrowCursor)
        self._zoom = 1.0
        self._rotation = 0
        self._mode = EditMode.SELECT
        self._transcription_focus = False
        self._undo_stack: QUndoStack | None = None
        self._panning = False
        self._pan_button: Qt.MouseButton | None = None
        self._pan_last = QPoint()
        self._replacement_points: list[PointTuple] = []
        self._replacement_preview: QGraphicsPathItem | None = None
        self._context_menu: QMenu | None = None
        self._page_width: int | None = None
        self._page_height: int | None = None

        self.overlay = TranscriptionOverlay(self.viewport())
        self.overlay.navigateLineRequested.connect(
            lambda direction: self.select_adjacent_line(direction, focus_editor=True)
        )
        self.page_scene.lineSelected.connect(self._line_selected)
        self.page_scene.geometryEditRequested.connect(self._geometry_edit_requested)
        self.horizontalScrollBar().valueChanged.connect(self.update_overlay_position)
        self.verticalScrollBar().valueChanged.connect(self.update_overlay_position)

    @property
    def edit_mode(self) -> EditMode:
        """Edit mode."""
        return self._mode

    @property
    def zoom_factor(self) -> float:
        """Return zoom factor."""
        return self._zoom

    @property
    def view_rotation(self) -> int:
        """Return view rotation."""
        return self._rotation

    @property
    def has_pending_replacement(self) -> bool:
        """Return whether pending replacement."""
        return bool(self._replacement_points)

    def set_undo_stack(self, stack: QUndoStack) -> None:
        """Set undo stack."""
        self._undo_stack = stack

    def set_edit_mode(self, mode: EditMode | str) -> None:
        """Set edit mode."""
        self._cancel_pan()
        self.cancel_replacement()
        self._mode = EditMode(mode)
        self._apply_item_interactions()
        self._restore_tool_cursor()

    def set_transcription_focus(self, enabled: bool) -> None:
        """Set transcription focus."""
        self._transcription_focus = enabled
        self._apply_item_interactions()

    def set_page(self, image, lines, on_change=None) -> None:
        """Load one page image and its editable line overlays."""
        self.overlay.set_line(None)
        self.page_scene.set_page(image, lines, on_change)
        self._apply_item_interactions()
        self.reset_rotation()
        self.fit_page()

    def set_page_size(self, width: int | None, height: int | None) -> None:
        """PAGE imageWidth/Height used by geometry guards, not pixmap pixels."""
        self._page_width = width
        self._page_height = height

    def set_overlay_visibility(self, polygons: bool, baselines: bool) -> None:
        """Set overlay visibility."""
        self.page_scene.set_overlay_visibility(polygons, baselines)

    def zoom_in(self) -> None:
        """Increase the canvas zoom by one standard step."""
        self.set_zoom(self._zoom * 1.2)

    def zoom_out(self) -> None:
        """Decrease the canvas zoom by one standard step."""
        self.set_zoom(self._zoom / 1.2)

    def set_zoom(self, zoom: float) -> None:
        """Set zoom."""
        self._zoom = min(20.0, max(0.03, zoom))
        self._apply_transform()

    def rotate_left(self) -> None:
        """Rotate the view left by ninety degrees."""
        self._rotation = (self._rotation - 90) % 360
        self._apply_transform()
        self.rotationChanged.emit(self._rotation)

    def rotate_right(self) -> None:
        """Rotate the view right by ninety degrees."""
        self._rotation = (self._rotation + 90) % 360
        self._apply_transform()
        self.rotationChanged.emit(self._rotation)

    def reset_rotation(self) -> None:
        """Restore the unrotated canvas view."""
        self._rotation = 0
        self._apply_transform()
        self.rotationChanged.emit(0)

    def fit_page(self) -> None:
        """Fit the current page image within the canvas viewport."""
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
        """Apply transform."""
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
        """Update overlay position."""
        try:
            item = self.page_scene.selected_line_item()
        except RuntimeError:
            return
        if item is None or not self.overlay.isVisible():
            return
        line_rect = self.mapFromScene(item.sceneBoundingRect()).boundingRect()
        points = item.polygon + item.baseline
        if points:
            # Anchor to the visible geometry rather than the item's padded hit
            # bounds so the editor sits directly beneath the lowest vertex.
            line_rect.setBottom(
                max(self.mapFromScene(QPointF(*point)).y() for point in points)
            )
        self.overlay.anchor_below(line_rect, self.viewport().width())

    def ensure_editor_visible(self) -> None:
        """Ensure editor visible."""
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
        """Update overlay content after the active line selection changes."""
        adapter = item.adapter if item is not None else None
        self.overlay.set_line(adapter)
        if item is not None:
            self.update_overlay_position()
            self.ensure_editor_visible()
        self.selectedLineChanged.emit(adapter)

    def select_adjacent_line(self, direction: int, *, focus_editor: bool = False) -> None:
        """Select the preceding or following TextLine in PAGE document order."""

        items = self.page_scene.line_items
        if not items or direction == 0:
            return
        current = self.page_scene.selected_line_item()
        if current is None:
            target_index = 0 if direction > 0 else len(items) - 1
        else:
            current_index = items.index(current)
            target_index = max(0, min(len(items) - 1, current_index + direction))
        target = items[target_index]
        if target is current:
            return

        editor_had_focus = focus_editor or self.overlay.editor.hasFocus()
        self.cancel_replacement()
        self.page_scene.clearSelection()
        target.setSelected(True)
        if editor_had_focus:
            self.overlay.editor.setFocus(Qt.FocusReason.ShortcutFocusReason)

    def accept_selected_correction(self) -> bool:
        """Accept selected correction."""
        return self._request_selected_correction_decision(accept=True)

    def reject_selected_correction(self) -> bool:
        """Reject selected correction."""
        return self._request_selected_correction_decision(accept=False)

    def _request_selected_correction_decision(self, *, accept: bool) -> bool:
        """Emit an acceptance or rejection request for the selected proposal."""
        item = self.page_scene.selected_line_item()
        if item is None or item.adapter.proposal_state not in {
            "applied",
            "pending",
            "proposed",
        }:
            return False
        signal = self.keepCorrectionRequested if accept else self.rejectCorrectionRequested
        signal.emit(item.adapter.id)
        return True

    def _geometry_edit_requested(
        self,
        item: LineGraphicsItem,
        before: Geometry,
        after: Geometry,
        label: str,
    ) -> None:
        """Validate and commit a requested geometry edit as one undo step."""
        introduced = self._geometry_issues(after) - self._geometry_issues(before)
        if introduced:
            item.set_geometry(*before)
            self.geometryEditRejected.emit("; ".join(sorted(introduced)))
            return

        def notify(adapter: LineAdapter) -> None:
            """Notify the UI that the edit state changed."""
            current = self.page_scene.line_item(adapter.id)
            if current is not None:
                current.sync_from_adapter()
            self.lineGeometryChanged.emit(adapter.id, adapter.polygon, adapter.baseline)
            self.update_overlay_position()

        if self._undo_stack is not None:
            self._undo_stack.push(GeometryEditCommand(item.adapter, before, after, notify, label))
        else:
            item.adapter.set_geometry(*after)
            notify(item.adapter)

    def _geometry_issues(self, geometry: Geometry) -> set[str]:
        """Return validation issues introduced by candidate line geometry."""
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
        width, height = self._page_width, self._page_height
        if width is None or height is None:
            image = self.page_scene.image_item
            if image is not None:
                width, height = image.pixmap().width(), image.pixmap().height()
        if width is not None and height is not None:
            points = list(polygon.points) + list(baseline.points if baseline else ())
            if any(not (0 <= point.x < width and 0 <= point.y < height) for point in points):
                issues.add("Geometry must remain inside the PAGE image")
        if baseline is not None and any(
            not polygon.contains(point) for point in baseline.points
        ):
            issues.add("Baseline must remain inside its line polygon")
        return issues

    def wheelEvent(self, event: QWheelEvent) -> None:
        """Handle the Qt wheel event."""
        zoom_modifiers = (
            Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier
        )
        if event.modifiers() & zoom_modifiers:
            self.set_zoom(self._zoom * (1.2 if event.angleDelta().y() > 0 else 1 / 1.2))
            event.accept()
            return
        super().wheelEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Handle the Qt mouse press event."""
        if self._panning:
            self._cancel_pan()
        pan_modifier = event.modifiers() & (
            Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier
        )
        if event.button() == Qt.MouseButton.MiddleButton or (
            event.button() == Qt.MouseButton.LeftButton
            and (self._mode is EditMode.PAN or pan_modifier)
        ):
            self._begin_pan(event, event.button())
            return
        if event.button() == Qt.MouseButton.LeftButton and self._mode is EditMode.SELECT:
            viewport_position = event.position().toPoint()
            active_line = self.page_scene.selected_line_item()
            selected_handles = [
                item
                for item in self.items(viewport_position)
                if isinstance(item, VertexHandle) and item.owner.isSelected()
            ]
            selected_handle = next(
                (handle for handle in selected_handles if handle.owner is active_line),
                selected_handles[0] if selected_handles else None,
            )
            if selected_handle is not None:
                owner = selected_handle.owner
                original_z = owner.zValue()
                owner.setZValue(
                    max(
                        (item.zValue() for item in self.page_scene.line_items),
                        default=original_z,
                    )
                    + 1
                )
                try:
                    super().mousePressEvent(event)
                finally:
                    owner.setZValue(original_z)
                return
            clicked = self.itemAt(viewport_position)
            if clicked is None or isinstance(clicked, QGraphicsPixmapItem):
                self.page_scene.clearSelection()
                event.accept()
                return
        geometry_modes = {
            EditMode.ADD_VERTEX,
            EditMode.DELETE_VERTEX,
            EditMode.REPLACE_POLYGON,
            EditMode.REPLACE_BASELINE,
        }
        if event.button() == Qt.MouseButton.LeftButton and self._mode in geometry_modes:
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
        """Handle the Qt mouse move event."""
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
        """Handle the Qt mouse release event."""
        if self._panning and event.button() == self._pan_button:
            self._panning = False
            self._pan_button = None
            self._restore_tool_cursor()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _begin_pan(self, event: QMouseEvent, button: Qt.MouseButton) -> None:
        """Begin pan."""
        self._panning = True
        self._pan_button = button
        self._pan_last = event.position().toPoint()
        self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
        event.accept()

    def _cancel_pan(self) -> None:
        """Cancel pan."""
        self._panning = False
        self._pan_button = None
        grabber = QWidget.mouseGrabber()
        if grabber in {self, self.viewport()}:
            grabber.releaseMouse()
        self._restore_tool_cursor()

    def _apply_item_interactions(self) -> None:
        """Apply item interactions."""
        for item in self.page_scene.line_items:
            item.set_interaction_mode(
                whole_line_movable=(
                    self._mode is EditMode.MOVE_LINE and not self._transcription_focus
                ),
                vertex_editable=(
                    self._mode
                    in {EditMode.SELECT, EditMode.ADD_VERTEX, EditMode.DELETE_VERTEX}
                    and not self._transcription_focus
                ),
            )

    def _restore_tool_cursor(self) -> None:
        """Restore tool cursor."""
        cursors = {
            EditMode.PAN: Qt.CursorShape.OpenHandCursor,
            EditMode.SELECT: Qt.CursorShape.ArrowCursor,
            EditMode.MOVE_LINE: Qt.CursorShape.SizeAllCursor,
        }
        self.viewport().setCursor(cursors.get(self._mode, Qt.CursorShape.CrossCursor))

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        """Handle the Qt mouse double click event."""
        if self._mode in (EditMode.REPLACE_POLYGON, EditMode.REPLACE_BASELINE):
            self.finish_replacement()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Handle the Qt key press event."""
        if event.modifiers() == Qt.KeyboardModifier.NoModifier and event.key() in (
            Qt.Key.Key_Up,
            Qt.Key.Key_Down,
        ):
            self.select_adjacent_line(-1 if event.key() == Qt.Key.Key_Up else 1)
            event.accept()
            return
        if event.key() in (Qt.Key.Key_Control, Qt.Key.Key_Meta):
            self.viewport().setCursor(Qt.CursorShape.OpenHandCursor)
        if self._replacement_points and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.finish_replacement()
            event.accept()
            return
        if self._replacement_points and event.key() == Qt.Key.Key_Escape:
            self.cancel_replacement()
            event.accept()
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event: QKeyEvent) -> None:
        """Handle the Qt key release event."""
        if event.key() in (Qt.Key.Key_Control, Qt.Key.Key_Meta) and not self._panning:
            self._restore_tool_cursor()
        super().keyReleaseEvent(event)

    def focusOutEvent(self, event) -> None:
        """Handle the Qt focus out event."""
        self._cancel_pan()
        for item in self.page_scene.line_items:
            item.cancel_active_drag()
        super().focusOutEvent(event)

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:
        """Handle the Qt context menu event."""
        clicked = self.itemAt(event.pos())
        item = clicked.owner if isinstance(clicked, VertexHandle) else clicked
        if not isinstance(item, LineGraphicsItem):
            super().contextMenuEvent(event)
            return
        self._context_menu = self.build_line_context_menu(item)
        self._context_menu.aboutToHide.connect(self._clear_context_menu)
        self._context_menu.popup(event.globalPos())
        event.accept()

    def _clear_context_menu(self) -> None:
        """Release the transient line context menu after it closes."""
        menu = self._context_menu
        self._context_menu = None
        if menu is not None:
            menu.deleteLater()

    def build_line_context_menu(self, item: LineGraphicsItem) -> QMenu:
        """Create the extensible right-click command surface for one TextLine."""

        menu = QMenu(self)
        edit_text = menu.addAction("Edit transcription")
        edit_text.triggered.connect(lambda: self._focus_line_editor(item))
        select_only = menu.addAction("Select only")
        select_only.triggered.connect(lambda: self._select_only(item))
        center = menu.addAction("Center on line")
        center.triggered.connect(lambda: self.centerOn(item))
        menu.addSeparator()
        move = menu.addAction("Use Move Whole Line tool")
        move.triggered.connect(lambda: self.editModeRequested.emit(EditMode.MOVE_LINE))
        add_vertex = menu.addAction("Use Add Vertex tool")
        add_vertex.triggered.connect(lambda: self.editModeRequested.emit(EditMode.ADD_VERTEX))
        menu.addSeparator()
        copy_id = menu.addAction("Copy TextLine ID")
        copy_id.triggered.connect(
            lambda: QApplication.clipboard().setText(item.adapter.id)
        )
        return menu

    def _select_only(self, item: LineGraphicsItem) -> None:
        """Select only."""
        self.page_scene.clearSelection()
        item.setSelected(True)

    def _focus_line_editor(self, item: LineGraphicsItem) -> None:
        """Select a line and focus its transcription editor."""
        self._select_only(item)
        self.overlay.editor.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self.overlay.editor.selectAll()

    def resizeEvent(self, event) -> None:
        """Handle the Qt resize event."""
        super().resizeEvent(event)
        self.update_overlay_position()

    def _add_vertex(self, position: QPointF) -> None:
        """Add vertex."""
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
        """Delete vertex."""
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
        """Add replacement point."""
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
        """Finish replacement."""
        item = self.page_scene.selected_line_item()
        kind = "polygon" if self._mode is EditMode.REPLACE_POLYGON else "baseline"
        success = item is not None and item.replace_shape(kind, self._replacement_points)
        self.cancel_replacement()
        return bool(success)

    def cancel_replacement(self) -> None:
        """Cancel replacement."""
        self._replacement_points.clear()
        if self._replacement_preview is not None:
            self.page_scene.removeItem(self._replacement_preview)
            self._replacement_preview = None

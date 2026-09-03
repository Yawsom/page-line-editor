"""Screen-stable draggable vertex handles."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QRectF
from PySide6.QtGui import QBrush, QPainter, QPen
from PySide6.QtWidgets import QGraphicsItem, QGraphicsObject, QStyleOptionGraphicsItem, QWidget

if TYPE_CHECKING:
    from .line_item import LineGraphicsItem


class VertexHandle(QGraphicsObject):
    RADIUS = 5.0

    def __init__(self, owner: LineGraphicsItem, kind: str, index: int) -> None:
        """Initialize the VertexHandle instance."""
        super().__init__(owner)
        self.owner = owner
        self.kind = kind
        self.index = index
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsFocusable, True)
        self.setAcceptedMouseButtons(owner.acceptedMouseButtons())
        self.setCursor(owner.cursor())
        self.setZValue(20)

    def boundingRect(self) -> QRectF:
        """Return the item bounding rectangle in local coordinates."""
        r = self.RADIUS + 1.5
        return QRectF(-r, -r, 2 * r, 2 * r)

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionGraphicsItem,
        widget: QWidget | None = None,
    ) -> None:
        """Paint the item using the active theme and selection state."""
        del option, widget
        painter.setPen(QPen(self.owner.colors["handle"], 1.5))
        painter.setBrush(QBrush(self.owner.colors["handle_fill"]))
        painter.drawEllipse(QRectF(-self.RADIUS, -self.RADIUS, 2 * self.RADIUS, 2 * self.RADIUS))

    def mousePressEvent(self, event) -> None:
        """Handle the Qt mouse press event."""
        self.owner.begin_vertex_drag(self.kind, self.index)
        event.accept()

    def mouseMoveEvent(self, event) -> None:
        """Handle the Qt mouse move event."""
        self.owner.preview_vertex(self.kind, self.index, event.scenePos())
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        """Handle the Qt mouse release event."""
        self.owner.finish_vertex_drag("Move vertex")
        event.accept()

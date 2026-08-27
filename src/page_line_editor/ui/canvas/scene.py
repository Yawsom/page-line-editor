"""Graphics scene owning the current page image and line items."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

from PySide6.QtCore import QRectF, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QGraphicsPixmapItem, QGraphicsScene

from ..adapters import LineAdapter
from ..themes import Theme
from .line_item import LineGraphicsItem


class ImageLoadError(ValueError):
    """The selected page image could not be decoded by Qt."""


class PageScene(QGraphicsScene):
    lineSelected = Signal(object)
    geometryEditRequested = Signal(object, object, object, str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.image_item: QGraphicsPixmapItem | None = None
        self.line_items: list[LineGraphicsItem] = []
        self._active_line: LineGraphicsItem | None = None
        self.theme = Theme.SYSTEM
        self.selectionChanged.connect(self._selection_changed)

    def set_page(
        self,
        image: QPixmap | str | Path,
        lines: Iterable[Any],
        on_change=None,
    ) -> None:
        self.clear()
        pixmap = image if isinstance(image, QPixmap) else QPixmap(str(image))
        if pixmap.isNull():
            raise ImageLoadError(
                f"Could not decode page image {image!s}. "
                "Use a valid JPEG or PNG and verify the Qt image plugins are installed."
            )
        self.image_item = self.addPixmap(pixmap)
        self.image_item.setZValue(-10)
        self.line_items = []
        self._active_line = None
        for source in lines:
            adapter = source if isinstance(source, LineAdapter) else LineAdapter(source, on_change)
            item = LineGraphicsItem(adapter, self.theme)
            item.geometryEditRequested.connect(
                lambda before, after, label, current=item: self.geometryEditRequested.emit(
                    current, before, after, label
                )
            )
            self.addItem(item)
            item.activated.connect(self._activate_line)
            self.line_items.append(item)
        image_rect = QRectF(pixmap.rect())
        # Lower margin makes room for the viewport editor without changing PAGE coordinates.
        self.setSceneRect(image_rect.adjusted(0, 0, 0, 260))

    def set_theme(self, theme: Theme | str) -> None:
        self.theme = Theme(theme)
        for item in self.line_items:
            item.set_theme(self.theme)

    def set_overlay_visibility(self, polygons: bool, baselines: bool) -> None:
        for item in self.line_items:
            item.set_overlay_visibility(polygons, baselines)

    def selected_line_item(self) -> LineGraphicsItem | None:
        if self._active_line is not None and self._active_line.isSelected():
            return self._active_line
        return next(
            (item for item in self.selectedItems() if isinstance(item, LineGraphicsItem)),
            None,
        )

    def line_item(self, line_id: str) -> LineGraphicsItem | None:
        return next((item for item in self.line_items if item.adapter.id == line_id), None)

    def _selection_changed(self) -> None:
        item = self.selected_line_item()
        self._active_line = item
        self.lineSelected.emit(item)

    def _activate_line(self, item: LineGraphicsItem) -> None:
        self._active_line = item

"""QUndoCommand implementations used by the canvas and text overlay."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtGui import QUndoCommand

from ..adapters import Geometry, LineAdapter


class TextEditCommand(QUndoCommand):
    def __init__(
        self,
        line: LineAdapter,
        before: str,
        after: str,
        notify: Callable[[LineAdapter], None],
    ) -> None:
        """Initialize the TextEditCommand instance."""
        super().__init__("Edit transcription")
        self._line = line
        self._before = before
        self._after = after
        self._notify = notify

    def redo(self) -> None:
        """Redo this operation."""
        self._line.set_text(self._after)
        self._notify(self._line)

    def undo(self) -> None:
        """Undo this operation."""
        self._line.set_text(self._before)
        self._notify(self._line)


class GeometryEditCommand(QUndoCommand):
    def __init__(
        self,
        line: LineAdapter,
        before: Geometry,
        after: Geometry,
        notify: Callable[[LineAdapter], None],
        label: str = "Edit line geometry",
    ) -> None:
        """Initialize the GeometryEditCommand instance."""
        super().__init__(label)
        self._line = line
        self._before = before
        self._after = after
        self._notify = notify

    def _apply(self, geometry: Geometry) -> None:
        """Apply a stored edit state and notify listeners."""
        self._line.set_geometry(*geometry)
        self._notify(self._line)

    def redo(self) -> None:
        """Redo this operation."""
        self._apply(self._after)

    def undo(self) -> None:
        """Undo this operation."""
        self._apply(self._before)

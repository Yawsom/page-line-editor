"""Small Qt-free undo/redo stack for document field edits."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from page_line_editor.domain.geometry import Polygon, Polyline
from page_line_editor.domain.page import PageDocument


@dataclass(frozen=True, slots=True)
class FieldEdit:
    line_id: str
    field: str
    before: Any
    after: Any
    label: str


class DocumentHistory:
    def __init__(self, document: PageDocument) -> None:
        self.document = document
        self._commands: list[FieldEdit] = []
        self._cursor = 0
        self._clean_cursor = 0

    @property
    def can_undo(self) -> bool:
        return self._cursor > 0

    @property
    def can_redo(self) -> bool:
        return self._cursor < len(self._commands)

    @property
    def is_clean(self) -> bool:
        return self._cursor == self._clean_cursor

    def _set(self, command: FieldEdit, *, forward: bool) -> None:
        line = self.document.line_by_id(command.line_id)
        setattr(line, command.field, command.after if forward else command.before)
        self.document.revision += 1

    def push(self, command: FieldEdit) -> None:
        if command.before == command.after:
            return
        del self._commands[self._cursor :]
        self._set(command, forward=True)
        self._commands.append(command)
        self._cursor += 1

    def edit_text(self, line_id: str, text: str, *, label: str = "Edit transcription") -> None:
        line = self.document.line_by_id(line_id)
        self.push(FieldEdit(line_id, "text", line.text, text, label))

    def edit_polygon(self, line_id: str, polygon: Polygon, *, label: str = "Edit polygon") -> None:
        line = self.document.line_by_id(line_id)
        self.push(FieldEdit(line_id, "polygon", line.polygon, polygon, label))

    def edit_baseline(
        self,
        line_id: str,
        baseline: Polyline | None,
        *,
        label: str = "Edit baseline",
    ) -> None:
        line = self.document.line_by_id(line_id)
        self.push(FieldEdit(line_id, "baseline", line.baseline, baseline, label))

    def edit_deleted(
        self,
        line_id: str,
        deleted: bool,
        *,
        label: str = "Delete line",
    ) -> None:
        """Apply a reversible in-memory line deletion/restoration."""
        line = self.document.line_by_id(line_id)
        self.push(FieldEdit(line_id, "deleted", line.deleted, deleted, label))

    def undo(self) -> FieldEdit | None:
        if not self.can_undo:
            return None
        self._cursor -= 1
        command = self._commands[self._cursor]
        self._set(command, forward=False)
        return command

    def redo(self) -> FieldEdit | None:
        if not self.can_redo:
            return None
        command = self._commands[self._cursor]
        self._set(command, forward=True)
        self._cursor += 1
        return command

    def mark_clean(self) -> None:
        self._clean_cursor = self._cursor

    def clear(self) -> None:
        self._commands.clear()
        self._cursor = self._clean_cursor = 0


class HistoryService:
    """Creates immutable audit copies outside the live XML directory."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def backup_manual(self, source: str | Path) -> Path:
        source_path = Path(source)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        run_dir = self.root / "manual" / f"{stamp}-{uuid4().hex[:8]}" / "originals"
        run_dir.mkdir(parents=True, exist_ok=False)
        destination = run_dir / source_path.name
        shutil.copyfile(source_path, destination)
        return destination

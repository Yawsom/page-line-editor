"""Validated backup-first, atomic PAGE saving."""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from page_line_editor.domain.page import PageDocument
from page_line_editor.pagexml.validator import ValidationReport, validate_xml
from page_line_editor.pagexml.writer import PageWriteError, build_candidate, refresh_xml_paths

from .history_service import HistoryService


class SaveError(RuntimeError):
    pass


class ValidationFailed(SaveError):
    def __init__(self, report: ValidationReport) -> None:
        super().__init__("Candidate PAGE XML did not pass blocking validation")
        self.report = report


@dataclass(frozen=True, slots=True)
class SaveResult:
    source_path: Path
    backup_path: Path
    validation: ValidationReport
    bytes_written: int


class SaveService:
    def __init__(self, history_directory: str | Path) -> None:
        self.history = HistoryService(history_directory)

    def save(self, document: PageDocument) -> SaveResult:
        text_edited_ids = tuple(
            line.id
            for line in document.lines
            if "text" in line.dirty_fields and not line.deleted
        )
        try:
            candidate, candidate_tree = build_candidate(document)
        except PageWriteError as exc:
            raise SaveError(f"Could not build PAGE XML: {exc}") from exc
        validation = validate_xml(candidate)
        if not validation.can_save:
            raise ValidationFailed(validation)
        source = document.source_path
        backup = self.history.backup_manual(source)
        temp_path: Path | None = None
        try:
            descriptor, raw_temp = tempfile.mkstemp(
                prefix=f".{source.name}.", suffix=".tmp", dir=source.parent
            )
            temp_path = Path(raw_temp)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(candidate)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_path, source)
            temp_path = None
            # Best-effort directory durability. Windows does not support opening
            # a directory as a normal file descriptor.
            if os.name != "nt":
                directory_fd = os.open(source.parent, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
        except OSError as exc:
            raise SaveError(f"Could not atomically save {source}: {exc}") from exc
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
        document.mark_clean(xml_tree=candidate_tree)
        for line_id in text_edited_ids:
            try:
                document.line_by_id(line_id).has_word_content = False
            except KeyError:
                # A future compound operation may delete a line after editing it.
                continue
        refresh_xml_paths(document)
        return SaveResult(source, backup, validation, len(candidate))

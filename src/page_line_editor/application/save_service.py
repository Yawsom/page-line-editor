"""Validated backup-first, atomic PAGE saving."""

from __future__ import annotations

import errno
import os
import shutil
import tempfile
from contextlib import suppress
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
        """Initialize the ValidationFailed instance."""
        super().__init__("Candidate PAGE XML did not pass blocking validation")
        self.report = report


@dataclass(frozen=True, slots=True)
class SaveResult:
    source_path: Path
    backup_path: Path
    validation: ValidationReport
    bytes_written: int
    durability_warning: str | None = None


_UNSUPPORTED_DIRECTORY_SYNC_ERRORS = {
    errno.EINVAL,
    getattr(errno, "ENOTSUP", errno.EINVAL),
    getattr(errno, "EOPNOTSUPP", errno.EINVAL),
}


def _sync_directory(directory: Path) -> str | None:
    """Best-effort directory durability without misreporting a committed save."""

    if os.name == "nt":
        return None
    directory_fd: int | None = None
    error: OSError | None = None
    try:
        directory_fd = os.open(directory, os.O_RDONLY)
        os.fsync(directory_fd)
    except OSError as exc:
        error = exc
    finally:
        if directory_fd is not None:
            try:
                os.close(directory_fd)
            except OSError as exc:
                if error is None:
                    error = exc
    if error is None or error.errno in _UNSUPPORTED_DIRECTORY_SYNC_ERRORS:
        return None
    return f"the file was replaced, but its directory could not be synced: {error}"


class SaveService:
    def __init__(self, history_directory: str | Path) -> None:
        """Initialize the SaveService instance."""
        self.history = HistoryService(history_directory)

    def save(self, document: PageDocument) -> SaveResult:
        """Validate, back up, and atomically persist the active PAGE document."""
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
        try:
            backup = self.history.backup_manual(source)
        except OSError as exc:
            raise SaveError(f"Could not back up {source} before saving: {exc}") from exc
        temp_path: Path | None = None
        try:
            descriptor, raw_temp = tempfile.mkstemp(
                prefix=f".{source.name}.", suffix=".tmp", dir=source.parent
            )
            temp_path = Path(raw_temp)
            with os.fdopen(descriptor, "wb") as stream:
                shutil.copymode(source, temp_path)
                stream.write(candidate)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_path, source)
            temp_path = None
        except OSError as exc:
            raise SaveError(f"Could not atomically save {source}: {exc}") from exc
        finally:
            if temp_path is not None:
                with suppress(OSError):
                    temp_path.unlink(missing_ok=True)
        # The replace above is the transaction boundary. Directory fsync adds
        # crash durability on platforms that support it, but a failure here
        # must not claim the already-replaced source was not saved.
        durability_warning = _sync_directory(source.parent)
        document.mark_clean(xml_tree=candidate_tree)
        for line_id in text_edited_ids:
            try:
                document.line_by_id(line_id).has_word_content = False
            except KeyError:
                # A future compound operation may delete a line after editing it.
                continue
        refresh_xml_paths(document)
        return SaveResult(source, backup, validation, len(candidate), durability_warning)

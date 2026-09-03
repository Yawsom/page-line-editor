"""Current-project/current-page state shared by future Qt views."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from page_line_editor.domain.page import PageDocument
from page_line_editor.pagexml.parser import parse_page

from .history_service import DocumentHistory
from .project_scanner import PagePair, ProjectScanner, ProjectScanResult
from .save_service import SaveResult, SaveService


@dataclass(slots=True)
class EditorSession:
    normalize_nfc: bool = True
    project: ProjectScanResult | None = None
    current_index: int = -1
    document: PageDocument | None = None
    history: DocumentHistory | None = None
    history_directory: Path | None = None
    scanner: ProjectScanner = field(default_factory=ProjectScanner)

    @property
    def current_pair(self) -> PagePair | None:
        """Return current pair."""
        if self.project is None or self.current_index < 0:
            return None
        return self.project.pairs[self.current_index]

    @property
    def is_dirty(self) -> bool:
        """Return whether dirty."""
        return self.document is not None and self.document.is_dirty

    def open_project(
        self,
        image_directory: str | Path,
        xml_directory: str | Path,
        history_directory: str | Path | None = None,
    ) -> ProjectScanResult:
        """Open project."""
        if self.is_dirty:
            raise RuntimeError(
                "Unsaved document changes must be handled before opening another project"
            )
        self.project = self.scanner.scan(image_directory, xml_directory)
        self.history_directory = (
            Path(history_directory)
            if history_directory is not None
            else Path(xml_directory).parent / "correction_history"
        )
        self.current_index = -1
        self.document = None
        self.history = None
        if self.project.pairs:
            self.open_page(0)
        return self.project

    def open_page(self, index: int) -> PageDocument:
        """Open page."""
        if self.project is None:
            raise RuntimeError("No project is open")
        if self.is_dirty:
            raise RuntimeError("Unsaved document changes must be handled before changing pages")
        pair = self.project.pairs[index]
        document = parse_page(pair.xml_path)
        document.image_path = pair.image_path
        self.current_index = index
        self.document = document
        self.history = DocumentHistory(document)
        return document

    def normalize_text(self, text: str) -> str:
        """Normalize text."""
        return unicodedata.normalize("NFC", text) if self.normalize_nfc else text

    def edit_text(self, line_id: str, text: str) -> None:
        """Edit text."""
        if self.history is None:
            raise RuntimeError("No page is open")
        self.history.edit_text(line_id, self.normalize_text(text))

    def save(self) -> SaveResult:
        """Save the active document through the safe persistence service."""
        if self.document is None or self.history_directory is None:
            raise RuntimeError("No page is open")
        result = SaveService(self.history_directory).save(self.document)
        if self.history is not None:
            # Saved deletions remove tombstones from the document. A fresh
            # history prevents undo commands from referencing committed nodes.
            self.history.clear()
        return result

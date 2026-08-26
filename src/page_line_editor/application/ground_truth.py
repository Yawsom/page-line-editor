"""Load the existing folio-delimited DOCX ground-truth format."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from zipfile import BadZipFile

from docx import Document
from docx.opc.exceptions import PackageNotFoundError

from page_line_editor.correction import GroundTruthLine
from page_line_editor.domain.page import PageDocument

FOLIO_RE = re.compile(r"^\[(\d+[rv])\]$", re.IGNORECASE)


class GroundTruthError(ValueError):
    """The ground-truth document cannot be used for correction."""


class GroundTruthPageNotFound(GroundTruthError):
    pass


@dataclass(frozen=True, slots=True)
class GroundTruthBook:
    source_path: Path
    pages: Mapping[str, tuple[GroundTruthLine, ...]]

    def lines_for_key(self, key: str) -> tuple[GroundTruthLine, ...]:
        direct = self.pages.get(key)
        if direct is not None:
            return direct
        folded = key.casefold()
        matches = [lines for page_key, lines in self.pages.items() if page_key.casefold() == folded]
        if len(matches) == 1:
            return matches[0]
        raise GroundTruthPageNotFound(f"No ground-truth page named {key!r}")

    def lines_for_document(self, document: PageDocument) -> tuple[GroundTruthLine, ...]:
        candidates: list[str] = []
        for value in (
            Path(document.image_filename).stem if document.image_filename else "",
            document.source_path.stem,
        ):
            if value and value not in candidates:
                candidates.append(value)
            if value.lower().startswith("transkribus-"):
                stripped = value[len("transkribus-") :]
                if stripped and stripped not in candidates:
                    candidates.append(stripped)
        for key in candidates:
            try:
                return self.lines_for_key(key)
            except GroundTruthPageNotFound:
                continue
        names = ", ".join(repr(key) for key in candidates) or "(no filename candidates)"
        raise GroundTruthPageNotFound(f"No ground truth matches PAGE keys: {names}")


def parse_ground_truth_docx(path: str | Path) -> GroundTruthBook:
    """Parse ``[12r]`` headers and following non-empty paragraphs.

    This intentionally mirrors the legacy correction script: content before the
    first header and blank paragraphs are ignored, and repeated headers append
    to the same folio.
    """

    source = Path(path)
    try:
        document = Document(str(source))
    except (OSError, ValueError, KeyError, BadZipFile, PackageNotFoundError) as exc:
        raise GroundTruthError(f"Cannot read ground-truth DOCX {source}: {exc}") from exc

    page_text: dict[str, list[str]] = {}
    current: str | None = None
    for paragraph in document.paragraphs:
        text = (paragraph.text or "").strip()
        if not text:
            continue
        header = FOLIO_RE.fullmatch(text)
        if header is not None:
            current = header.group(1).lower()
            page_text.setdefault(current, [])
            continue
        if current is not None:
            page_text[current].append(text)

    if not page_text:
        raise GroundTruthError(
            f"Ground-truth DOCX {source} contains no [folio] page headers"
        )
    pages = {
        key: tuple(GroundTruthLine(index, text) for index, text in enumerate(lines))
        for key, lines in page_text.items()
    }
    return GroundTruthBook(source, MappingProxyType(pages))

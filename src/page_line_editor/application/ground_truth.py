"""Load the existing folio-delimited DOCX ground-truth format."""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from zipfile import BadZipFile

from docx import Document
from docx.document import Document as DocumentObject
from docx.opc.exceptions import PackageNotFoundError
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph

from page_line_editor.correction import GroundTruthLine
from page_line_editor.domain.page import PageDocument

FOLIO_RE = re.compile(r"^\[(\d+[rv])\]$", re.IGNORECASE)
FOLIO_LIKE_RE = re.compile(r"^\[+\s*\d+\s*[rRvV]\s*\]+$")
BIDI_FORMAT_RE = re.compile(r"[\u200e\u200f\u202a-\u202e\u2066-\u2069\ufeff]")


class GroundTruthError(ValueError):
    """The ground-truth document cannot be used for correction."""


class GroundTruthPageNotFound(GroundTruthError):
    pass


@dataclass(frozen=True, slots=True)
class GroundTruthBook:
    source_path: Path
    pages: Mapping[str, tuple[GroundTruthLine, ...]]
    warnings: tuple[str, ...] = ()

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


def strip_bidi_format(text: str) -> str:
    """Remove marks Word inserts around RTL folio headers such as ``[93v]``."""
    return BIDI_FORMAT_RE.sub("", text).strip()


def iter_docx_blocks(document: DocumentObject) -> Iterator[Paragraph | Table]:
    """Yield body paragraphs and tables in document order."""
    body = document.element.body
    for child in body.iterchildren():
        if child.tag == qn("w:p"):
            yield Paragraph(child, document)
        elif child.tag == qn("w:tbl"):
            yield Table(child, document)


def _cell_paragraphs(table: Table) -> Iterator[Paragraph]:
    seen: set[int] = set()
    for row in table.rows:
        for cell in row.cells:
            ident = id(cell._tc)
            if ident in seen:
                continue
            seen.add(ident)
            yield from cell.paragraphs


def parse_ground_truth_docx(path: str | Path) -> GroundTruthBook:
    """Parse ``[12r]`` headers and following non-empty paragraphs.

    This intentionally mirrors the legacy correction script: content before the
    first header and blank paragraphs are ignored, and repeated headers append
    to the same folio. Bidirectional format marks are stripped before matching
    so RTL Word documents still produce folio keys. Table cells are walked in
    document order.
    """

    source = Path(path)
    try:
        document = Document(str(source))
    except (OSError, ValueError, KeyError, BadZipFile, PackageNotFoundError) as exc:
        raise GroundTruthError(f"Cannot read ground-truth DOCX {source}: {exc}") from exc

    page_text: dict[str, list[str]] = {}
    current: str | None = None
    warnings: list[str] = []
    table_rows = 0
    unused_story_chars = 0
    for block in iter_docx_blocks(document):
        paragraphs: Iterable[Paragraph]
        if isinstance(block, Table):
            table_rows += len(block.rows)
            paragraphs = _cell_paragraphs(block)
        else:
            paragraphs = (block,)
        for paragraph in paragraphs:
            text = strip_bidi_format(paragraph.text or "")
            if not text:
                continue
            header = FOLIO_RE.fullmatch(text)
            if header is not None:
                current = header.group(1).lower()
                page_text.setdefault(current, [])
                continue
            if FOLIO_LIKE_RE.fullmatch(text):
                warnings.append(f"Unmatched folio-like line ignored: {text}")
                continue
            if current is not None:
                page_text[current].append(text)
            else:
                unused_story_chars += len(text)

    if not page_text:
        detail = []
        if table_rows:
            detail.append(f"{table_rows} table row(s) scanned")
        if unused_story_chars:
            detail.append("text was found outside folio headers")
        suffix = f" ({'; '.join(detail)})" if detail else ""
        raise GroundTruthError(
            f"Ground-truth DOCX {source} contains no [folio] page headers{suffix}"
        )
    pages = {
        key: tuple(GroundTruthLine(index, text) for index, text in enumerate(lines))
        for key, lines in page_text.items()
    }
    return GroundTruthBook(source, MappingProxyType(pages), tuple(warnings))

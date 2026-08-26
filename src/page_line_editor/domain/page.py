"""Ordered, editable PAGE document model with immutable original snapshots."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .geometry import Polygon, Polyline


@dataclass(slots=True)
class TextLine:
    id: str
    region_id: str
    source_order: int
    original_text: str
    original_polygon: Polygon
    original_baseline: Polyline | None
    text: str
    polygon: Polygon
    baseline: Polyline | None
    xml_path: str
    has_word_content: bool = False
    warnings: list[str] = field(default_factory=list)
    proposal_id: str | None = None
    proposal_state: str = ""
    diff_text: str = ""
    pre_correction_text: str | None = None
    original_deleted: bool = False
    deleted: bool = False

    @property
    def stable_id(self) -> str:
        return self.id

    @property
    def source_index(self) -> int:
        return self.source_order

    @property
    def current_text(self) -> str:
        return self.text

    @current_text.setter
    def current_text(self, value: str) -> None:
        self.text = value

    @property
    def current_polygon(self) -> Polygon:
        return self.polygon

    @current_polygon.setter
    def current_polygon(self, value: Polygon) -> None:
        self.polygon = value if isinstance(value, Polygon) else Polygon(value)

    @property
    def current_baseline(self) -> Polyline | None:
        return self.baseline

    @current_baseline.setter
    def current_baseline(self, value: Polyline | None) -> None:
        self.baseline = value if value is None or isinstance(value, Polyline) else Polyline(value)

    @property
    def dirty_fields(self) -> frozenset[str]:
        fields: set[str] = set()
        if self.text != self.original_text:
            fields.add("text")
        if self.polygon != self.original_polygon:
            fields.add("polygon")
        if self.baseline != self.original_baseline:
            fields.add("baseline")
        if self.deleted != self.original_deleted:
            fields.add("deleted")
        return frozenset(fields)

    @property
    def is_dirty(self) -> bool:
        return bool(self.dirty_fields)

    def mark_clean(self) -> None:
        self.original_text = self.text
        self.original_polygon = self.polygon
        self.original_baseline = self.baseline
        self.original_deleted = self.deleted


@dataclass(slots=True)
class TextRegion:
    id: str
    source_order: int
    lines: list[TextLine]
    polygon: Polygon | None = None
    xml_path: str = ""

    def __iter__(self) -> Iterator[TextLine]:
        return iter(self.lines)


@dataclass(slots=True)
class PageDocument:
    source_path: Path
    namespace: str
    image_filename: str
    image_width: int
    image_height: int
    regions: list[TextRegion]
    xml_tree: Any = field(repr=False)
    xml_encoding: str = "UTF-8"
    xml_standalone: bool | None = None
    image_path: Path | None = None
    validation_report: Any | None = None
    revision: int = 0
    load_warnings: list[str] = field(default_factory=list)

    @property
    def lines(self) -> list[TextLine]:
        return [line for region in self.regions for line in region.lines]

    @property
    def active_lines(self) -> list[TextLine]:
        """Lines currently present in the editable PAGE document."""
        return [line for line in self.lines if not line.deleted]

    def line_by_id(self, line_id: str) -> TextLine:
        matches = [line for line in self.lines if line.id == line_id]
        if not matches:
            raise KeyError(line_id)
        if len(matches) > 1:
            raise KeyError(f"Duplicate line id: {line_id}")
        return matches[0]

    @property
    def is_dirty(self) -> bool:
        return any(line.is_dirty for line in self.lines)

    def mark_clean(self, *, xml_tree: Any | None = None) -> None:
        # Once an atomic save commits a deletion, the retained raw tree no
        # longer contains that element. Drop its tombstone so later saves never
        # try to resolve a path which cannot exist in the new tree.
        for region in self.regions:
            region.lines[:] = [line for line in region.lines if not line.deleted]
        for line in self.lines:
            line.mark_clean()
        if xml_tree is not None:
            self.xml_tree = xml_tree
        self.revision += 1

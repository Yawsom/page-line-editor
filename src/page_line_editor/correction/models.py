"""Immutable inputs and outputs for the automatic correction engine.

The correction worker must never receive the GUI's live PAGE document.  These
small value objects form the boundary between the worker and the editor and are
also deliberately straightforward to serialise in audit reports.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

Point = tuple[int, int]


class CorrectionStatus(StrEnum):
    MATCH = "MATCH"
    OCR = "OCR"
    MERGE = "MERGE"
    SPLIT = "SPLIT"
    EXTRA = "EXTRA"
    MISSING = "MISSING"


STATUSES: tuple[str, ...] = tuple(status.value for status in CorrectionStatus)


@dataclass(frozen=True, slots=True)
class BoundingBox:
    x_min: int
    y_min: int
    x_max: int
    y_max: int

    @property
    def width(self) -> int:
        return self.x_max - self.x_min

    def union(self, other: BoundingBox) -> BoundingBox:
        return BoundingBox(
            min(self.x_min, other.x_min),
            min(self.y_min, other.y_min),
            max(self.x_max, other.x_max),
            max(self.y_max, other.y_max),
        )

    @classmethod
    def from_points(cls, points: Sequence[Point]) -> BoundingBox:
        if not points:
            return cls(0, 0, 0, 0)
        xs = [point[0] for point in points]
        ys = [point[1] for point in points]
        return cls(min(xs), min(ys), max(xs), max(ys))


@dataclass(frozen=True, slots=True)
class CorrectionLine:
    """Read-only snapshot of one PAGE ``TextLine``."""

    line_id: str
    text: str
    polygon: tuple[Point, ...] = ()
    baseline: tuple[Point, ...] = ()
    source_index: int = 0
    region_id: str | None = None
    noise: bool | None = None
    merged_from: tuple[str, ...] = ()

    @property
    def bbox(self) -> BoundingBox:
        return BoundingBox.from_points(self.polygon)

    @property
    def baseline_y(self) -> float:
        if self.baseline:
            return sum(point[1] for point in self.baseline) / len(self.baseline)
        return (self.bbox.y_min + self.bbox.y_max) / 2


@dataclass(frozen=True, slots=True)
class GroundTruthLine:
    index: int
    text: str


@dataclass(frozen=True, slots=True)
class PageCorrectionInput:
    xml_filename: str
    lines: tuple[CorrectionLine, ...]
    folio: str | None = None
    image_filename: str | None = None


@dataclass(frozen=True, slots=True)
class CharDiff:
    tag: str  # equal | replace | delete | insert
    before: str
    after: str


@dataclass(frozen=True, slots=True)
class LineState:
    """A complete reversible line state.

    ``deleted`` represents removal from the in-memory document.  The state
    retains geometry and text even when deleted so Reject can restore it.
    """

    line_id: str
    text: str
    polygon: tuple[Point, ...]
    baseline: tuple[Point, ...]
    region_id: str | None = None
    deleted: bool = False


@dataclass(frozen=True, slots=True)
class LineCorrectionProposal:
    proposal_id: str
    record_key: str
    xml_filename: str
    status: CorrectionStatus
    line_ids: tuple[str, ...]
    gt_indexes: tuple[int, ...]
    before: tuple[LineState, ...]
    after: tuple[LineState, ...]
    before_text: str
    after_text: str | None
    ratio: float | None
    baseline_y: float | None
    bbox: BoundingBox | None
    flags: tuple[str, ...] = ()
    char_diffs: tuple[CharDiff, ...] = ()
    automatically_applied: bool = True

    @property
    def actionable(self) -> bool:
        return self.before != self.after

    @property
    def primary_line_id(self) -> str | None:
        return self.line_ids[0] if self.line_ids else None


@dataclass(frozen=True, slots=True)
class PageCorrectionProposal:
    xml_filename: str
    proposals: tuple[LineCorrectionProposal, ...]
    folio: str | None = None
    image_filename: str | None = None
    source_line_count: int = 0
    ground_truth_line_count: int = 0

    @property
    def records(self) -> Mapping[str, LineCorrectionProposal]:
        return {proposal.record_key: proposal for proposal in self.proposals}


@dataclass(frozen=True, slots=True)
class FolderCorrectionProposal:
    pages: tuple[PageCorrectionProposal, ...]
    cancelled: bool = False
    errors: Mapping[str, str] = field(default_factory=dict)

    @property
    def records(self) -> Mapping[str, LineCorrectionProposal]:
        return {
            proposal.record_key: proposal
            for page in self.pages
            for proposal in page.proposals
            if proposal.line_ids
        }


@dataclass(frozen=True, slots=True)
class CorrectionSettings:
    delete_all_extras: bool = False
    apply_noise_deletions: bool = True


def record_key(xml_filename: str, line_id: str) -> str:
    """Return the stable report key required by the audit format."""

    return f"{Path(xml_filename).name}::{line_id}"


def _attr(value: Any, *names: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        for name in names:
            if name in value:
                return value[name]
        return default
    for name in names:
        if hasattr(value, name):
            return getattr(value, name)
    return default


def _points(value: Any) -> tuple[Point, ...]:
    if value is None:
        return ()
    points: list[Point] = []
    for point in value:
        if isinstance(point, Mapping):
            x, y = point.get("x"), point.get("y")
        elif hasattr(point, "x") and hasattr(point, "y"):
            x_value, y_value = point.x, point.y
            x = x_value() if callable(x_value) else x_value
            y = y_value() if callable(y_value) else y_value
        else:
            x, y = point[0], point[1]
        if x is None or y is None:
            raise ValueError("Geometry points require numeric x and y values")
        points.append((int(round(float(x))), int(round(float(y)))))
    return tuple(points)


def coerce_line(value: Any, source_index: int = 0) -> CorrectionLine:
    """Adapt a domain line, mapping, or ``CorrectionLine`` without mutation."""

    if isinstance(value, CorrectionLine):
        return value
    line_id = _attr(value, "line_id", "id")
    if not line_id:
        raise ValueError("Every correction line requires a persistent TextLine ID")
    return CorrectionLine(
        line_id=str(line_id),
        text=str(_attr(value, "text", "current_text", default="") or ""),
        polygon=_points(_attr(value, "polygon", "coords", "current_polygon", default=())),
        baseline=_points(_attr(value, "baseline", "current_baseline", default=())),
        source_index=int(_attr(value, "source_index", "reading_order", default=source_index)),
        region_id=_attr(value, "region_id"),
        noise=_attr(value, "noise"),
        merged_from=tuple(_attr(value, "merged_from", default=()) or ()),
    )


def coerce_page(value: Any) -> PageCorrectionInput:
    if isinstance(value, PageCorrectionInput):
        return value
    filename = _attr(value, "xml_filename", "filename")
    if filename is None:
        source_path = _attr(value, "source_path", "xml_path")
        filename = Path(source_path).name if source_path else None
    if not filename:
        raise ValueError("A page correction input requires an XML filename")
    raw_lines: Iterable[Any] = _attr(value, "lines", default=())
    lines = tuple(coerce_line(line, index) for index, line in enumerate(raw_lines))
    return PageCorrectionInput(
        xml_filename=Path(str(filename)).name,
        lines=lines,
        folio=_attr(value, "folio"),
        image_filename=_attr(value, "image_filename"),
    )


def coerce_ground_truth(values: Iterable[Any]) -> tuple[GroundTruthLine, ...]:
    result: list[GroundTruthLine] = []
    for index, value in enumerate(values):
        if isinstance(value, GroundTruthLine):
            result.append(value)
        elif isinstance(value, str):
            result.append(GroundTruthLine(index, value))
        else:
            result.append(
                GroundTruthLine(
                    int(_attr(value, "index", default=index)),
                    str(_attr(value, "text", default="") or ""),
                )
            )
    return tuple(result)

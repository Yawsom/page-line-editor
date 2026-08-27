"""Small duck-typed adapters between the Qt scene and the domain model.

The domain package deliberately has no Qt dependency.  These helpers accept the
public ``TextLine`` surface (id/text/polygon/baseline), while also tolerating
``current_*`` names used by richer document models.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, is_dataclass, replace
from typing import Any, Protocol, cast, runtime_checkable

PointTuple = tuple[float, float]
Geometry = tuple[tuple[PointTuple, ...], tuple[PointTuple, ...]]


@runtime_checkable
class TextLineLike(Protocol):
    id: str
    text: str
    polygon: Any
    baseline: Any


def point_xy(point: Any) -> PointTuple:
    """Return coordinates from a tuple, Qt point, or domain point."""

    if hasattr(point, "x"):
        x_value = point.x() if callable(point.x) else point.x
        y_value = point.y() if callable(point.y) else point.y
        return float(x_value), float(y_value)
    return float(point[0]), float(point[1])


def shape_points(shape: Any) -> tuple[PointTuple, ...]:
    if shape is None:
        return ()
    values = shape.points if hasattr(shape, "points") else shape
    return tuple(point_xy(point) for point in values)


def _point_like(sample: Any, xy: PointTuple) -> Any:
    x, y = xy
    if sample is None or isinstance(sample, tuple):
        return (x, y)
    if isinstance(sample, list):
        return [x, y]
    try:
        return type(sample)(x, y)
    except (TypeError, ValueError):
        return (x, y)


def _shape_like(shape: Any, points: Sequence[PointTuple]) -> Any:
    if shape is None:
        return tuple(points)
    source_points = shape.points if hasattr(shape, "points") else shape
    sample = next(iter(source_points), None)
    converted = tuple(_point_like(sample, point) for point in points)
    if hasattr(shape, "points"):
        if is_dataclass(shape):
            return replace(cast(Any, shape), points=converted)
        try:
            return type(shape)(converted)
        except (TypeError, ValueError):
            try:
                shape.points = converted
                return shape
            except (AttributeError, TypeError):
                return converted
    return list(converted) if isinstance(shape, list) else converted


def _read(source: Any, names: Iterable[str], default: Any = None) -> Any:
    for name in names:
        if hasattr(source, name):
            return getattr(source, name)
    return default


@dataclass(slots=True)
class LineAdapter:
    """Editable UI snapshot backed by an optional domain ``TextLine`` object.

    Mutations are best effort on the source and are always mirrored in the UI
    snapshot.  ``on_change`` lets an application/session layer apply immutable
    model replacements when its domain objects are frozen.
    """

    source: Any
    on_change: Callable[[str, str, Any], None] | None = None
    _text: str = ""
    _polygon: tuple[PointTuple, ...] = ()
    _baseline: tuple[PointTuple, ...] = ()

    def __post_init__(self) -> None:
        self._text = str(_read(self.source, ("current_text", "text"), ""))
        self._polygon = shape_points(_read(self.source, ("current_polygon", "polygon"), ()))
        self._baseline = shape_points(_read(self.source, ("current_baseline", "baseline"), ()))

    @property
    def id(self) -> str:
        return str(_read(self.source, ("id", "line_id"), ""))

    @property
    def text(self) -> str:
        return self._text

    @property
    def polygon(self) -> tuple[PointTuple, ...]:
        return self._polygon

    @property
    def baseline(self) -> tuple[PointTuple, ...]:
        return self._baseline

    @property
    def diff_text(self) -> str:
        value = _read(self.source, ("diff_text", "correction_diff", "diff"), "")
        return str(value or "")

    @property
    def proposal_state(self) -> str:
        value = _read(self.source, ("proposal_state", "correction_state", "status"), "")
        return str(getattr(value, "value", value) or "").lower()

    @property
    def correction_status(self) -> str:
        value = _read(self.source, ("correction_status",), "")
        status = str(getattr(value, "value", value) or "").upper()
        return {"MATCH": "MATCHED", "EXTRA": "REMOVED"}.get(status, status)

    @property
    def pre_correction_text(self) -> str:
        value = _read(self.source, ("pre_correction_text", "original_text"), "")
        return str(value or "")

    def set_text(self, value: str) -> None:
        self._text = value
        self._write(("current_text", "text"), value, "text")

    def geometry(self) -> Geometry:
        return self._polygon, self._baseline

    def set_geometry(
        self,
        polygon: Sequence[PointTuple],
        baseline: Sequence[PointTuple],
    ) -> None:
        self._polygon = tuple((float(x), float(y)) for x, y in polygon)
        self._baseline = tuple((float(x), float(y)) for x, y in baseline)
        old_polygon = _read(self.source, ("current_polygon", "polygon"), ())
        old_baseline = _read(self.source, ("current_baseline", "baseline"), ())
        self._write(
            ("current_polygon", "polygon"),
            _shape_like(old_polygon, self._polygon),
            "polygon",
        )
        self._write(
            ("current_baseline", "baseline"),
            _shape_like(old_baseline, self._baseline),
            "baseline",
        )

    def _write(self, names: tuple[str, ...], value: Any, field: str) -> None:
        written = False
        for name in names:
            if hasattr(self.source, name):
                try:
                    setattr(self.source, name, value)
                    written = True
                except (AttributeError, TypeError):
                    pass
                break
        if self.on_change is not None:
            self.on_change(self.id, field, value)
        elif not written:
            # A frozen model is still usable as a UI snapshot. The integration
            # layer can consume MainWindow's edit signals to replace it.
            return

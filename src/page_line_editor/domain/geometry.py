"""Geometry primitives in PAGE image-pixel coordinates."""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from math import hypot


class GeometryError(ValueError):
    """Raised when edited PAGE geometry is not representable."""


@dataclass(frozen=True, slots=True, order=True)
class Point:
    x: int
    y: int

    def __post_init__(self) -> None:
        # UI coordinates arrive as floats. PAGE persists pixel coordinates, so
        # quantize once at the Qt-free model boundary.
        object.__setattr__(self, "x", int(round(self.x)))
        object.__setattr__(self, "y", int(round(self.y)))

    def translated(self, dx: int, dy: int) -> Point:
        return Point(self.x + dx, self.y + dy)

    def distance_to(self, other: Point) -> float:
        return hypot(self.x - other.x, self.y - other.y)


def parse_points(value: str, *, minimum: int = 1) -> tuple[Point, ...]:
    """Parse PAGE's ordered ``x,y x,y`` point syntax."""
    points: list[Point] = []
    for token in value.split():
        pieces = token.split(",")
        if len(pieces) != 2:
            raise GeometryError(f"Invalid PAGE point {token!r}")
        try:
            x, y = (int(piece) for piece in pieces)
        except ValueError as exc:
            raise GeometryError(f"Non-integer PAGE point {token!r}") from exc
        if x < 0 or y < 0:
            raise GeometryError(f"Negative PAGE point {token!r}")
        points.append(Point(x, y))
    if len(points) < minimum:
        raise GeometryError(f"Expected at least {minimum} points, found {len(points)}")
    return tuple(points)


def format_points(points: Iterable[Point]) -> str:
    return " ".join(f"{point.x},{point.y}" for point in points)


def _orientation(a: Point, b: Point, c: Point) -> int:
    value = (b.y - a.y) * (c.x - b.x) - (b.x - a.x) * (c.y - b.y)
    return (value > 0) - (value < 0)


def _on_segment(a: Point, b: Point, c: Point) -> bool:
    return min(a.x, c.x) <= b.x <= max(a.x, c.x) and min(a.y, c.y) <= b.y <= max(a.y, c.y)


def segments_intersect(a: Point, b: Point, c: Point, d: Point) -> bool:
    orientations = (
        _orientation(a, b, c),
        _orientation(a, b, d),
        _orientation(c, d, a),
        _orientation(c, d, b),
    )
    if orientations[0] != orientations[1] and orientations[2] != orientations[3]:
        return True
    return any(
        orientation == 0 and _on_segment(start, point, end)
        for orientation, start, point, end in (
            (orientations[0], a, c, b),
            (orientations[1], a, d, b),
            (orientations[2], c, a, d),
            (orientations[3], c, b, d),
        )
    )


@dataclass(frozen=True, slots=True)
class Polyline:
    points: tuple[Point, ...]

    def __init__(self, points: Sequence[Point] | Iterable[Point]) -> None:
        ordered = tuple(points)
        if len(ordered) < 2:
            raise GeometryError("A baseline requires at least two points")
        object.__setattr__(self, "points", ordered)

    @classmethod
    def from_page(cls, value: str) -> Polyline:
        return cls(parse_points(value, minimum=2))

    def to_page(self) -> str:
        return format_points(self.points)

    def translated(self, dx: int, dy: int) -> Polyline:
        return Polyline(point.translated(dx, dy) for point in self.points)

    def __iter__(self) -> Iterator[Point]:
        return iter(self.points)


@dataclass(frozen=True, slots=True)
class Polygon:
    points: tuple[Point, ...]

    def __init__(self, points: Sequence[Point] | Iterable[Point]) -> None:
        ordered = tuple(points)
        # PAGE source sometimes explicitly repeats the first vertex. Preserve it,
        # but count distinct closure vertices for validity.
        distinct = ordered[:-1] if len(ordered) > 1 and ordered[0] == ordered[-1] else ordered
        if len(distinct) < 3:
            raise GeometryError("A polygon requires at least three points")
        object.__setattr__(self, "points", ordered)

    @classmethod
    def from_page(cls, value: str) -> Polygon:
        return cls(parse_points(value, minimum=3))

    def to_page(self) -> str:
        return format_points(self.points)

    @property
    def vertices(self) -> tuple[Point, ...]:
        if self.points[0] == self.points[-1]:
            return self.points[:-1]
        return self.points

    def translated(self, dx: int, dy: int) -> Polygon:
        return Polygon(point.translated(dx, dy) for point in self.points)

    def contains(self, point: Point, *, include_boundary: bool = True) -> bool:
        vertices = self.vertices
        inside = False
        previous = vertices[-1]
        for current in vertices:
            if _orientation(previous, point, current) == 0 and _on_segment(
                previous, point, current
            ):
                return include_boundary
            if (current.y > point.y) != (previous.y > point.y):
                cross_x = (previous.x - current.x) * (point.y - current.y) / (
                    previous.y - current.y
                ) + current.x
                if point.x < cross_x:
                    inside = not inside
            previous = current
        return inside

    def is_self_intersecting(self) -> bool:
        vertices = self.vertices
        count = len(vertices)
        for i in range(count):
            a, b = vertices[i], vertices[(i + 1) % count]
            for j in range(i + 1, count):
                if j in {i, (i + 1) % count} or (j + 1) % count in {i, (i + 1) % count}:
                    continue
                if segments_intersect(a, b, vertices[j], vertices[(j + 1) % count]):
                    return True
        return False

    def __iter__(self) -> Iterator[Point]:
        return iter(self.points)

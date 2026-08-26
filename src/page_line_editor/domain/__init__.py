"""Qt-free document domain types."""

from .geometry import GeometryError, Point, Polygon, Polyline
from .page import PageDocument, TextLine, TextRegion

__all__ = [
    "GeometryError",
    "PageDocument",
    "Point",
    "Polygon",
    "Polyline",
    "TextLine",
    "TextRegion",
]

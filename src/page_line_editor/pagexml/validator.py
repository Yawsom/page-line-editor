"""Offline schema and semantic validation for editable PAGE 2013 files."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from enum import StrEnum
from functools import lru_cache
from importlib.resources import files

from lxml import etree  # type: ignore[import-untyped]

from page_line_editor.domain.geometry import GeometryError, Polygon, Polyline
from page_line_editor.domain.page import PageDocument

from .parser import PAGE_2013_NAMESPACE


class Severity(StrEnum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    code: str
    message: str
    severity: Severity = Severity.ERROR
    line_id: str | None = None


@dataclass(slots=True)
class ValidationReport:
    strict_valid: bool
    core_valid: bool
    issues: list[ValidationIssue] = field(default_factory=list)
    strict_schema_errors: list[str] = field(default_factory=list)
    core_schema_errors: list[str] = field(default_factory=list)

    @property
    def errors(self) -> list[ValidationIssue]:
        """Return errors."""
        return [issue for issue in self.issues if issue.severity == Severity.ERROR]

    @property
    def warnings(self) -> list[ValidationIssue]:
        """Return warnings."""
        return [issue for issue in self.issues if issue.severity == Severity.WARNING]

    @property
    def can_save(self) -> bool:
        """Return whether save."""
        return self.core_valid and not self.errors

    @property
    def valid(self) -> bool:
        """Return valid."""
        return self.can_save


def _parser() -> etree.XMLParser:
    """Return parser."""
    return etree.XMLParser(
        resolve_entities=False, no_network=True, load_dtd=False, recover=False, huge_tree=False
    )


@lru_cache(maxsize=1)
def _schema() -> etree.XMLSchema:
    """Return schema."""
    resource = files("page_line_editor.pagexml").joinpath("schemas/pagecontent-2013-07-15.xsd")
    with resource.open("rb") as stream:
        return etree.XMLSchema(etree.parse(stream, parser=_parser()))


def _schema_errors(schema: etree.XMLSchema, tree: etree._ElementTree) -> list[str]:
    """Return normalized XML-schema validation errors."""
    if schema.validate(tree):
        return []
    return [entry.message for entry in schema.error_log]


def _core_tree(tree: etree._ElementTree) -> etree._ElementTree:
    """Return core tree."""
    clone = deepcopy(tree)
    namespace = PAGE_2013_NAMESPACE
    metadata = clone.getroot().find(f"{{{namespace}}}Metadata")
    if metadata is not None:
        # Current Transkribus PAGE exports place this vendor extension in the
        # PAGE namespace. It is ignored only in the disposable validation copy.
        for child in list(metadata):
            if (
                etree.QName(child).namespace == namespace
                and etree.QName(child).localname == "TranskribusMetadata"
            ):
                metadata.remove(child)
    return clone


def _int_attribute(element: etree._Element, name: str, issues: list[ValidationIssue]) -> int | None:
    """Return an optional integer XML attribute and collect validation issues."""
    try:
        value = int(element.get(name, ""))
    except ValueError:
        issues.append(ValidationIssue("page.dimension", f"Page/@{name} must be an integer"))
        return None
    if value <= 0:
        issues.append(ValidationIssue("page.dimension", f"Page/@{name} must be positive"))
        return None
    return value


def _semantic_issues(tree: etree._ElementTree) -> list[ValidationIssue]:
    """Return semantic PAGE validation issues for the parsed tree."""
    issues: list[ValidationIssue] = []
    root = tree.getroot()
    namespace = etree.QName(root).namespace
    if namespace != PAGE_2013_NAMESPACE:
        return [
            ValidationIssue("namespace.unsupported", f"Unsupported PAGE namespace: {namespace}")
        ]

    def q(name: str) -> str:
        """Build a qualified PAGE XML element name."""
        return f"{{{namespace}}}{name}"

    page = root.find(q("Page"))
    if page is None:
        return [ValidationIssue("page.missing", "PAGE document has no Page element")]
    width = _int_attribute(page, "imageWidth", issues)
    height = _int_attribute(page, "imageHeight", issues)

    ids: dict[str, etree._Element] = {}
    for element in root.iter():
        element_id = element.get("id")
        if not element_id:
            continue
        if element_id in ids:
            issues.append(
                ValidationIssue(
                    "id.duplicate", f"Duplicate PAGE id: {element_id}", line_id=element_id
                )
            )
        else:
            ids[element_id] = element

    for line_order, line_element in enumerate(page.iter(q("TextLine"))):
        source_id = line_element.get("id")
        line_id = source_id or f"line at source position {line_order + 1}"
        if not source_id:
            issues.append(
                ValidationIssue(
                    "line.id.missing",
                    "TextLine requires a persistent id",
                    line_id=line_id,
                )
            )
        coords = line_element.find(q("Coords"))
        if coords is None or not coords.get("points"):
            issues.append(
                ValidationIssue(
                    "line.coords.missing", "TextLine requires Coords/@points", line_id=line_id
                )
            )
            continue
        polygon: Polygon | None = None
        try:
            polygon = Polygon.from_page(coords.get("points", ""))
        except GeometryError as exc:
            issues.append(ValidationIssue("line.coords.syntax", str(exc), line_id=line_id))
        baseline_element = line_element.find(q("Baseline"))
        baseline: Polyline | None = None
        if baseline_element is not None:
            try:
                baseline = Polyline.from_page(baseline_element.get("points", ""))
            except GeometryError as exc:
                issues.append(ValidationIssue("line.baseline.syntax", str(exc), line_id=line_id))
        if polygon is not None and polygon.is_self_intersecting():
            issues.append(
                ValidationIssue(
                    "line.coords.self_intersection", "Line polygon self-intersects", line_id=line_id
                )
            )
        geometries = list(polygon.points if polygon else ()) + list(
            baseline.points if baseline else ()
        )
        if width is not None and height is not None:
            for point in geometries:
                if point.x < 0 or point.y < 0 or point.x > width or point.y > height:
                    issues.append(
                        ValidationIssue(
                            "line.geometry.bounds",
                            f"Point {point.x},{point.y} is outside the {width}x{height} page",
                            line_id=line_id,
                        )
                    )
                    break
                if point.x == width or point.y == height:
                    issues.append(
                        ValidationIssue(
                            "line.geometry.edge",
                            f"Point {point.x},{point.y} sits on the PAGE image edge",
                            Severity.WARNING,
                            line_id,
                        )
                    )
                    break
        if (
            polygon is not None
            and baseline is not None
            and any(not polygon.contains(point) for point in baseline.points)
        ):
            issues.append(
                ValidationIssue(
                    "line.baseline.outside",
                    "Baseline is not fully contained by its line polygon",
                    Severity.WARNING,
                    line_id,
                )
            )
        parent_region = next(
            (
                ancestor
                for ancestor in line_element.iterancestors()
                if ancestor.tag == q("TextRegion")
            ),
            None,
        )
        region_coords = parent_region.find(q("Coords")) if parent_region is not None else None
        if polygon is not None and region_coords is not None and region_coords.get("points"):
            try:
                region_polygon = Polygon.from_page(region_coords.get("points", ""))
            except GeometryError:
                region_polygon = None
            if region_polygon is not None and any(
                not region_polygon.contains(point) for point in polygon.vertices
            ):
                issues.append(
                    ValidationIssue(
                        "line.coords.outside_region",
                        "Line polygon is not fully contained by its TextRegion",
                        Severity.WARNING,
                        line_id,
                    )
                )

    for region_order, region in enumerate(page.iter(q("TextRegion"))):
        region_id = region.get("id") or f"region at source position {region_order + 1}"
        coords = region.find(q("Coords"))
        if coords is None or not coords.get("points"):
            issues.append(
                ValidationIssue(
                    "region.coords.missing",
                    "TextRegion requires Coords/@points",
                    line_id=region_id,
                )
            )
            continue
        try:
            polygon = Polygon.from_page(coords.get("points", ""))
        except GeometryError as exc:
            issues.append(ValidationIssue("region.coords.syntax", str(exc), line_id=region_id))
            continue
        if polygon.is_self_intersecting():
            issues.append(
                ValidationIssue(
                    "region.coords.self_intersection",
                    "TextRegion polygon self-intersects",
                    line_id=region_id,
                )
            )
        outside = (
            width is not None
            and height is not None
            and any(
                point.x < 0 or point.y < 0 or point.x > width or point.y > height
                for point in polygon.points
            )
        )
        if outside:
            issues.append(
                ValidationIssue(
                    "region.geometry.bounds",
                    f"TextRegion geometry is outside the {width}x{height} page",
                    line_id=region_id,
                )
            )
        elif width is not None and height is not None and any(
            point.x == width or point.y == height for point in polygon.points
        ):
            issues.append(
                ValidationIssue(
                    "region.geometry.edge",
                    "TextRegion geometry sits on the PAGE image edge",
                    Severity.WARNING,
                    region_id,
                )
            )
    return issues


def validate_tree(tree: etree._ElementTree) -> ValidationReport:
    """Validate tree."""
    schema = _schema()
    strict_errors = _schema_errors(schema, tree)
    core_errors = _schema_errors(schema, _core_tree(tree))
    issues = _semantic_issues(tree)
    if strict_errors and not core_errors:
        issues.append(
            ValidationIssue(
                "schema.vendor_extension",
                "Strict PAGE validation fails because allowlisted "
                "Transkribus metadata is preserved",
                Severity.WARNING,
            )
        )
    elif core_errors:
        issues.extend(ValidationIssue("schema.core", message) for message in core_errors)
    return ValidationReport(
        strict_valid=not strict_errors
        and not any(issue.severity == Severity.ERROR for issue in issues),
        core_valid=not core_errors,
        issues=issues,
        strict_schema_errors=strict_errors,
        core_schema_errors=core_errors,
    )


def validate_xml(xml: bytes | str) -> ValidationReport:
    """Validate xml."""
    try:
        root = etree.fromstring(xml if isinstance(xml, bytes) else xml.encode(), parser=_parser())
        tree = root.getroottree()
        if tree.docinfo.doctype:
            return ValidationReport(
                False, False, [ValidationIssue("xml.doctype", "DOCTYPE is not allowed")]
            )
    except etree.XMLSyntaxError as exc:
        return ValidationReport(False, False, [ValidationIssue("xml.syntax", str(exc))])
    return validate_tree(tree)


def validate_document(document: PageDocument) -> ValidationReport:
    """Validate a PAGE document by serializing its current candidate tree."""
    from .writer import build_candidate

    candidate, _ = build_candidate(document)
    return validate_xml(candidate)

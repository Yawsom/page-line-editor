"""Secure, loss-minimising PAGE XML parser."""

from __future__ import annotations

import re
from pathlib import Path

from lxml import etree  # type: ignore[import-untyped]

from page_line_editor.domain.geometry import GeometryError, Polygon, Polyline
from page_line_editor.domain.page import PageDocument, TextLine, TextRegion

PAGE_2013_NAMESPACE = "http://schema.primaresearch.org/PAGE/gts/pagecontent/2013-07-15"


class PageXmlError(ValueError):
    """A PAGE document cannot safely be opened for editing."""


def _secure_parser() -> etree.XMLParser:
    return etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        recover=False,
        load_dtd=False,
        remove_blank_text=False,
        strip_cdata=False,
        huge_tree=False,
    )


def _required_int(element: etree._Element, name: str) -> int:
    value = element.get(name)
    try:
        number = int(value) if value is not None else 0
    except ValueError as exc:
        raise PageXmlError(f"Page/@{name} must be an integer") from exc
    if number <= 0:
        raise PageXmlError(f"Page/@{name} must be positive")
    return number


def parse_page(path: str | Path) -> PageDocument:
    """Read a PAGE 2013 file while retaining its complete lxml tree."""
    source = Path(path)
    try:
        tree = etree.parse(str(source), parser=_secure_parser())
    except (OSError, etree.XMLSyntaxError) as exc:
        raise PageXmlError(f"Cannot parse {source}: {exc}") from exc
    if tree.docinfo.doctype:
        raise PageXmlError("DOCTYPE declarations are not supported")
    root = tree.getroot()
    namespace = etree.QName(root).namespace
    if namespace != PAGE_2013_NAMESPACE or etree.QName(root).localname != "PcGts":
        raise PageXmlError(f"Unsupported PAGE namespace: {namespace or '(none)'}")

    def q(name: str) -> str:
        return f"{{{namespace}}}{name}"

    page = root.find(q("Page"))
    if page is None:
        raise PageXmlError("PAGE document has no Page element")

    regions: list[TextRegion] = []
    seen_region_ids: dict[str, int] = {}
    seen_line_ids: dict[str, int] = {}
    line_order = 0
    for region_order, region_element in enumerate(page.iterfind(f".//{q('TextRegion')}")):
        source_region_id = region_element.get("id") or f"region-{region_order + 1}"
        seen_region_ids[source_region_id] = seen_region_ids.get(source_region_id, 0) + 1
        region_id = source_region_id
        region_coords = region_element.find(q("Coords"))
        region_polygon: Polygon | None = None
        if region_coords is not None and region_coords.get("points"):
            try:
                region_polygon = Polygon.from_page(region_coords.get("points", ""))
            except GeometryError:
                region_polygon = None

        lines: list[TextLine] = []
        # Only lines whose closest TextRegion ancestor is this region belong here.
        for line_element in region_element.iterfind(f".//{q('TextLine')}"):
            closest_region = next(
                (
                    ancestor
                    for ancestor in line_element.iterancestors()
                    if ancestor.tag == q("TextRegion")
                ),
                None,
            )
            if closest_region is not region_element:
                continue
            source_line_id = line_element.get("id") or f"{region_id}-line-{line_order + 1}"
            seen_line_ids[source_line_id] = seen_line_ids.get(source_line_id, 0) + 1
            # The XML path is the definitive identity inside the retained tree. IDs
            # remain unchanged so duplicate source IDs can be diagnosed faithfully.
            coords = line_element.find(q("Coords"))
            if coords is None or not coords.get("points"):
                raise PageXmlError(f"TextLine {source_line_id!r} has no Coords/@points")
            try:
                polygon = Polygon.from_page(coords.get("points", ""))
                baseline_element = line_element.find(q("Baseline"))
                baseline = (
                    Polyline.from_page(baseline_element.get("points", ""))
                    if baseline_element is not None and baseline_element.get("points")
                    else None
                )
            except GeometryError as exc:
                raise PageXmlError(
                    f"Invalid geometry on TextLine {source_line_id!r}: {exc}"
                ) from exc
            unicode_element = line_element.find(f"{q('TextEquiv')}/{q('Unicode')}")
            text = (
                unicode_element.text
                if unicode_element is not None and unicode_element.text is not None
                else ""
            )
            lines.append(
                TextLine(
                    id=source_line_id,
                    region_id=region_id,
                    source_order=line_order,
                    original_text=text,
                    original_polygon=polygon,
                    original_baseline=baseline,
                    text=text,
                    polygon=polygon,
                    baseline=baseline,
                    xml_path=tree.getpath(line_element),
                    has_word_content=line_element.find(q("Word")) is not None,
                )
            )
            line_order += 1
        regions.append(
            TextRegion(
                id=region_id,
                source_order=region_order,
                lines=lines,
                polygon=region_polygon,
                xml_path=tree.getpath(region_element),
            )
        )

    warnings: list[str] = []
    warnings.extend(
        f"Duplicate TextRegion id: {key}" for key, count in seen_region_ids.items() if count > 1
    )
    warnings.extend(
        f"Duplicate TextLine id: {key}" for key, count in seen_line_ids.items() if count > 1
    )
    encoding = tree.docinfo.encoding or "UTF-8"
    declaration = source.read_bytes()[:512]
    standalone_match = re.search(
        rb"standalone\s*=\s*['\"](yes|no)['\"]", declaration, re.IGNORECASE
    )
    standalone = (
        standalone_match.group(1).lower() == b"yes" if standalone_match is not None else None
    )
    document = PageDocument(
        source_path=source,
        namespace=namespace,
        image_filename=page.get("imageFilename", ""),
        image_width=_required_int(page, "imageWidth"),
        image_height=_required_int(page, "imageHeight"),
        regions=regions,
        xml_tree=tree,
        xml_encoding=encoding,
        xml_standalone=standalone,
        load_warnings=warnings,
    )
    # Delayed import avoids a parser/validator import cycle while still giving
    # every opened page its load-time validation baseline.
    from .validator import validate_tree

    document.validation_report = validate_tree(tree)
    return document

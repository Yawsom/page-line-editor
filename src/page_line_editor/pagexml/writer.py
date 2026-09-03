"""Narrow PAGE mutations and serialization."""

from __future__ import annotations

import re
from copy import deepcopy
from datetime import UTC, datetime

from lxml import etree  # type: ignore[import-untyped]

from page_line_editor.domain.page import PageDocument, TextLine

READING_ORDER_RE = re.compile(r"readingOrder\s*\{index:\s*\d+;\}")


class PageWriteError(ValueError):
    pass


def _text_line_elements(tree: etree._ElementTree, namespace: str) -> list[etree._Element]:
    """Return all TextLine elements in a PAGE tree."""
    return list(tree.iter(f"{{{namespace}}}TextLine"))


def _find_line(tree: etree._ElementTree, line: TextLine, namespace: str) -> etree._Element:
    """Resolve a TextLine by unique ``@id``. Positional getpath() is not identity."""
    line_id = line.id
    if not line_id:
        raise PageWriteError("Cannot resolve a TextLine with an empty id")
    matches = [
        element
        for element in _text_line_elements(tree, namespace)
        if element.get("id") == line_id
    ]
    if len(matches) != 1:
        if not matches:
            raise PageWriteError(f"Cannot resolve source element for line {line_id!r}")
        raise PageWriteError(f"Duplicate TextLine id {line_id!r} cannot be saved")
    return matches[0]


def refresh_xml_paths(document: PageDocument, tree: etree._ElementTree | None = None) -> None:
    """Recompute cached positional paths after a structural save.

    ``xml_path`` is lxml ``getpath()`` and shifts when earlier siblings are
    removed. The writer looks up by ``@id``; these caches must still match the
    retained tree so later diagnostics never point at a different line.
    """
    candidate = tree if tree is not None else document.xml_tree
    namespace = document.namespace
    by_id: dict[str, list[etree._Element]] = {}
    for element in _text_line_elements(candidate, namespace):
        element_id = element.get("id")
        if element_id:
            by_id.setdefault(element_id, []).append(element)
    region_qname = f"{{{namespace}}}TextRegion"
    for region in document.regions:
        region_matches = [
            element for element in candidate.iter(region_qname) if element.get("id") == region.id
        ]
        if len(region_matches) == 1:
            region.xml_path = candidate.getpath(region_matches[0])
        for line in region.lines:
            if line.deleted:
                continue
            matches = by_id.get(line.id, [])
            if len(matches) == 1:
                line.xml_path = candidate.getpath(matches[0])


def _ensure_baseline(line_element: etree._Element, namespace: str) -> etree._Element:
    """Return a Baseline element, creating it after Coords when required."""
    def q(name: str) -> str:
        """Build a qualified PAGE XML element name."""
        return f"{{{namespace}}}{name}"

    baseline = line_element.find(q("Baseline"))
    if baseline is not None:
        return baseline
    baseline = etree.Element(q("Baseline"))
    coords = line_element.find(q("Coords"))
    insert_at = line_element.index(coords) + 1 if coords is not None else 0
    line_element.insert(insert_at, baseline)
    return baseline


def _set_reading_order(element: etree._Element, index: int) -> None:
    """Store a PAGE reading-order index in an element custom attribute."""
    replacement = f"readingOrder {{index:{index};}}"
    custom = element.get("custom") or ""
    if READING_ORDER_RE.search(custom):
        custom = READING_ORDER_RE.sub(replacement, custom)
    else:
        custom = f"{custom} {replacement}".strip()
    element.set("custom", custom)


def _sync_line_text(line_element: etree._Element, namespace: str, text: str) -> None:
    """Write Unicode and drop stale Word/Glyph/PlainText so Transkribus shows the edit."""

    def q(name: str) -> str:
        """Build a qualified PAGE XML element name."""
        return f"{{{namespace}}}{name}"

    for child in list(line_element):
        local = etree.QName(child).localname
        if local in {"Word", "Glyph"}:
            line_element.remove(child)
    unicode_element = _ensure_unicode(line_element, namespace)
    unicode_element.text = text
    text_equiv = unicode_element.getparent()
    if text_equiv is not None:
        plain_text = text_equiv.find(q("PlainText"))
        if plain_text is not None:
            text_equiv.remove(plain_text)


def _refresh_dirty_regions(
    tree: etree._ElementTree,
    document: PageDocument,
    namespace: str,
    dirty_region_ids: set[str],
) -> None:
    """Refresh dirty region text and reading order after structural edits."""
    if not dirty_region_ids:
        return

    def q(name: str) -> str:
        """Build a qualified PAGE XML element name."""
        return f"{{{namespace}}}{name}"

    domain_regions = {region.id: region for region in document.regions}
    for region_idx, region in enumerate(tree.iter(q("TextRegion"))):
        region_id = region.get("id")
        if region_id not in dirty_region_ids:
            continue
        domain_region = domain_regions.get(region_id)
        if domain_region is None:
            raise PageWriteError(f"Cannot resolve source TextRegion {region_id!r}")

        # Reorder only TextLine siblings.  Detaching all of them first keeps
        # Coords, TextEquiv, comments, and vendor children in their original
        # slots while making the user's explicit line order durable in PAGE.
        source_lines = region.findall(q("TextLine"))
        source_by_id = {element.get("id"): element for element in source_lines}
        desired_ids = [line.id for line in domain_region.lines if not line.deleted]
        if len(source_by_id) != len(source_lines) or set(source_by_id) != set(desired_ids):
            raise PageWriteError(
                f"TextRegion {region_id!r} has an ambiguous or stale TextLine order"
            )
        line_slots = [index for index, child in enumerate(region) if child.tag == q("TextLine")]
        for element in source_lines:
            region.remove(element)
        for slot, line_id in zip(line_slots, desired_ids, strict=True):
            region.insert(slot, source_by_id[line_id])
        for text_equiv in region.findall(q("TextEquiv")):
            unicode_element = text_equiv.find(q("Unicode"))
            if unicode_element is not None:
                unicode_element.text = None
            plain_text = text_equiv.find(q("PlainText"))
            if plain_text is not None:
                plain_text.text = None
        for index, line_element in enumerate(region.findall(q("TextLine"))):
            _set_reading_order(line_element, index)
        custom = region.get("custom") or ""
        if READING_ORDER_RE.search(custom):
            _set_reading_order(region, region_idx)


def _ensure_unicode(line_element: etree._Element, namespace: str) -> etree._Element:
    """Return a Unicode element, creating the required TextEquiv structure."""
    def q(name: str) -> str:
        """Build a qualified PAGE XML element name."""
        return f"{{{namespace}}}{name}"

    text_equiv = line_element.find(q("TextEquiv"))
    if text_equiv is None:
        text_equiv = etree.Element(q("TextEquiv"))
        text_style = line_element.find(q("TextStyle"))
        if text_style is not None:
            line_element.insert(line_element.index(text_style), text_equiv)
        else:
            line_element.append(text_equiv)
    unicode_element = text_equiv.find(q("Unicode"))
    if unicode_element is None:
        unicode_element = etree.Element(q("Unicode"))
        # PAGE 2013 orders optional PlainText before Unicode.
        plain_text = text_equiv.find(q("PlainText"))
        if plain_text is None:
            text_equiv.insert(0, unicode_element)
        else:
            text_equiv.insert(text_equiv.index(plain_text) + 1, unicode_element)
    return unicode_element


def apply_document(
    document: PageDocument, tree: etree._ElementTree | None = None
) -> etree._ElementTree:
    """Clone the raw tree and apply only dirty line fields and LastChange."""
    candidate = deepcopy(tree if tree is not None else document.xml_tree)
    changed = False
    namespace = document.namespace

    def q(name: str) -> str:
        """Build a qualified PAGE XML element name."""
        return f"{{{namespace}}}{name}"

    dirty_region_ids = {line.region_id for line in document.lines if line.is_dirty}
    for line in document.lines:
        if not line.is_dirty:
            continue
        element = _find_line(candidate, line, namespace)
        if "deleted" in line.dirty_fields and line.deleted:
            parent = element.getparent()
            if parent is None:
                raise PageWriteError(f"TextLine {line.id!r} cannot be removed")
            parent.remove(element)
            changed = True
            continue
        if "polygon" in line.dirty_fields:
            coords = element.find(q("Coords"))
            if coords is None:
                raise PageWriteError(f"TextLine {line.id!r} has lost its Coords element")
            coords.set("points", line.polygon.to_page())
        if "baseline" in line.dirty_fields:
            existing = element.find(q("Baseline"))
            if line.baseline is None:
                if existing is not None:
                    element.remove(existing)
            else:
                _ensure_baseline(element, namespace).set("points", line.baseline.to_page())
        if "text" in line.dirty_fields:
            _sync_line_text(element, namespace, line.text)
        changed = True
    if dirty_region_ids:
        _refresh_dirty_regions(candidate, document, namespace, dirty_region_ids)
        changed = True
    if changed:
        metadata = candidate.getroot().find(q("Metadata"))
        if metadata is None:
            raise PageWriteError("PAGE document has no Metadata element")
        last_change = metadata.find(q("LastChange"))
        if last_change is None:
            last_change = etree.Element(q("LastChange"))
            created = metadata.find(q("Created"))
            metadata.insert(
                metadata.index(created) + 1 if created is not None else len(metadata), last_change
            )
        last_change.text = datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    return candidate


def serialize_tree(tree: etree._ElementTree, document: PageDocument) -> bytes:
    """Serialize a PAGE tree with the source document serialization settings."""
    options: dict[str, object] = {
        "encoding": document.xml_encoding,
        "xml_declaration": True,
        "pretty_print": False,
    }
    if document.xml_standalone is not None:
        options["standalone"] = document.xml_standalone
    return etree.tostring(tree, **options)


def build_candidate(document: PageDocument) -> tuple[bytes, etree._ElementTree]:
    """Build serialized candidate XML and its validated mutable tree."""
    tree = apply_document(document)
    return serialize_tree(tree, document), tree

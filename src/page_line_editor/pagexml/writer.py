"""Narrow PAGE mutations and serialization."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime

from lxml import etree  # type: ignore[import-untyped]

from page_line_editor.domain.page import PageDocument, TextLine


class PageWriteError(ValueError):
    pass


def _find_line(tree: etree._ElementTree, line: TextLine) -> etree._Element:
    matches = tree.xpath(line.xml_path)
    if len(matches) != 1 or not isinstance(matches[0], etree._Element):
        raise PageWriteError(f"Cannot resolve source element for line {line.id!r}")
    return matches[0]


def _ensure_baseline(line_element: etree._Element, namespace: str) -> etree._Element:
    def q(name: str) -> str:
        return f"{{{namespace}}}{name}"

    baseline = line_element.find(q("Baseline"))
    if baseline is not None:
        return baseline
    baseline = etree.Element(q("Baseline"))
    coords = line_element.find(q("Coords"))
    insert_at = line_element.index(coords) + 1 if coords is not None else 0
    line_element.insert(insert_at, baseline)
    return baseline


def _ensure_unicode(line_element: etree._Element, namespace: str) -> etree._Element:
    def q(name: str) -> str:
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
        return f"{{{namespace}}}{name}"

    for line in document.lines:
        if not line.is_dirty:
            continue
        element = _find_line(candidate, line)
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
            _ensure_unicode(element, namespace).text = line.text
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
    options: dict[str, object] = {
        "encoding": document.xml_encoding,
        "xml_declaration": True,
        "pretty_print": False,
    }
    if document.xml_standalone is not None:
        options["standalone"] = document.xml_standalone
    return etree.tostring(tree, **options)


def build_candidate(document: PageDocument) -> tuple[bytes, etree._ElementTree]:
    tree = apply_document(document)
    return serialize_tree(tree, document), tree

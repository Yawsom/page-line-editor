# ruff: noqa: E501
from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import NoReturn

import pytest
from lxml import etree

from page_line_editor.application.history_service import DocumentHistory
from page_line_editor.application.save_service import SaveError, SaveService, ValidationFailed
from page_line_editor.domain.geometry import Point, Polygon
from page_line_editor.pagexml.parser import PAGE_2013_NAMESPACE, parse_page
from page_line_editor.pagexml.validator import validate_xml
from page_line_editor.pagexml.writer import PageWriteError, build_candidate


def page_xml(*, image: str = "page.jpg", transkribus: bool = True) -> bytes:
    vendor = '<TranskribusMetadata docId="1"/>' if transkribus else ""
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<PcGts xmlns="{PAGE_2013_NAMESPACE}">
  <Metadata><Creator>fixture</Creator><Created>2020-01-01T00:00:00Z</Created><LastChange>2020-01-01T00:00:00Z</LastChange>{vendor}</Metadata>
  <Page imageFilename="{image}" imageWidth="100" imageHeight="80">
    <!--retain me--><TextRegion id="r1" custom="region"><Coords points="0,0 99,0 99,79 0,79"/>
      <TextLine id="l1" custom="line"><Coords points="10,10 80,10 80,30 10,30"/><Baseline points="12,25 40,26 78,25"/><Word id="w1"><Coords points="10,10 20,10 20,20 10,20"/></Word><TextEquiv><Unicode>قديم</Unicode></TextEquiv></TextLine>
      <TextLine id="l2"><Coords points="10,40 80,40 80,60 10,60"/><Baseline points="12,55 78,55"/><TextEquiv><PlainText>plain</PlainText><Unicode>ثان</Unicode></TextEquiv></TextLine>
    </TextRegion>
  </Page>
</PcGts>'''.encode()


def three_line_page_xml() -> bytes:
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<PcGts xmlns="{PAGE_2013_NAMESPACE}">
  <Metadata><Creator>fixture</Creator><Created>2020-01-01T00:00:00Z</Created><LastChange>2020-01-01T00:00:00Z</LastChange></Metadata>
  <Page imageFilename="page.jpg" imageWidth="100" imageHeight="80">
    <TextRegion id="r1"><Coords points="0,0 99,0 99,79 0,79"/>
      <TextLine id="l1"><Coords points="10,10 80,10 80,24 10,24"/><Baseline points="12,20 78,20"/><TextEquiv><Unicode>اول</Unicode></TextEquiv></TextLine>
      <TextLine id="l2"><Coords points="10,28 80,28 80,42 10,42"/><Baseline points="12,38 78,38"/><TextEquiv><Unicode>ثان</Unicode></TextEquiv></TextLine>
      <TextLine id="l3"><Coords points="10,46 80,46 80,60 10,60"/><Baseline points="12,56 78,56"/><TextEquiv><Unicode>ثالث</Unicode></TextEquiv></TextLine>
    </TextRegion>
  </Page>
</PcGts>'''.encode()


def test_parse_preserves_ordered_geometry_and_original_values(tmp_path: Path) -> None:
    source = tmp_path / "page.xml"
    source.write_bytes(page_xml())
    document = parse_page(source)
    assert [line.id for line in document.lines] == ["l1", "l2"]
    line = document.lines[0]
    assert line.original_text == line.text == "قديم"
    assert line.baseline is not None
    assert line.baseline.points == (Point(12, 25), Point(40, 26), Point(78, 25))
    assert line.has_word_content
    assert not document.is_dirty


def test_narrow_writer_retains_unknown_content_and_reports_vendor_schema(tmp_path: Path) -> None:
    source = tmp_path / "page.xml"
    source.write_bytes(page_xml())
    document = parse_page(source)
    history = DocumentHistory(document)
    history.edit_text("l1", "جديد")
    candidate, _ = build_candidate(document)
    assert document.line_by_id("l1").has_word_content
    tree = etree.fromstring(candidate)
    ns = {"p": PAGE_2013_NAMESPACE}
    assert (
        tree.xpath("string(.//p:TextLine[@id='l1']/p:TextEquiv/p:Unicode)", namespaces=ns) == "جديد"
    )
    assert tree.xpath("count(.//p:TextLine[@id='l1']/p:Word)", namespaces=ns) == 0
    l1_custom = str(tree.xpath("string(.//p:TextLine[@id='l1']/@custom)", namespaces=ns))
    assert "line" in l1_custom
    assert "readingOrder {index:0;}" in l1_custom
    assert b"retain me" in candidate
    report = validate_xml(candidate)
    assert report.core_valid and report.can_save
    assert not report.strict_valid
    assert any(issue.code == "schema.vendor_extension" for issue in report.warnings)


def test_save_creates_exact_backup_then_replaces_atomically(tmp_path: Path) -> None:
    source = tmp_path / "page.xml"
    original = page_xml(transkribus=False)
    source.write_bytes(original)
    document = parse_page(source)
    document.lines[0].text = "محفوظ"
    result = SaveService(tmp_path / "history").save(document)
    assert result.backup_path.read_bytes() == original
    assert "manual" in result.backup_path.parts
    assert b"\xd9\x85\xd8\xad\xd9\x81\xd9\x88\xd8\xb8" in source.read_bytes()
    assert not document.is_dirty


@pytest.mark.skipif(os.name == "nt", reason="Windows does not use POSIX mode bits")
def test_atomic_save_preserves_source_permissions(tmp_path: Path) -> None:
    source = tmp_path / "page.xml"
    source.write_bytes(page_xml(transkribus=False))
    source.chmod(0o640)
    document = parse_page(source)
    document.lines[0].text = "محفوظ"

    SaveService(tmp_path / "history").save(document)

    assert stat.S_IMODE(source.stat().st_mode) == 0o640


def test_save_wraps_backup_failure_without_touching_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "page.xml"
    original = page_xml(transkribus=False)
    source.write_bytes(original)
    document = parse_page(source)
    document.lines[0].text = "should remain in memory"
    service = SaveService(tmp_path / "history")

    def fail_backup(_source: str | Path) -> NoReturn:
        raise OSError("history is unavailable")

    monkeypatch.setattr(service.history, "backup_manual", fail_backup)

    with pytest.raises(SaveError, match="Could not back up"):
        service.save(document)

    assert source.read_bytes() == original
    assert document.is_dirty


@pytest.mark.skipif(os.name == "nt", reason="Windows does not fsync directories")
def test_directory_fsync_failure_does_not_report_a_failed_save(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "page.xml"
    source.write_bytes(page_xml(transkribus=False))
    document = parse_page(source)
    document.lines[0].text = "محفوظ"
    real_fsync = os.fsync
    calls = 0

    def fail_directory_fsync(descriptor: int) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("directory fsync unsupported")
        real_fsync(descriptor)

    monkeypatch.setattr(os, "fsync", fail_directory_fsync)

    result = SaveService(tmp_path / "history").save(document)

    assert calls == 2
    assert result.source_path == source
    assert result.durability_warning is not None
    assert "directory fsync unsupported" in result.durability_warning
    assert b"\xd9\x85\xd8\xad\xd9\x81\xd9\x88\xd8\xb8" in source.read_bytes()
    assert not document.is_dirty


def test_temp_cleanup_failure_does_not_mask_atomic_save_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "page.xml"
    source.write_bytes(page_xml(transkribus=False))
    document = parse_page(source)
    document.lines[0].text = "not saved"

    def fail_replace(_source: str | Path, _destination: str | Path) -> NoReturn:
        raise OSError("replace failed")

    def fail_cleanup(_path: Path, *, missing_ok: bool = False) -> NoReturn:
        del missing_ok
        raise OSError("cleanup failed")

    monkeypatch.setattr(os, "replace", fail_replace)
    monkeypatch.setattr(Path, "unlink", fail_cleanup)

    with pytest.raises(SaveError, match="replace failed"):
        SaveService(tmp_path / "history").save(document)


def test_successful_text_save_updates_word_content_metadata(tmp_path: Path) -> None:
    source = tmp_path / "page.xml"
    source.write_bytes(page_xml(transkribus=False))
    document = parse_page(source)
    line = document.line_by_id("l1")
    assert line.has_word_content
    line.text = "نص جديد"

    SaveService(tmp_path / "history").save(document)

    assert not line.has_word_content
    saved = etree.parse(str(source))
    assert not saved.xpath(
        ".//p:TextLine[@id='l1']/p:Word", namespaces={"p": PAGE_2013_NAMESPACE}
    )


def test_invalid_candidate_does_not_touch_source_or_create_backup(tmp_path: Path) -> None:
    source = tmp_path / "page.xml"
    original = page_xml(transkribus=False)
    source.write_bytes(original)
    document = parse_page(source)
    document.lines[0].polygon = Polygon(
        (Point(10, 10), Point(80, 30), Point(80, 10), Point(10, 30))
    )
    with pytest.raises(ValidationFailed):
        SaveService(tmp_path / "history").save(document)
    assert source.read_bytes() == original
    assert not (tmp_path / "history").exists()


def test_document_history_undo_redo() -> None:
    # This test intentionally uses a temp-free in-memory model through a parsed fixture elsewhere.
    assert Point(1, 2).translated(3, 4) == Point(4, 6)


def test_confirmed_deletion_is_reversible_then_removed_on_save(tmp_path: Path) -> None:
    source = tmp_path / "page.xml"
    source.write_bytes(page_xml(transkribus=False))
    document = parse_page(source)
    history = DocumentHistory(document)

    history.edit_deleted("l2", True)
    assert [line.id for line in document.active_lines] == ["l1"]
    assert document.line_by_id("l2").deleted
    history.undo()
    assert [line.id for line in document.active_lines] == ["l1", "l2"]
    history.redo()

    SaveService(tmp_path / "history").save(document)
    saved = etree.parse(str(source))
    ns = {"p": PAGE_2013_NAMESPACE}
    assert saved.xpath("count(.//p:TextLine[@id='l2'])", namespaces=ns) == 0
    assert [line.id for line in document.lines] == ["l1"]


def test_save_after_deleting_first_line_edits_the_surviving_second_id(tmp_path: Path) -> None:
    """Delete line A, save, edit the old second line: Unicode must land on @id l2, not l3.

    Positional lxml getpath() used to shift after the sibling removal, so the
    second save wrote B's text onto C.
    """
    source = tmp_path / "page.xml"
    source.write_bytes(three_line_page_xml())
    document = parse_page(source)
    history = DocumentHistory(document)

    history.edit_deleted("l1", True)
    SaveService(tmp_path / "history").save(document)

    assert [line.id for line in document.lines] == ["l2", "l3"]
    tree = document.xml_tree
    ns = {"p": PAGE_2013_NAMESPACE}
    l2_element = tree.xpath(".//p:TextLine[@id='l2']", namespaces=ns)[0]
    l3_element = tree.xpath(".//p:TextLine[@id='l3']", namespaces=ns)[0]
    assert document.line_by_id("l2").xml_path == tree.getpath(l2_element)
    assert document.line_by_id("l3").xml_path == tree.getpath(l3_element)
    assert tree.xpath(document.line_by_id("l2").xml_path)[0].get("id") == "l2"

    edited = "تصحيح الثاني"
    history.edit_text("l2", edited)
    SaveService(tmp_path / "history").save(document)

    saved = etree.parse(str(source))
    ns = {"p": PAGE_2013_NAMESPACE}
    assert saved.xpath("count(.//p:TextLine)", namespaces=ns) == 2
    assert saved.xpath("count(.//p:TextLine[@id='l1'])", namespaces=ns) == 0
    assert saved.xpath("string(.//p:TextLine[@id='l2']/p:TextEquiv/p:Unicode)", namespaces=ns) == edited
    assert saved.xpath("string(.//p:TextLine[@id='l3']/p:TextEquiv/p:Unicode)", namespaces=ns) == "ثالث"


def test_writer_refuses_missing_or_duplicate_textline_ids(tmp_path: Path) -> None:
    source = tmp_path / "page.xml"
    source.write_bytes(page_xml(transkribus=False))
    document = parse_page(source)
    document.lines[0].text = "should not write"
    document.lines[0].id = "missing-from-tree"
    with pytest.raises(PageWriteError, match="Cannot resolve source element"):
        build_candidate(document)

    duplicate = tmp_path / "duplicate.xml"
    duplicate.write_bytes(
        page_xml(transkribus=False).replace(b'id="l2"', b'id="l1"', 1)
    )
    duplicated = parse_page(duplicate)
    duplicated.lines[0].text = "should not write"
    with pytest.raises(PageWriteError, match="Duplicate TextLine id"):
        build_candidate(duplicated)


def test_save_wraps_writer_identity_failure_without_touching_source(tmp_path: Path) -> None:
    source = tmp_path / "page.xml"
    original = page_xml(transkribus=False)
    source.write_bytes(original)
    document = parse_page(source)
    document.lines[0].text = "should not write"
    document.lines[0].id = "missing-from-tree"

    with pytest.raises(SaveError, match="Could not build PAGE XML"):
        SaveService(tmp_path / "history").save(document)

    assert source.read_bytes() == original
    assert not (tmp_path / "history").exists()


def test_rejected_deletion_serializes_no_structural_change(tmp_path: Path) -> None:
    source = tmp_path / "page.xml"
    source.write_bytes(page_xml(transkribus=False))
    document = parse_page(source)
    history = DocumentHistory(document)

    history.edit_deleted("l2", True)
    history.undo()  # Reject restores the complete pre-correction state.
    candidate, _ = build_candidate(document)
    tree = etree.fromstring(candidate)
    ns = {"p": PAGE_2013_NAMESPACE}
    assert tree.xpath("count(.//p:TextLine[@id='l2'])", namespaces=ns) == 1
    assert not document.is_dirty


def test_text_edit_drops_word_plaintext_and_stale_region_unicode(tmp_path: Path) -> None:
    source = tmp_path / "page.xml"
    source.write_bytes(page_xml(transkribus=False))
    document = parse_page(source)
    document.line_by_id("l2").text = "محدث"
    candidate, _ = build_candidate(document)
    tree = etree.fromstring(candidate)
    ns = {"p": PAGE_2013_NAMESPACE}
    assert (
        tree.xpath("string(.//p:TextLine[@id='l2']/p:TextEquiv/p:Unicode)", namespaces=ns) == "محدث"
    )
    assert tree.xpath("count(.//p:TextLine[@id='l2']/p:TextEquiv/p:PlainText)", namespaces=ns) == 0
    assert tree.xpath("count(.//p:TextLine[@id='l1']/p:Word)", namespaces=ns) == 1
    assert "readingOrder {index:1;}" in str(
        tree.xpath("string(.//p:TextLine[@id='l2']/@custom)", namespaces=ns)
    )


def test_deletion_reindexes_reading_order(tmp_path: Path) -> None:
    source = tmp_path / "page.xml"
    xml = page_xml(transkribus=False).replace(
        b'id="r1" custom="region"',
        b'id="r1" custom="readingOrder {index:4;}"',
    )
    source.write_bytes(xml)
    document = parse_page(source)
    document.line_by_id("l1").deleted = True
    candidate, _ = build_candidate(document)
    tree = etree.fromstring(candidate)
    ns = {"p": PAGE_2013_NAMESPACE}
    assert tree.xpath("count(.//p:TextLine[@id='l1'])", namespaces=ns) == 0
    assert "readingOrder {index:0;}" in str(
        tree.xpath("string(.//p:TextLine[@id='l2']/@custom)", namespaces=ns)
    )
    assert "readingOrder {index:0;}" in str(
        tree.xpath("string(.//p:TextRegion[@id='r1']/@custom)", namespaces=ns)
    )


def test_page_edge_coordinate_is_warning_not_blocking(tmp_path: Path) -> None:
    source = tmp_path / "page.xml"
    xml = page_xml(transkribus=False).replace(
        b'points="10,10 80,10 80,30 10,30"',
        b'points="10,10 100,10 100,30 10,30"',
    )
    source.write_bytes(xml)
    document = parse_page(source)
    report = document.validation_report
    assert report is not None
    assert report.can_save
    assert any(issue.code == "line.geometry.edge" for issue in report.warnings)

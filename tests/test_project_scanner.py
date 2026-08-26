from __future__ import annotations

from pathlib import Path

from test_pagexml_core import page_xml

from page_line_editor.application.project_scanner import PairingMethod, scan_project


def test_scanner_pairs_exact_then_page_image_filename(tmp_path: Path) -> None:
    images, xml = tmp_path / "images", tmp_path / "xml"
    images.mkdir()
    xml.mkdir()
    (images / "a.jpg").write_bytes(b"image")
    (images / "legacy.png").write_bytes(b"image")
    (xml / "a.xml").write_bytes(page_xml(image="a.jpg", transkribus=False))
    (xml / "transkribus-legacy.xml").write_bytes(page_xml(image="legacy.png", transkribus=False))
    result = scan_project(images, xml)
    assert [pair.method for pair in result.pairs] == [
        PairingMethod.EXACT_STEM,
        PairingMethod.IMAGE_FILENAME,
    ]
    assert not result.unmatched


def test_scanner_isolates_malformed_and_unmatched_files(tmp_path: Path) -> None:
    images, xml = tmp_path / "images", tmp_path / "xml"
    images.mkdir()
    xml.mkdir()
    (images / "bad.jpg").write_bytes(b"image")
    (images / "orphan.png").write_bytes(b"image")
    (xml / "bad.xml").write_text("<not-xml")
    result = scan_project(images, xml)
    assert len(result.pairs) == 1
    assert any(item.code == "xml.malformed" for item in result.pairs[0].diagnostics)
    assert any(
        item.code == "unmatched.image" and item.path.name == "orphan.png"
        for item in result.diagnostics
    )

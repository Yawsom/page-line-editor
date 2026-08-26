# ruff: noqa: E402, I001
from __future__ import annotations

import base64
from dataclasses import dataclass
from pathlib import Path

import pytest
from docx import Document
from lxml import etree

pytest.importorskip("PySide6")

from page_line_editor.pagexml.parser import PAGE_2013_NAMESPACE
from page_line_editor.ui.controller import EditorController
from page_line_editor.ui.main_window import MainWindow
from page_line_editor.ui.panels import ProjectPaths


# A real, synthetic 1x1 PNG. PAGE dimensions deliberately remain document
# coordinates; the controller should not need manuscript fixtures to open it.
PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def _page_xml(text: str = "قديم") -> bytes:
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<PcGts xmlns="{PAGE_2013_NAMESPACE}">
  <Metadata>
    <Creator>controller test</Creator>
    <Created>2020-01-01T00:00:00Z</Created>
    <LastChange>2020-01-01T00:00:00Z</LastChange>
  </Metadata>
  <Page imageFilename="1r.png" imageWidth="100" imageHeight="80">
    <TextRegion id="region-1">
      <Coords points="0,0 99,0 99,79 0,79"/>
      <TextLine id="line-1">
        <Coords points="10,10 90,10 90,35 10,35"/>
        <Baseline points="12,30 88,30"/>
        <TextEquiv><Unicode>{text}</Unicode></TextEquiv>
      </TextLine>
    </TextRegion>
  </Page>
</PcGts>'''.encode()


@dataclass(frozen=True)
class SyntheticProject:
    paths: ProjectPaths
    xml_path: Path
    original_xml: bytes


def _project(tmp_path: Path) -> SyntheticProject:
    images = tmp_path / "images"
    xml = tmp_path / "xml"
    history = tmp_path / "history"
    images.mkdir()
    xml.mkdir()
    (images / "1r.png").write_bytes(PNG_BYTES)
    original = _page_xml()
    xml_path = xml / "1r.xml"
    xml_path.write_bytes(original)

    ground_truth = tmp_path / "ground-truth.docx"
    document = Document()
    document.add_paragraph("[1r]")
    document.add_paragraph("جديد")
    document.save(ground_truth)
    return SyntheticProject(
        ProjectPaths(images, xml, ground_truth, history, normalize_nfc=True),
        xml_path,
        original,
    )


def _open_controller(qtbot, project: SyntheticProject) -> EditorController:  # type: ignore[no-untyped-def]
    window = MainWindow()
    qtbot.addWidget(window)
    controller = EditorController(window)
    controller.open_project(project.paths)
    assert controller.session.document is not None
    assert controller.ground_truth is not None
    return controller


def _complete_current_page_correction(controller: EditorController) -> None:
    """Run the worker's pure step and its GUI-thread completion deterministically."""
    document = controller.session.document
    assert document is not None
    assert controller.ground_truth is not None
    proposal = controller.workflow.propose(document, controller.ground_truth)
    controller._apply_page_proposal(proposal)


def _saved_unicode(path: Path) -> str:
    tree = etree.parse(str(path))
    return str(
        tree.xpath(
            "string(.//p:TextLine[@id='line-1']/p:TextEquiv/p:Unicode)",
            namespaces={"p": PAGE_2013_NAMESPACE},
        )
    )


def test_controller_opens_folders_auto_applies_in_memory_and_rejects(qtbot, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    project = _project(tmp_path)
    controller = _open_controller(qtbot, project)

    document = controller.session.document
    assert document is not None
    assert document.line_by_id("line-1").text == "قديم"
    _complete_current_page_correction(controller)

    line = document.line_by_id("line-1")
    assert line.text == "جديد"
    assert line.proposal_state == "applied"
    assert line.diff_text == "قديم → جديد"
    assert document.is_dirty
    assert project.xml_path.read_bytes() == project.original_xml
    # Auto correction immediately keeps its own audit copy/report, while the
    # live PAGE source remains untouched until explicit Save.
    assert (
        next(project.paths.audit_directory.glob("auto/*/originals/1r.xml")).read_bytes()
        == project.original_xml
    )

    controller.reject_line("line-1")
    assert line.text == "قديم"
    assert line.proposal_state == ""
    assert not document.is_dirty
    assert project.xml_path.read_bytes() == project.original_xml
    assert not list(project.paths.audit_directory.glob("manual/*/originals/1r.xml"))


def test_controller_explicit_save_writes_correction_and_exact_manual_backup(
    qtbot, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    project = _project(tmp_path)
    controller = _open_controller(qtbot, project)
    _complete_current_page_correction(controller)

    assert project.xml_path.read_bytes() == project.original_xml
    assert not list(project.paths.audit_directory.glob("manual/*/originals/1r.xml"))
    controller.save()

    assert _saved_unicode(project.xml_path) == "جديد"
    backups = list(project.paths.audit_directory.glob("manual/*/originals/1r.xml"))
    assert len(backups) == 1
    assert backups[0].read_bytes() == project.original_xml
    assert controller.session.document is not None
    assert not controller.session.document.is_dirty
    assert controller.window.undo_stack.isClean()

"""Deterministic folder pairing for images and PAGE XML documents."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from page_line_editor.pagexml.parser import PageXmlError, parse_page

IMAGE_SUFFIXES = frozenset({".jpg", ".jpeg", ".png"})


class PairingMethod(StrEnum):
    EXACT_STEM = "exact_stem"
    CASE_INSENSITIVE_STEM = "case_insensitive_stem"
    IMAGE_FILENAME = "image_filename"


@dataclass(frozen=True, slots=True)
class ScanDiagnostic:
    code: str
    message: str
    path: Path | None = None


@dataclass(slots=True)
class PagePair:
    image_path: Path
    xml_path: Path
    method: PairingMethod
    diagnostics: list[ScanDiagnostic] = field(default_factory=list)


@dataclass(slots=True)
class ProjectScanResult:
    image_directory: Path
    xml_directory: Path
    pairs: list[PagePair] = field(default_factory=list)
    diagnostics: list[ScanDiagnostic] = field(default_factory=list)

    @property
    def unmatched(self) -> list[ScanDiagnostic]:
        """Return page pairs that could not be matched to both inputs."""
        return [item for item in self.diagnostics if item.code.startswith("unmatched.")]


def _files(directory: Path, suffixes: frozenset[str]) -> list[Path]:
    """Return files."""
    if not directory.is_dir():
        raise NotADirectoryError(directory)
    return sorted(
        (
            path
            for path in directory.iterdir()
            if path.is_file() and path.suffix.lower() in suffixes
        ),
        key=lambda path: (path.name.casefold(), path.name),
    )


def _index(paths: list[Path], key: Callable[[Path], str]) -> dict[str, list[Path]]:
    """Return index."""
    result: dict[str, list[Path]] = {}
    for path in paths:
        result.setdefault(key(path), []).append(path)
    return result


def scan_project(image_directory: str | Path, xml_directory: str | Path) -> ProjectScanResult:
    """Pair unique files without guessing between duplicate candidates."""
    image_dir, xml_dir = Path(image_directory), Path(xml_directory)
    images = _files(image_dir, IMAGE_SUFFIXES)
    xml_files = _files(xml_dir, frozenset({".xml"}))
    result = ProjectScanResult(image_dir, xml_dir)
    exact_images = _index(images, lambda path: path.stem)
    folded_images = _index(images, lambda path: path.stem.casefold())
    filename_images = _index(images, lambda path: path.name.casefold())
    used_images: set[Path] = set()

    for xml_path in xml_files:
        candidates = exact_images.get(xml_path.stem, [])
        method = PairingMethod.EXACT_STEM
        page_image_filename: str | None = None
        parse_error: str | None = None
        if len(candidates) != 1:
            candidates = folded_images.get(xml_path.stem.casefold(), [])
            method = PairingMethod.CASE_INSENSITIVE_STEM
        if len(candidates) != 1:
            try:
                page_image_filename = parse_page(xml_path).image_filename
            except PageXmlError as exc:
                parse_error = str(exc)
            candidates = (
                filename_images.get(Path(page_image_filename).name.casefold(), [])
                if page_image_filename
                else []
            )
            method = PairingMethod.IMAGE_FILENAME
        if len(candidates) > 1:
            result.diagnostics.append(
                ScanDiagnostic(
                    "ambiguous.image", f"Multiple images match {xml_path.name}", xml_path
                )
            )
            continue
        if not candidates:
            message = f"No image matches {xml_path.name}"
            if parse_error:
                message += f"; PAGE metadata could not be read: {parse_error}"
            result.diagnostics.append(ScanDiagnostic("unmatched.xml", message, xml_path))
            continue
        image_path = candidates[0]
        if image_path in used_images:
            result.diagnostics.append(
                ScanDiagnostic(
                    "ambiguous.reused_image",
                    f"Image {image_path.name} matches more than one XML",
                    xml_path,
                )
            )
            continue
        pair_diagnostics: list[ScanDiagnostic] = []
        if method != PairingMethod.EXACT_STEM:
            pair_diagnostics.append(
                ScanDiagnostic("pair.compatibility", f"Paired using {method.value}", xml_path)
            )
        # Exact pairing should still report malformed PAGE rather than making the
        # entire project fail to open.
        try:
            parsed = parse_page(xml_path)
            if parsed.validation_report is not None and not parsed.validation_report.can_save:
                pair_diagnostics.append(
                    ScanDiagnostic(
                        "xml.invalid",
                        "PAGE XML has blocking schema or semantic validation errors",
                        xml_path,
                    )
                )
        except PageXmlError as exc:
            pair_diagnostics.append(ScanDiagnostic("xml.malformed", str(exc), xml_path))
        result.pairs.append(PagePair(image_path, xml_path, method, pair_diagnostics))
        used_images.add(image_path)

    for image in images:
        if image not in used_images:
            result.diagnostics.append(
                ScanDiagnostic("unmatched.image", f"No XML matches {image.name}", image)
            )
    return result


class ProjectScanner:
    """Injectable facade used by the desktop session."""

    def scan(self, image_directory: str | Path, xml_directory: str | Path) -> ProjectScanResult:
        """Pair project images with PAGE XML and report pairing diagnostics."""
        return scan_project(image_directory, xml_directory)

"""Open-project dialog for separate image, PAGE XML, and audit folders."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


@dataclass(frozen=True, slots=True)
class ProjectPaths:
    image_directory: Path
    xml_directory: Path
    ground_truth_path: Path | None
    audit_directory: Path
    normalize_nfc: bool = True


class _PathRow(QWidget):
    def __init__(self, label: str, mode: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.mode = mode
        self.edit = QLineEdit(self)
        self.edit.setAccessibleName(label)
        self.button = QPushButton("Browse…", self)
        self.button.setAccessibleName(f"Browse for {label}")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.edit, 1)
        layout.addWidget(self.button)
        self.button.clicked.connect(self.browse)

    def browse(self) -> None:
        start = self.edit.text() or str(Path.home())
        if self.mode == "file":
            value, _ = QFileDialog.getOpenFileName(
                self,
                "Select ground-truth document",
                start,
                "Word documents (*.docx);;All files (*)",
            )
        else:
            value = QFileDialog.getExistingDirectory(self, "Select folder", start)
        if value:
            self.edit.setText(value)


class ProjectOpenDialog(QDialog):
    """Collect all paths needed to scan and later auto-correct a project."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Open PAGE project")
        self.setMinimumWidth(680)
        self.image_row = _PathRow("Image folder", "directory", self)
        self.image_row.setObjectName("imageDirectoryRow")
        self.xml_row = _PathRow("PAGE XML folder", "directory", self)
        self.xml_row.setObjectName("xmlDirectoryRow")
        self.ground_truth_row = _PathRow("Ground truth (.docx, optional)", "file", self)
        self.ground_truth_row.setObjectName("groundTruthRow")
        self.audit_row = _PathRow("Correction history folder", "directory", self)
        self.audit_row.setObjectName("auditDirectoryRow")
        self.normalize_checkbox = QCheckBox("Normalize edited transcription to Unicode NFC on save")
        self.normalize_checkbox.setChecked(True)
        self.error_label = QLabel(self)
        self.error_label.setStyleSheet("color: #c62828;")
        self.error_label.hide()

        form = QFormLayout()
        form.addRow("Images", self.image_row)
        form.addRow("PAGE XML", self.xml_row)
        form.addRow("Ground truth", self.ground_truth_row)
        form.addRow("History", self.audit_row)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Open | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.normalize_checkbox)
        layout.addWidget(self.error_label)
        layout.addWidget(buttons)
        self.image_row.edit.textChanged.connect(self._suggest_history)
        self.xml_row.edit.textChanged.connect(self._suggest_history)
        self._restore_settings()

    def paths(self) -> ProjectPaths:
        ground_truth = self.ground_truth_row.edit.text().strip()
        audit = self.audit_row.edit.text().strip()
        return ProjectPaths(
            image_directory=Path(self.image_row.edit.text().strip()).expanduser(),
            xml_directory=Path(self.xml_row.edit.text().strip()).expanduser(),
            ground_truth_path=Path(ground_truth).expanduser() if ground_truth else None,
            audit_directory=Path(audit).expanduser(),
            normalize_nfc=self.normalize_checkbox.isChecked(),
        )

    def accept(self) -> None:
        paths = self.paths()
        errors = []
        if not self.image_row.edit.text().strip() or not paths.image_directory.is_dir():
            errors.append("Choose an existing image folder.")
        if not self.xml_row.edit.text().strip() or not paths.xml_directory.is_dir():
            errors.append("Choose an existing PAGE XML folder.")
        if paths.ground_truth_path is not None and not paths.ground_truth_path.is_file():
            errors.append("The optional ground-truth document does not exist.")
        if not self.audit_row.edit.text().strip():
            errors.append("Choose a correction history folder.")
        if errors:
            self.error_label.setText(" ".join(errors))
            self.error_label.show()
            return
        settings = QSettings()
        settings.setValue("project/images", str(paths.image_directory))
        settings.setValue("project/xml", str(paths.xml_directory))
        settings.setValue("project/ground_truth", str(paths.ground_truth_path or ""))
        settings.setValue("project/audit", str(paths.audit_directory))
        settings.setValue("editor/normalize_nfc", paths.normalize_nfc)
        super().accept()

    def _suggest_history(self) -> None:
        if self.audit_row.edit.isModified() or self.audit_row.edit.text():
            return
        xml_text = self.xml_row.edit.text().strip()
        if xml_text:
            self.audit_row.edit.setText(str(Path(xml_text).parent / "correction_history"))

    def _restore_settings(self) -> None:
        settings = QSettings()
        self.image_row.edit.setText(str(settings.value("project/images", "")))
        self.xml_row.edit.setText(str(settings.value("project/xml", "")))
        self.ground_truth_row.edit.setText(str(settings.value("project/ground_truth", "")))
        self.audit_row.edit.setText(str(settings.value("project/audit", "")))
        normalize = settings.value("editor/normalize_nfc", True)
        self.normalize_checkbox.setChecked(str(normalize).lower() not in {"false", "0"})

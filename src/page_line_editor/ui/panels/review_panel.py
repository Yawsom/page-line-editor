"""Right-hand correction review and validation panel."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QGroupBox,
    QLabel,
    QListWidget,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class ReviewPanel(QWidget):
    autoCorrectPageRequested = Signal()
    autoCorrectBatchRequested = Signal()
    cancelRequested = Signal()
    keepPageRequested = Signal()
    rejectPageRequested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.project_label = QLabel("No project open", self)
        self.project_label.setWordWrap(True)
        self.validation_label = QLabel("No PAGE document loaded", self)
        self.validation_label.setWordWrap(True)
        self.validation_messages = QListWidget(self)
        self.validation_messages.setAccessibleName("PAGE validation messages")

        self.filter_combo = QComboBox(self)
        self.filter_combo.addItems(("All lines", "Automatically changed", "Rejected", "Warnings"))
        self.filter_combo.setAccessibleName("Correction review filter")
        self.progress = QProgressBar(self)
        self.progress.setRange(0, 100)
        self.progress.hide()
        self.cancel_button = QPushButton("Cancel correction", self)
        self.cancel_button.hide()
        self.correct_page_button = QPushButton("Auto-correct current page", self)
        self.correct_batch_button = QPushButton("Auto-correct folder", self)
        self.keep_page_button = QPushButton("Keep all on page", self)
        self.reject_page_button = QPushButton("Reject / revert all on page", self)

        correction_group = QGroupBox("Automatic correction", self)
        correction_layout = QVBoxLayout(correction_group)
        correction_layout.addWidget(self.filter_combo)
        correction_layout.addWidget(self.correct_page_button)
        correction_layout.addWidget(self.correct_batch_button)
        correction_layout.addWidget(self.progress)
        correction_layout.addWidget(self.cancel_button)
        correction_layout.addWidget(self.keep_page_button)
        correction_layout.addWidget(self.reject_page_button)

        layout = QVBoxLayout(self)
        layout.addWidget(self.project_label)
        layout.addWidget(correction_group)
        layout.addWidget(self.validation_label)
        layout.addWidget(self.validation_messages, 1)

        self.correct_page_button.clicked.connect(self.autoCorrectPageRequested)
        self.correct_batch_button.clicked.connect(self.autoCorrectBatchRequested)
        self.cancel_button.clicked.connect(self.cancelRequested)
        self.keep_page_button.clicked.connect(self.keepPageRequested)
        self.reject_page_button.clicked.connect(self.rejectPageRequested)

    def set_project_summary(self, text: str) -> None:
        self.project_label.setText(text)

    def set_validation(self, summary: str, messages: list[str] | tuple[str, ...] = ()) -> None:
        self.validation_label.setText(summary)
        self.validation_messages.clear()
        self.validation_messages.addItems(messages)

    def set_correction_progress(self, value: int | None, status: str = "") -> None:
        running = value is not None
        self.progress.setVisible(running)
        self.cancel_button.setVisible(running)
        self.correct_page_button.setEnabled(not running)
        self.correct_batch_button.setEnabled(not running)
        if value is not None:
            self.progress.setValue(value)
            self.progress.setFormat(status or "%p%")

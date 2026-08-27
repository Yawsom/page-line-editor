"""Right-hand correction review and validation panel."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)


class ReviewPanel(QWidget):
    autoCorrectPageRequested = Signal()
    autoCorrectBatchRequested = Signal()
    cancelRequested = Signal()
    keepPageRequested = Signal()
    rejectPageRequested = Signal()
    keepLineRequested = Signal(str)
    rejectLineRequested = Signal(str)

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
        self._corrections: list[dict[str, object]] = []
        self.review_content = QWidget(self)
        self.review_layout = QVBoxLayout(self.review_content)
        self.review_layout.setContentsMargins(0, 0, 0, 0)
        self.review_layout.setSpacing(7)
        self.review_layout.addStretch(1)
        self.review_scroll = QScrollArea(self)
        self.review_scroll.setObjectName("correctionReviewList")
        self.review_scroll.setWidgetResizable(True)
        self.review_scroll.setWidget(self.review_content)
        self.review_scroll.setMinimumHeight(220)

        correction_group = QGroupBox("Automatic correction", self)
        correction_layout = QVBoxLayout(correction_group)
        correction_layout.addWidget(self.filter_combo)
        correction_layout.addWidget(self.correct_page_button)
        correction_layout.addWidget(self.correct_batch_button)
        correction_layout.addWidget(self.progress)
        correction_layout.addWidget(self.cancel_button)
        correction_layout.addWidget(self.review_scroll, 1)
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
        self.filter_combo.currentTextChanged.connect(self._rebuild_corrections)

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

    def set_corrections(self, entries: Iterable[Mapping[str, object]]) -> None:
        self._corrections = [dict(entry) for entry in entries]
        self._rebuild_corrections()

    def clear_corrections(self) -> None:
        self.set_corrections(())

    def _rebuild_corrections(self, *_args: object) -> None:
        while self.review_layout.count() > 1:
            item = self.review_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        filter_name = self.filter_combo.currentText()
        visible = [entry for entry in self._corrections if self._included(entry, filter_name)]
        if not visible:
            empty = QLabel("No correction records for this filter", self.review_content)
            empty.setWordWrap(True)
            empty.setStyleSheet("color: palette(mid); padding: 8px;")
            self.review_layout.insertWidget(0, empty)
            return
        for index, entry in enumerate(visible):
            self.review_layout.insertWidget(index, self._correction_card(entry))

    @staticmethod
    def _included(entry: Mapping[str, object], filter_name: str) -> bool:
        if filter_name == "Automatically changed":
            return bool(entry.get("actionable"))
        if filter_name == "Rejected":
            return entry.get("decision") == "rejected"
        if filter_name == "Warnings":
            return str(entry.get("status", "")) in {"MISSING", "SPLIT", "MERGE"}
        return True

    def _correction_card(self, entry: Mapping[str, object]) -> QFrame:
        card = QFrame(self.review_content)
        card.setFrameShape(QFrame.Shape.StyledPanel)
        card.setObjectName("correctionReviewCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(8, 7, 8, 7)
        layout.setSpacing(3)

        status = str(entry.get("status", ""))
        badge = QLabel(status, card)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setStyleSheet(
            "font-weight: 700; padding: 2px 7px; border: 1px solid palette(mid); "
            "border-radius: 8px;"
        )
        layout.addWidget(badge, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self._caption("CORRECTION", card))
        layout.addWidget(self._rtl_text(str(entry.get("corrected", "—")), card))
        layout.addWidget(self._caption("ORIGINAL PAGE XML", card))
        layout.addWidget(self._rtl_text(str(entry.get("original", "—")), card))

        decision = str(entry.get("decision", ""))
        if decision:
            decision_label = self._caption(f"DECISION: {decision.upper()}", card)
            layout.addWidget(decision_label)
        line_id = str(entry.get("line_id", ""))
        if bool(entry.get("actionable")) and line_id and decision not in {
            "kept",
            "rejected",
        }:
            keep = QPushButton("Keep", card)
            reject = QPushButton("Reject / Revert", card)
            keep.clicked.connect(
                lambda checked=False, value=line_id: self.keepLineRequested.emit(value)
            )
            reject.clicked.connect(
                lambda checked=False, value=line_id: self.rejectLineRequested.emit(value)
            )
            row = QHBoxLayout()
            row.addStretch(1)
            row.addWidget(keep)
            row.addWidget(reject)
            layout.addLayout(row)
        return card

    @staticmethod
    def _caption(text: str, parent: QWidget) -> QLabel:
        label = QLabel(text, parent)
        label.setStyleSheet("font-size: 10px; color: palette(mid);")
        return label

    @staticmethod
    def _rtl_text(text: str, parent: QWidget) -> QLabel:
        label = QLabel(text or "—", parent)
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        label.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        label.setAlignment(Qt.AlignmentFlag.AlignRight)
        return label

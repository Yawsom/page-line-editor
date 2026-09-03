"""Right-hand correction review and validation panel."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QPalette
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

from ..diff_markup import compare_text, rich_diff_text


class ReviewPanel(QWidget):
    autoCorrectPageRequested = Signal()
    autoCorrectBatchRequested = Signal()
    cancelRequested = Signal()
    keepPageRequested = Signal()
    rejectPageRequested = Signal()
    keepLineRequested = Signal(str)
    rejectLineRequested = Signal(str)

    def __init__(self, parent=None) -> None:
        """Initialize the ReviewPanel instance."""
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
        """Set project summary."""
        self.project_label.setText(text)

    def set_validation(self, summary: str, messages: list[str] | tuple[str, ...] = ()) -> None:
        """Set validation."""
        self.validation_label.setText(summary)
        self.validation_messages.clear()
        self.validation_messages.addItems(messages)

    def set_correction_progress(self, value: int | None, status: str = "") -> None:
        """Set correction progress."""
        running = value is not None
        self.progress.setVisible(running)
        self.cancel_button.setVisible(running)
        self.correct_page_button.setEnabled(not running)
        self.correct_batch_button.setEnabled(not running)
        if value is not None:
            self.progress.setValue(value)
            self.progress.setFormat(status or "%p%")

    def set_corrections(self, entries: Iterable[Mapping[str, object]]) -> None:
        """Set corrections."""
        self._corrections = [dict(entry) for entry in entries]
        self._rebuild_corrections()

    def clear_corrections(self) -> None:
        """Remove all correction cards and reset the review panel."""
        self.set_corrections(())

    def _rebuild_corrections(self, *_args: object) -> None:
        """Rebuild correction cards from the current filtered entries."""
        while self.review_layout.count() > 1:
            item = self.review_layout.takeAt(0)
            if item is None:
                break
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
        """Return whether an entry matches the active review filter."""
        if filter_name == "Automatically changed":
            return bool(entry.get("actionable"))
        if filter_name == "Rejected":
            return entry.get("decision") == "rejected"
        if filter_name == "Warnings":
            return str(entry.get("status", "")) in {"MISSING", "SPLIT", "MERGE"}
        return True

    def _correction_card(self, entry: Mapping[str, object]) -> QFrame:
        """Build one reviewer-facing correction card."""
        card = QFrame(self.review_content)
        card.setObjectName("correctionReviewCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        status = str(entry.get("status", ""))
        header = QFrame(card)
        header.setObjectName("reviewDiffHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(8, 5, 8, 5)
        badge = QLabel(status, header)
        badge.setObjectName("reviewStatusBadge")
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header_layout.addWidget(badge)
        header_layout.addStretch(1)
        decision = str(entry.get("decision", ""))
        if decision:
            decision_label = QLabel(decision.upper().replace("_", " "), header)
            decision_label.setObjectName("reviewDecision")
            header_layout.addWidget(decision_label)
        layout.addWidget(header)
        corrected_text = str(entry.get("corrected", "—"))
        original_text = str(entry.get("original", "—"))
        show_diff = bool(entry.get("actionable")) and decision not in {
            "kept",
            "rejected",
        }
        corrected = self._rtl_text(corrected_text, card)
        corrected.setObjectName("reviewCorrectedText")
        if show_diff:
            original = self._rtl_text(original_text, card)
            original.setObjectName("reviewOriginalText")
            difference = compare_text(original_text, str(entry.get("after_text", "")))
            dark = self.palette().color(QPalette.ColorRole.Base).lightness() < 128
            if not bool(entry.get("removed")) and not bool(
                entry.get("proposed_removal")
            ):
                corrected.setTextFormat(Qt.TextFormat.RichText)
                corrected.setText(
                    rich_diff_text(difference.after, side="after", dark=dark)
                )
            original.setTextFormat(Qt.TextFormat.RichText)
            original.setText(
                rich_diff_text(difference.before, side="before", dark=dark)
            )
            layout.addWidget(self._review_diff_row("reviewAdditionRow", "+", corrected))
            layout.addWidget(self._review_diff_row("reviewDeletionRow", "−", original))
        else:
            layout.addWidget(self._review_diff_row("reviewNeutralRow", " ", corrected))

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
            footer = QFrame(card)
            footer.setObjectName("reviewDiffFooter")
            footer.setLayout(row)
            row.setContentsMargins(8, 6, 8, 6)
            layout.addWidget(footer)
        self._style_card(card, badge, status)
        return card

    @staticmethod
    def _review_diff_row(name: str, marker: str, content: QWidget) -> QFrame:
        """Build the text-difference row for a correction card."""
        frame = QFrame()
        frame.setObjectName(name)
        gutter = QLabel(marker, frame)
        gutter.setObjectName(f"{name}Gutter")
        gutter.setFixedWidth(28)
        gutter.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row = QHBoxLayout(frame)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        row.addWidget(gutter)
        row.addWidget(content, 1)
        return frame

    @staticmethod
    def _rtl_text(text: str, parent: QWidget) -> QLabel:
        """Create a right-to-left text label for Arabic content."""
        label = QLabel(text or "—", parent)
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        label.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        label.setAlignment(Qt.AlignmentFlag.AlignRight)
        label.setContentsMargins(7, 5, 7, 5)
        return label

    def _style_card(self, card: QFrame, badge: QLabel, status: str) -> None:
        """Apply theme-aware styling to a correction card."""
        dark = self.palette().color(QPalette.ColorRole.Base).lightness() < 128
        if dark:
            border, header, text = "#30363d", "#161b22", "#e6edf3"
            add_line, add_gutter = "#12261b", "#1f3d2a"
            del_line, del_gutter = "#321c20", "#512329"
        else:
            border, header, text = "#d0d7de", "#f6f8fa", "#1f2328"
            add_line, add_gutter = "#e6ffec", "#ccffd8"
            del_line, del_gutter = "#ffebe9", "#ffd7d5"
        card.setStyleSheet(
            f"QFrame#correctionReviewCard {{ border: 1px solid {border}; "
            "border-radius: 6px; }"
            f"QFrame#reviewDiffHeader, QFrame#reviewDiffFooter {{ background: {header}; }}"
            f"QFrame#reviewAdditionRow {{ background: {add_line}; "
            f"border-top: 1px solid {border}; }}"
            f"QLabel#reviewAdditionRowGutter {{ background: {add_gutter}; color: {text}; }}"
            f"QFrame#reviewDeletionRow {{ background: {del_line}; "
            f"border-top: 1px solid {border}; }}"
            f"QLabel#reviewDeletionRowGutter {{ background: {del_gutter}; color: {text}; }}"
            f"QFrame#reviewNeutralRow {{ background: {header}; "
            f"border-top: 1px solid {border}; }}"
            f"QLabel#reviewNeutralRowGutter {{ background: {header}; color: {text}; }}"
            f"QLabel#reviewCorrectedText, QLabel#reviewOriginalText {{ color: {text}; }}"
        )
        badge_colors = {
            "MATCHED": ("#1a7f37", "#dafbe1"),
            "OCR": ("#0969da", "#ddf4ff"),
            "REMOVED": ("#cf222e", "#ffebe9"),
            "EXTRA": ("#9a6700", "#fff8c5"),
            "MERGE": ("#8250df", "#fbefff"),
            "SPLIT": ("#8250df", "#fbefff"),
        }
        foreground, background = badge_colors.get(status, ("#57606a", "#f6f8fa"))
        if dark:
            background = header
            foreground = {
                "MATCHED": "#3fb950",
                "OCR": "#58a6ff",
                "REMOVED": "#ff7b72",
                "EXTRA": "#d29922",
                "MERGE": "#bc8cff",
                "SPLIT": "#bc8cff",
            }.get(status, "#8b949e")
        badge.setStyleSheet(
            f"color: {foreground}; background: {background}; border: 1px solid {foreground}; "
            "border-radius: 8px; font-weight: 700; padding: 1px 6px;"
        )

    def event(self, event: QEvent) -> bool:
        """Handle the Qt event."""
        result = super().event(event)
        if event.type() == QEvent.Type.PaletteChange and getattr(self, "_corrections", None):
            self._rebuild_corrections()
        return result

"""A single viewport overlay anchored beneath the selected PAGE line."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QRect, Qt, Signal
from PySide6.QtGui import QFontMetrics, QKeyEvent, QTextBlockFormat, QTextCursor
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..adapters import LineAdapter


class TranscriptionEdit(QPlainTextEdit):
    commitRequested = Signal()
    cancelRequested = Signal()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        modifiers = event.modifiers()
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and modifiers & (
            Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier
        ):
            self.commitRequested.emit()
            event.accept()
            return
        if event.key() == Qt.Key.Key_Escape:
            self.cancelRequested.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class TranscriptionOverlay(QFrame):
    textCommitRequested = Signal(object, str)
    keepRequested = Signal(str)
    rejectRequested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("transcriptionOverlay")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setAutoFillBackground(True)
        self.setMinimumWidth(280)
        self.setMaximumWidth(1000)
        self._line: LineAdapter | None = None
        self._committed_text = ""
        self._diff_visible = True

        self.line_label = QLabel(self)
        self.line_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.editor = TranscriptionEdit(self)
        self.editor.setObjectName("transcriptionEditor")
        self.editor.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self._set_editor_alignment(Qt.AlignmentFlag.AlignRight)
        self.editor.setFixedHeight(66)
        self.editor.setAccessibleName("Line transcription")

        self.diff_card = QFrame(self)
        self.diff_card.setObjectName("correctionComparison")
        self.diff_card.setFrameShape(QFrame.Shape.StyledPanel)
        self.status_badge = QLabel(self.diff_card)
        self.status_badge.setObjectName("correctionStatusBadge")
        self.status_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_badge.setStyleSheet(
            "font-weight: 700; padding: 2px 8px; border: 1px solid palette(mid); "
            "border-radius: 8px;"
        )
        self.corrected_caption = QLabel("CORRECTION", self.diff_card)
        self.corrected_caption.setStyleSheet("font-size: 10px; color: palette(mid);")
        self.corrected_label = QLabel(self.diff_card)
        self.corrected_label.setObjectName("correctedText")
        self.corrected_label.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.corrected_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.corrected_label.setWordWrap(True)
        self.original_caption = QLabel("ORIGINAL PAGE XML", self.diff_card)
        self.original_caption.setStyleSheet("font-size: 10px; color: palette(mid);")
        self.original_label = QLabel(self.diff_card)
        self.original_label.setObjectName("originalText")
        self.original_label.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.original_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.original_label.setWordWrap(True)
        self.diff_label = QLabel(self)
        self.diff_label.setObjectName("correctionDiff")
        self.diff_label.setAccessibleName("Automatic correction difference")
        self.diff_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.diff_label.setStyleSheet("color: palette(mid); font-size: 11px;")

        comparison_layout = QVBoxLayout(self.diff_card)
        comparison_layout.setContentsMargins(8, 7, 8, 7)
        comparison_layout.setSpacing(3)
        comparison_layout.addWidget(self.status_badge, 0, Qt.AlignmentFlag.AlignLeft)
        comparison_layout.addWidget(self.corrected_caption)
        comparison_layout.addWidget(self.corrected_label)
        comparison_layout.addWidget(self.original_caption)
        comparison_layout.addWidget(self.original_label)
        comparison_layout.addWidget(self.diff_label)

        self.keep_button = QPushButton("Keep", self)
        self.keep_button.setToolTip("Keep the automatically applied correction")
        self.reject_button = QPushButton("Reject / Revert", self)
        self.reject_button.setToolTip("Restore the text from before automatic correction")
        button_row = QHBoxLayout()
        button_row.addStretch(1)
        button_row.addWidget(self.keep_button)
        button_row.addWidget(self.reject_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(5)
        layout.addWidget(self.line_label)
        layout.addWidget(self.editor)
        layout.addWidget(self.diff_card)
        layout.addLayout(button_row)

        self.editor.commitRequested.connect(self.commit)
        self.editor.cancelRequested.connect(self.cancel)
        self.editor.textChanged.connect(self._sync_corrected_preview)
        self.keep_button.clicked.connect(self._keep)
        self.reject_button.clicked.connect(self._reject)
        self.hide()

    @property
    def line(self) -> LineAdapter | None:
        return self._line

    def set_line(self, line: LineAdapter | None) -> None:
        if self._line is not None and line is not self._line:
            self.commit_if_changed()
        self._line = line
        if line is None:
            self.hide()
            return
        self._committed_text = line.text
        self.line_label.setText(f"Line {line.id}")
        self.editor.setPlainText(line.text)
        self._set_editor_alignment(
            Qt.AlignmentFlag.AlignRight
            if self.editor.layoutDirection() == Qt.LayoutDirection.RightToLeft
            else Qt.AlignmentFlag.AlignLeft
        )
        self.editor.moveCursor(QTextCursor.MoveOperation.End)
        self.diff_label.setText(line.diff_text)
        self.status_badge.setText(line.correction_status)
        self.original_label.setText(line.pre_correction_text or "—")
        self._sync_corrected_preview()
        reviewable = line.proposal_state in {"proposed", "applied", "pending"}
        self.keep_button.setVisible(reviewable)
        self.reject_button.setVisible(reviewable)
        has_comparison = bool(line.correction_status or line.diff_text)
        self.diff_card.setVisible(self._diff_visible and has_comparison)
        self.diff_label.setVisible(bool(line.diff_text))
        self.adjustSize()
        self.show()
        self.raise_()

    def refresh(self) -> None:
        if self._line is not None:
            self.set_line(self._line)

    def set_diff_visible(self, visible: bool) -> None:
        self._diff_visible = visible
        self.diff_card.setVisible(
            visible and bool(self.status_badge.text() or self.diff_label.text())
        )
        self.adjustSize()

    def set_text_direction(self, direction: Qt.LayoutDirection) -> None:
        self.editor.setLayoutDirection(direction)
        alignment = (
            Qt.AlignmentFlag.AlignRight
            if direction == Qt.LayoutDirection.RightToLeft
            else Qt.AlignmentFlag.AlignLeft
        )
        self._set_editor_alignment(alignment)

    def _set_editor_alignment(self, alignment: Qt.AlignmentFlag) -> None:
        """Apply paragraph alignment to a QPlainTextEdit document.

        QPlainTextEdit intentionally has no QWidget-level ``setAlignment`` API;
        alignment belongs to its text blocks instead.
        """

        cursor = self.editor.textCursor()
        position = cursor.position()
        cursor.select(QTextCursor.SelectionType.Document)
        block_format = QTextBlockFormat()
        block_format.setAlignment(alignment)
        cursor.mergeBlockFormat(block_format)
        cursor.clearSelection()
        cursor.setPosition(min(position, len(self.editor.toPlainText())))
        self.editor.setTextCursor(cursor)

    def commit_if_changed(self) -> bool:
        if self._line is None:
            return False
        value = self.editor.toPlainText()
        if value == self._committed_text:
            return False
        self.textCommitRequested.emit(self._line, value)
        self._committed_text = value
        return True

    def commit(self) -> None:
        self.commit_if_changed()

    def cancel(self) -> None:
        self.editor.setPlainText(self._committed_text)
        self.editor.selectAll()

    def anchor_below(self, line_rect: QRect, viewport_width: int) -> None:
        line_thickness = max(20, min(line_rect.width(), line_rect.height()))
        font_size = min(46, max(15, round(line_thickness * 0.42)))
        editor_font = self.editor.font()
        editor_font.setPixelSize(font_size)
        self.editor.setFont(editor_font)
        comparison_font = self.corrected_label.font()
        comparison_font.setPixelSize(max(14, min(32, round(font_size * 0.82))))
        self.corrected_label.setFont(comparison_font)
        self.original_label.setFont(comparison_font)
        editor_height = min(112, max(52, QFontMetrics(editor_font).height() * 2 + 14))
        self.editor.setFixedHeight(editor_height)

        available = max(280, viewport_width - 20)
        geometry_width = max(280, line_rect.width())
        width = min(geometry_width, available, self.maximumWidth())
        self.resize(width, self.sizeHint().height())
        x = max(8, min(line_rect.left(), viewport_width - width - 8))
        # Never flip the editor above the selected line. PageScene provides a lower margin.
        self.move(x, line_rect.bottom() + 8)

    def _sync_corrected_preview(self) -> None:
        self.corrected_label.setText(self.editor.toPlainText() or "—")

    def _keep(self) -> None:
        if self._line is not None:
            self.keepRequested.emit(self._line.id)

    def _reject(self) -> None:
        if self._line is not None:
            self.rejectRequested.emit(self._line.id)

    def event(self, event: QEvent) -> bool:
        if event.type() == QEvent.Type.PaletteChange:
            self.setAutoFillBackground(True)
        return super().event(event)

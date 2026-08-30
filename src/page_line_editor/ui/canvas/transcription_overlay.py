"""GitHub-style single-line transcription diff anchored beneath a PAGE line."""

from __future__ import annotations

from typing import Any, cast

from PySide6.QtCore import QEvent, QMimeData, QRect, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFontMetrics,
    QKeyEvent,
    QPalette,
    QTextBlockFormat,
    QTextCharFormat,
    QTextCursor,
)
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..adapters import LineAdapter
from ..diff_markup import compare_text, rich_diff_text


class TranscriptionEdit(QPlainTextEdit):
    """Single-line plain-text editor with non-destructive addition highlights."""

    commitRequested = Signal()
    cancelRequested = Signal()
    navigateRequested = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.document().setDocumentMargin(0)

    def setPlainText(self, value: str) -> None:  # noqa: N802 - Qt API refinement
        super().setPlainText(value.replace("\r", " ").replace("\n", " "))

    def text(self) -> str:
        return self.toPlainText()

    def setCursorPosition(self, position: int) -> None:  # noqa: N802 - compatibility API
        cursor = self.textCursor()
        cursor.setPosition(max(0, min(position, len(self.toPlainText()))))
        self.setTextCursor(cursor)

    def setAlignment(self, alignment: Qt.AlignmentFlag) -> None:  # noqa: N802
        cursor = self.textCursor()
        position = cursor.position()
        cursor.select(QTextCursor.SelectionType.Document)
        block_format = QTextBlockFormat()
        block_format.setAlignment(alignment)
        cursor.mergeBlockFormat(block_format)
        cursor.clearSelection()
        cursor.setPosition(min(position, len(self.toPlainText())))
        self.setTextCursor(cursor)

    def set_addition_ranges(
        self,
        ranges: tuple[tuple[int, int], ...],
        color: QColor,
    ) -> None:
        selections: list[QTextEdit.ExtraSelection] = []
        for start, end in ranges:
            selection = cast(Any, QTextEdit.ExtraSelection())
            selection.cursor = self.textCursor()
            selection.cursor.setPosition(start)
            selection.cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
            selection.format = QTextCharFormat()
            selection.format.setBackground(color)
            selection.format.setFontWeight(600)
            selections.append(selection)
        self.setExtraSelections(selections)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.modifiers() == Qt.KeyboardModifier.NoModifier and event.key() in (
            Qt.Key.Key_Up,
            Qt.Key.Key_Down,
        ):
            self.navigateRequested.emit(-1 if event.key() == Qt.Key.Key_Up else 1)
            event.accept()
            return
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.commitRequested.emit()
            event.accept()
            return
        if event.key() == Qt.Key.Key_Escape:
            self.cancelRequested.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def insertFromMimeData(self, source: QMimeData) -> None:  # noqa: N802 - Qt override
        self.insertPlainText(source.text().replace("\r", " ").replace("\n", " "))


class TranscriptionOverlay(QFrame):
    textCommitRequested = Signal(object, str)
    keepRequested = Signal(str)
    rejectRequested = Signal(str)
    navigateLineRequested = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("transcriptionOverlay")
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setAutoFillBackground(True)
        self.setMinimumWidth(320)
        self.setMaximumWidth(1100)
        self._line: LineAdapter | None = None
        self._committed_text = ""
        self._original_text = ""
        self._diff_visible = True
        self._comparison_active = False

        self.diff_card = QFrame(self)
        self.diff_card.setObjectName("correctionComparison")
        self.line_label = QLabel(self.diff_card)
        self.line_label.setObjectName("diffHeaderLabel")
        self.line_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.status_badge = QLabel(self.diff_card)
        self.status_badge.setObjectName("correctionStatusBadge")
        self.status_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)

        header = QFrame(self.diff_card)
        header.setObjectName("diffHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(10, 6, 8, 6)
        header_layout.addWidget(self.line_label)
        header_layout.addStretch(1)
        header_layout.addWidget(self.status_badge)

        self.editor = TranscriptionEdit(self.diff_card)
        self.editor.setObjectName("transcriptionEditor")
        self.editor.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.editor.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.editor.setAccessibleName("Corrected line transcription")
        self.corrected_label = self.editor
        self.addition_gutter = QLabel("+", self.diff_card)
        self.addition_row = self._diff_row(
            "diffAdditionRow", self.addition_gutter, self.editor
        )

        self.original_label = QLabel(self.diff_card)
        self.original_label.setObjectName("originalText")
        self.original_label.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.original_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self.original_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.original_label.setTextFormat(Qt.TextFormat.RichText)
        self.original_label.setWordWrap(False)
        self.deletion_gutter = QLabel("−", self.diff_card)
        self.deletion_row = self._diff_row(
            "diffDeletionRow", self.deletion_gutter, self.original_label
        )

        self.diff_label = QLabel(self.diff_card)
        self.diff_label.setObjectName("correctionDiff")
        self.diff_label.setAccessibleName("Automatic correction difference")
        self.diff_label.hide()

        self.keep_button = QPushButton("Keep", self.diff_card)
        self.keep_button.setToolTip("Keep the automatically applied correction")
        self.reject_button = QPushButton("Reject / Revert", self.diff_card)
        self.reject_button.setToolTip("Restore the text from before automatic correction")
        self.button_frame = QFrame(self.diff_card)
        self.button_frame.setObjectName("diffFooter")
        button_row = QHBoxLayout(self.button_frame)
        button_row.setContentsMargins(8, 6, 8, 6)
        button_row.addStretch(1)
        button_row.addWidget(self.keep_button)
        button_row.addWidget(self.reject_button)

        comparison_layout = QVBoxLayout(self.diff_card)
        comparison_layout.setContentsMargins(0, 0, 0, 0)
        comparison_layout.setSpacing(0)
        comparison_layout.addWidget(header)
        comparison_layout.addWidget(self.addition_row)
        comparison_layout.addWidget(self.deletion_row)
        comparison_layout.addWidget(self.button_frame)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.diff_card)

        self.editor.commitRequested.connect(self.commit)
        self.editor.cancelRequested.connect(self.cancel)
        self.editor.navigateRequested.connect(self.navigateLineRequested)
        self.editor.textChanged.connect(self._update_diff_markup)
        self.keep_button.clicked.connect(self._keep)
        self.reject_button.clicked.connect(self._reject)
        self._apply_diff_style()
        self.hide()

    @staticmethod
    def _diff_row(name: str, gutter: QLabel, content: QWidget) -> QFrame:
        row = QFrame()
        row.setObjectName(name)
        gutter.setObjectName(f"{name}Gutter")
        gutter.setFixedWidth(34)
        gutter.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(gutter)
        layout.addWidget(content, 1)
        return row

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
        self._original_text = line.pre_correction_text or line.text
        reviewable = line.proposal_state in {"proposed", "applied", "pending"}
        self._comparison_active = reviewable and bool(
            line.correction_status or line.diff_text
        )
        self.line_label.setText(f"TextLine · {line.id}")
        self.editor.setPlainText(line.text)
        self.editor.setCursorPosition(len(self.editor.text()))
        self.diff_label.setText(line.diff_text)
        self.status_badge.setText(line.correction_status)
        self.keep_button.setVisible(reviewable)
        self.reject_button.setVisible(reviewable)
        self.button_frame.setVisible(reviewable)
        show_diff = self._diff_visible and self._comparison_active
        self.status_badge.setVisible(show_diff)
        self.deletion_row.setVisible(show_diff)
        self.addition_gutter.setText("+" if show_diff else " ")
        self._update_diff_markup()
        self._apply_diff_style()
        self.adjustSize()
        self.show()
        self.raise_()

    def refresh(self) -> None:
        if self._line is not None:
            self.set_line(self._line)

    def set_diff_visible(self, visible: bool) -> None:
        self._diff_visible = visible
        show_diff = visible and self._comparison_active
        self.status_badge.setVisible(show_diff)
        self.deletion_row.setVisible(show_diff)
        self.addition_gutter.setText("+" if show_diff else " ")
        self._update_diff_markup()
        self._apply_diff_style()
        self.adjustSize()

    def set_text_direction(self, direction: Qt.LayoutDirection) -> None:
        self.editor.setLayoutDirection(direction)
        self.original_label.setLayoutDirection(direction)
        alignment = (
            Qt.AlignmentFlag.AlignRight
            if direction == Qt.LayoutDirection.RightToLeft
            else Qt.AlignmentFlag.AlignLeft
        )
        self.editor.setAlignment(alignment | Qt.AlignmentFlag.AlignVCenter)
        self.original_label.setAlignment(alignment | Qt.AlignmentFlag.AlignVCenter)

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
        available = max(320, viewport_width - 20)
        geometry_width = max(320, line_rect.width())
        width = min(geometry_width, available, self.maximumWidth())
        line_thickness = max(20, min(line_rect.width(), line_rect.height()))
        font_size = min(52, max(15, round(line_thickness * 0.50)))
        editor_font = self.editor.font()
        editor_font.setPixelSize(font_size)
        content_width = max(80, width - self.addition_gutter.width() - 20)
        metrics = QFontMetrics(editor_font)
        widest = max(
            metrics.horizontalAdvance(self.editor.text()),
            metrics.horizontalAdvance(self._original_text),
            1,
        )
        if widest > content_width:
            editor_font.setPixelSize(max(12, int(font_size * content_width / widest)))
        self.editor.setFont(editor_font)
        self.original_label.setFont(editor_font)
        row_height = max(38, QFontMetrics(editor_font).height() + 14)
        self.editor.setFixedHeight(row_height)
        self.original_label.setFixedHeight(row_height)

        self.resize(width, self.sizeHint().height())
        x = max(8, min(line_rect.left(), viewport_width - width - 8))
        self.move(x, line_rect.bottom() + 2)

    def _apply_diff_style(self) -> None:
        dark = self.palette().color(QPalette.ColorRole.Base).lightness() < 128
        show_diff = self._comparison_active and self._diff_visible
        if dark:
            border, header = "#30363d", "#161b22"
            add_line, add_gutter = "#12261b", "#1f3d2a"
            del_line, del_gutter = "#321c20", "#512329"
            text, neutral = "#e6edf3", "#0d1117"
        else:
            border, header = "#d0d7de", "#f6f8fa"
            add_line, add_gutter = "#e6ffec", "#ccffd8"
            del_line, del_gutter = "#ffebe9", "#ffd7d5"
            text, neutral = "#1f2328", "#ffffff"
        if not show_diff:
            add_line = neutral
            add_gutter = header
        self.diff_card.setStyleSheet(
            f"QFrame#correctionComparison {{ border: 1px solid {border}; "
            "border-radius: 6px; }"
            f"QFrame#diffHeader, QFrame#diffFooter {{ background: {header}; }}"
            f"QFrame#diffAdditionRow {{ background: {add_line}; "
            f"border-top: 1px solid {border}; }}"
            f"QLabel#diffAdditionRowGutter {{ background: {add_gutter}; color: {text}; }}"
            f"QFrame#diffDeletionRow {{ background: {del_line}; "
            f"border-top: 1px solid {border}; }}"
            f"QLabel#diffDeletionRowGutter {{ background: {del_gutter}; color: {text}; }}"
            "QPlainTextEdit#transcriptionEditor { background: transparent; border: none; "
            f"color: {text}; padding: 4px 8px; }}"
            f"QLabel#originalText {{ color: {text}; padding: 4px 8px; }}"
        )
        status = self.status_badge.text().upper()
        badge_colors = {
            "MATCHED": ("#1a7f37", "#dafbe1"),
            "OCR": ("#0969da", "#ddf4ff"),
            "REMOVED": ("#cf222e", "#ffebe9"),
            "EXTRA": ("#9a6700", "#fff8c5"),
            "MERGE": ("#8250df", "#fbefff"),
            "SPLIT": ("#8250df", "#fbefff"),
            "MISSING": ("#9a6700", "#fff8c5"),
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
                "MISSING": "#d29922",
            }.get(status, "#8b949e")
        self.status_badge.setStyleSheet(
            f"color: {foreground}; background: {background}; border: 1px solid {foreground}; "
            "border-radius: 9px; font-weight: 700; padding: 2px 8px;"
        )

    def _update_diff_markup(self) -> None:
        show_diff = self._comparison_active and self._diff_visible
        if not show_diff:
            self.original_label.setTextFormat(Qt.TextFormat.PlainText)
            self.original_label.setText(self._original_text or "—")
            self.editor.set_addition_ranges((), QColor())
            return
        difference = compare_text(self._original_text, self.editor.toPlainText())
        dark = self.palette().color(QPalette.ColorRole.Base).lightness() < 128
        self.original_label.setTextFormat(Qt.TextFormat.RichText)
        self.original_label.setText(
            rich_diff_text(difference.before, side="before", dark=dark)
        )
        highlight = QColor(46, 160, 67, 100) if dark else QColor("#abf2bc")
        self.editor.set_addition_ranges(difference.addition_ranges, highlight)

    def _keep(self) -> None:
        if self._line is not None:
            self.keepRequested.emit(self._line.id)

    def _reject(self) -> None:
        if self._line is not None:
            self.rejectRequested.emit(self._line.id)

    def event(self, event: QEvent) -> bool:
        result = super().event(event)
        if event.type() == QEvent.Type.PaletteChange:
            self.setAutoFillBackground(True)
            self._apply_diff_style()
            self._update_diff_markup()
        return result

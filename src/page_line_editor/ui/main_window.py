"""Main window and public integration surface for PAGE Line Editor."""

from __future__ import annotations

import unicodedata
from pathlib import Path
from typing import Any

from PySide6.QtCore import QSettings, QSize, Qt, Signal
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QCloseEvent,
    QIcon,
    QKeySequence,
    QShortcut,
    QUndoStack,
)
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDockWidget,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QToolBar,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
)

from .adapters import LineAdapter
from .canvas import EditMode, PageCanvasView
from .commands import TextEditCommand
from .panels import ProjectOpenDialog, ProjectPaths, ReviewPanel
from .themes import Theme, apply_theme


class MainWindow(QMainWindow):
    """Modern Qt Widgets shell; application services connect to its signals."""

    openProjectRequested = Signal(object)
    saveRequested = Signal()
    pageRequested = Signal(object)
    autoCorrectPageRequested = Signal()
    autoCorrectBatchRequested = Signal()
    cancelCorrectionRequested = Signal()
    keepCorrectionRequested = Signal(str)
    rejectCorrectionRequested = Signal(str)
    keepPageCorrectionsRequested = Signal()
    rejectPageCorrectionsRequested = Signal()
    lineTextChanged = Signal(str, str)
    lineGeometryChanged = Signal(str, object, object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("mainWindow")
        self.setWindowTitle("PAGE Line Editor")
        self.resize(1440, 900)
        self.undo_stack = QUndoStack(self)
        self.undo_stack.setClean()
        self.canvas = PageCanvasView(self)
        self.canvas.set_undo_stack(self.undo_stack)
        self.setCentralWidget(self.canvas)
        self.page_list = QTreeWidget(self)
        self.page_list.setObjectName("pageBrowser")
        self.page_list.setHeaderLabels(("Page", "Pairing / status"))
        self.page_list.setRootIsDecorated(False)
        self.review_panel = ReviewPanel(self)
        self._current_page_payload: Any = None
        self._project_paths: ProjectPaths | None = None
        self._theme = Theme.SYSTEM
        self._transcription_mode = False
        self._build_docks()
        self._build_actions()
        self._build_canvas_shortcuts()
        self._build_toolbar()
        self.mode_indicator = QLabel(self)
        self.mode_indicator.setObjectName("modeIndicator")
        self.mode_indicator.setAccessibleName("Current editor mode")
        self.statusBar().addPermanentWidget(self.mode_indicator)
        self._connect_signals()
        self._update_mode_indicator()
        self.statusBar().showMessage("Open a project to begin")
        self._restore_preferences()

    def _build_docks(self) -> None:
        pages_dock = QDockWidget("Pages", self)
        pages_dock.setObjectName("pagesDock")
        pages_dock.setWidget(self.page_list)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, pages_dock)
        review_dock = QDockWidget("Review", self)
        review_dock.setObjectName("reviewDock")
        review_dock.setWidget(self.review_panel)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, review_dock)

    def _action(
        self,
        text: str,
        slot,
        shortcut: QKeySequence | QKeySequence.StandardKey | str | None = None,
        tooltip: str = "",
        checkable: bool = False,
    ) -> QAction:
        action = QAction(text, self)
        action.setToolTip(tooltip or text)
        action.setStatusTip(tooltip or text)
        action.setCheckable(checkable)
        if shortcut is not None:
            action.setShortcut(shortcut)
        action.triggered.connect(slot)
        return action

    def _build_actions(self) -> None:
        self.open_action = self._action(
            "Open Project…", self.open_project_dialog, QKeySequence.StandardKey.Open,
            "Open separate image and PAGE XML folders",
        )
        self.save_action = self._action(
            "Save", self.request_save, QKeySequence.StandardKey.Save,
            "Validate, back up, and save the current PAGE XML",
        )
        self.undo_action = self.undo_stack.createUndoAction(self, "Undo")
        self.undo_action.setShortcuts(QKeySequence.StandardKey.Undo)
        self.redo_action = self.undo_stack.createRedoAction(self, "Redo")
        self.redo_action.setShortcuts(QKeySequence.StandardKey.Redo)
        self.previous_action = self._action("Previous", self.previous_page, QKeySequence("PgUp"))
        self.next_action = self._action("Next", self.next_page, QKeySequence("PgDown"))
        self.zoom_in_action = self._action(
            "Zoom In", self.canvas.zoom_in, QKeySequence.StandardKey.ZoomIn
        )
        self.zoom_out_action = self._action(
            "Zoom Out", self.canvas.zoom_out, QKeySequence.StandardKey.ZoomOut
        )
        self.fit_action = self._action(
            "Fit", self.canvas.fit_page, QKeySequence("F"), "Fit page to view"
        )
        self.rotate_left_action = self._action(
            "Rotate Left", self.canvas.rotate_left, QKeySequence("[")
        )
        self.rotate_right_action = self._action(
            "Rotate Right", self.canvas.rotate_right, QKeySequence("]")
        )
        self.reset_rotation_action = self._action("Reset Rotation", self.canvas.reset_rotation)
        self.polygons_action = self._action("Polygons", self._update_overlays, checkable=True)
        self.polygons_action.setChecked(True)
        self.baselines_action = self._action("Baselines", self._update_overlays, checkable=True)
        self.baselines_action.setChecked(True)
        self.diff_action = self._action("Diff", self._update_diff, checkable=True)
        self.diff_action.setChecked(True)
        self.normalize_action = self._action("Unicode NFC", lambda: None, checkable=True)
        self.normalize_action.setChecked(True)
        self.transcription_mode_action = self._action(
            "Transcription Mode",
            self.set_transcription_mode,
            tooltip="Hide geometry and focus on transcription (Ctrl/Cmd+T)",
            checkable=True,
        )
        self.transcription_mode_action.setShortcuts(
            (QKeySequence("Ctrl+T"), QKeySequence("Meta+T"))
        )

        self.mode_group = QActionGroup(self)
        self.mode_group.setExclusive(True)
        mode_specs = (
            ("Pan Canvas", EditMode.PAN, "H", "pan.svg"),
            ("Select / Edit", EditMode.SELECT, "V", "select.svg"),
            ("Move Whole Line", EditMode.MOVE_LINE, "M", "move.svg"),
            ("Add Vertex", EditMode.ADD_VERTEX, "A", "add-vertex.svg"),
            ("Delete Vertex", EditMode.DELETE_VERTEX, "D", "delete-vertex.svg"),
            ("Replace Polygon", EditMode.REPLACE_POLYGON, "P", "polygon.svg"),
            ("Replace Baseline", EditMode.REPLACE_BASELINE, "B", "baseline.svg"),
        )
        self.mode_actions: dict[EditMode, QAction] = {}
        icon_directory = Path(__file__).parent / "icons"
        for label, mode, shortcut, icon_name in mode_specs:
            action = self._action(
                label,
                lambda checked=False, value=mode: self._set_edit_mode(value),
                shortcut,
                tooltip=f"{label} ({shortcut})",
                checkable=True,
            )
            action.setIcon(QIcon(str(icon_directory / icon_name)))
            self.mode_group.addAction(action)
            self.mode_actions[mode] = action
        self.mode_actions[EditMode.SELECT].setChecked(True)

        self.correct_page_action = self._action(
            "Auto-correct Page",
            self.autoCorrectPageRequested,
            tooltip="Apply automatic correction to this page in memory",
        )
        self.correct_batch_action = self._action(
            "Auto-correct Folder",
            self.autoCorrectBatchRequested,
            tooltip="Apply automatic correction to the project in memory",
        )

    def _build_canvas_shortcuts(self) -> None:
        """Reserve review/navigation keys before child widgets consume them."""

        self.previous_line_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Up), self.canvas)
        self.previous_line_shortcut.setContext(
            Qt.ShortcutContext.WidgetWithChildrenShortcut
        )
        self.previous_line_shortcut.activated.connect(
            lambda: self.canvas.select_adjacent_line(-1)
        )
        self.next_line_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Down), self.canvas)
        self.next_line_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.next_line_shortcut.activated.connect(
            lambda: self.canvas.select_adjacent_line(1)
        )
        self.accept_change_shortcuts = tuple(
            QShortcut(QKeySequence(key), self.canvas)
            for key in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
        )
        for shortcut in self.accept_change_shortcuts:
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(self._accept_selected_change)
        self.reject_change_shortcut = QShortcut(
            QKeySequence(Qt.Key.Key_Backspace), self.canvas
        )
        self.reject_change_shortcut.setContext(
            Qt.ShortcutContext.WidgetWithChildrenShortcut
        )
        self.reject_change_shortcut.activated.connect(self._reject_selected_change)

    def _accept_selected_change(self) -> None:
        if self.canvas.has_pending_replacement:
            self.canvas.finish_replacement()
            return
        if QApplication.focusWidget() is self.canvas.overlay.editor:
            self.canvas.overlay.commit_if_changed()
        self.canvas.accept_selected_correction()

    def _reject_selected_change(self) -> None:
        editor = self.canvas.overlay.editor
        if QApplication.focusWidget() is editor:
            # Keep ordinary text editing safe: Backspace rejects only while
            # the selected line/canvas has focus, never while typing.
            cursor = editor.textCursor()
            if cursor.hasSelection():
                cursor.removeSelectedText()
            else:
                cursor.deletePreviousChar()
            editor.setTextCursor(cursor)
            return
        self.canvas.reject_selected_correction()

    def _build_toolbar(self) -> None:
        toolbar = QToolBar("Editor", self)
        toolbar.setObjectName("editorToolbar")
        toolbar.setMovable(False)
        for action in (
            self.open_action, self.save_action, self.undo_action, self.redo_action,
            self.previous_action, self.next_action, self.zoom_out_action, self.zoom_in_action,
            self.fit_action,
        ):
            toolbar.addAction(action)
            button = toolbar.widgetForAction(action)
            if button is not None:
                button.setAccessibleName(action.text())
                button.setAccessibleDescription(action.statusTip())
        toolbar.addSeparator()
        self.view_menu = QMenu("View", toolbar)
        self.view_menu.addActions(
            (
                self.rotate_left_action,
                self.rotate_right_action,
                self.reset_rotation_action,
                self.polygons_action,
                self.baselines_action,
                self.diff_action,
                self.normalize_action,
            )
        )
        self.view_button = self._toolbar_menu_button(toolbar, "View", self.view_menu)
        toolbar.addWidget(self.view_button)
        toolbar.addAction(self.transcription_mode_action)

        self.correction_menu = QMenu("Automatic correction", toolbar)
        self.correction_menu.addActions((self.correct_page_action, self.correct_batch_action))
        self.correction_button = self._toolbar_menu_button(
            toolbar, "Auto-correct ▾", self.correction_menu
        )
        toolbar.addWidget(self.correction_button)
        self.theme_combo = QComboBox(toolbar)
        self.theme_combo.setAccessibleName("Application theme")
        self.theme_combo.addItems([theme.value for theme in Theme])
        toolbar.addWidget(self.theme_combo)
        self.addToolBar(toolbar)

        self.tools_toolbar = QToolBar("Tools", self)
        self.tools_toolbar.setObjectName("toolsToolbar")
        self.tools_toolbar.setMovable(False)
        self.tools_toolbar.setIconSize(QSize(24, 24))
        self.tools_toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        for index, action in enumerate(self.mode_group.actions()):
            if index in (3, 5):
                self.tools_toolbar.addSeparator()
            self.tools_toolbar.addAction(action)
            button = self.tools_toolbar.widgetForAction(action)
            if button is not None:
                button.setAccessibleName(action.text())
                button.setAccessibleDescription(action.statusTip())
        self.addToolBar(Qt.ToolBarArea.LeftToolBarArea, self.tools_toolbar)

    @staticmethod
    def _toolbar_menu_button(
        toolbar: QToolBar,
        text: str,
        menu: QMenu,
    ) -> QToolButton:
        button = QToolButton(toolbar)
        button.setText(text)
        button.setMenu(menu)
        button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        return button

    def _connect_signals(self) -> None:
        self.page_list.currentItemChanged.connect(self._page_item_changed)
        self.canvas.overlay.textCommitRequested.connect(self._commit_text)
        self.canvas.overlay.keepRequested.connect(self.keepCorrectionRequested)
        self.canvas.overlay.rejectRequested.connect(self.rejectCorrectionRequested)
        self.canvas.keepCorrectionRequested.connect(self.keepCorrectionRequested)
        self.canvas.rejectCorrectionRequested.connect(self.rejectCorrectionRequested)
        self.canvas.lineGeometryChanged.connect(self.lineGeometryChanged)
        self.canvas.editModeRequested.connect(self._activate_edit_mode)
        self.canvas.geometryEditRejected.connect(
            lambda message: self.statusBar().showMessage(f"Edit rejected: {message}", 6000)
        )
        self.canvas.zoomChanged.connect(self._update_status)
        self.canvas.rotationChanged.connect(self._update_status)
        self.undo_stack.cleanChanged.connect(self._update_dirty_state)
        self.theme_combo.currentTextChanged.connect(self.set_theme)
        self.review_panel.autoCorrectPageRequested.connect(self.autoCorrectPageRequested)
        self.review_panel.autoCorrectBatchRequested.connect(self.autoCorrectBatchRequested)
        self.review_panel.cancelRequested.connect(self.cancelCorrectionRequested)
        self.review_panel.keepPageRequested.connect(self.keepPageCorrectionsRequested)
        self.review_panel.rejectPageRequested.connect(self.rejectPageCorrectionsRequested)
        self.review_panel.keepLineRequested.connect(self.keepCorrectionRequested)
        self.review_panel.rejectLineRequested.connect(self.rejectCorrectionRequested)

    def open_project_dialog(self) -> None:
        if not self.confirm_discard_or_save("opening another project"):
            return
        dialog = ProjectOpenDialog(self)
        if dialog.exec() == ProjectOpenDialog.DialogCode.Accepted:
            self._project_paths = dialog.paths()
            self.normalize_action.setChecked(self._project_paths.normalize_nfc)
            self.review_panel.set_project_summary(
                f"Images: {self._project_paths.image_directory}\n"
                f"XML: {self._project_paths.xml_directory}"
            )
            self.openProjectRequested.emit(self._project_paths)

    def set_pages(self, pages: list[Any] | tuple[Any, ...]) -> None:
        """Populate the browser with duck-typed PagePair/domain records."""

        self.page_list.clear()
        for page in pages:
            image = getattr(page, "image_path", getattr(page, "image", ""))
            xml = getattr(page, "xml_path", getattr(page, "xml", ""))
            name = Path(str(image or xml)).stem or str(getattr(page, "name", "Untitled"))
            method = getattr(page, "pairing_method", getattr(page, "status", "matched"))
            diagnostics = getattr(page, "diagnostics", ())
            status = str(getattr(method, "value", method))
            if diagnostics:
                status += f" · {len(diagnostics)} warning(s)"
            item = QTreeWidgetItem((name, status))
            item.setData(0, Qt.ItemDataRole.UserRole, page)
            item.setToolTip(1, "\n".join(map(str, diagnostics)))
            self.page_list.addTopLevelItem(item)
        if self.page_list.topLevelItemCount():
            first = self.page_list.topLevelItem(0)
            if first is not None:
                self.page_list.setCurrentItem(first)

    def load_page(
        self,
        image,
        lines,
        page_payload: Any = None,
        on_change=None,
        page_size: tuple[int, int] | None = None,
    ) -> None:
        self.canvas.set_page_size(*(page_size or (None, None)))
        self.canvas.set_page(image, lines, on_change)
        self._current_page_payload = page_payload
        self.undo_stack.clear()
        self.undo_stack.setClean()
        self._update_status()

    def set_correction_review(self, run: Any | None) -> None:
        if run is None:
            self.review_panel.clear_corrections()
            return
        entries: list[dict[str, object]] = []
        for application in run.applications:
            proposal = application.proposal
            decision = getattr(application.decision, "value", application.decision)
            live_line = None
            document = getattr(run, "document", None)
            line_id = proposal.primary_line_id or ""
            if document is not None and line_id:
                try:
                    live_line = document.line_by_id(line_id)
                except (KeyError, AttributeError):
                    live_line = None
            live_deleted = bool(getattr(live_line, "deleted", False))
            extra = proposal.status.value == "EXTRA"
            removed = extra and live_deleted and decision in {"kept", "applied"}
            status = "REMOVED" if removed else {
                "MATCH": "MATCHED",
            }.get(proposal.status.value, proposal.status.value)
            corrected = proposal.after_text
            if extra and not removed and decision == "pending":
                corrected = "Pending deletion (Keep to remove)"
            elif corrected is None:
                corrected = "Removed from PAGE XML" if removed else "Not automatically removed"
            if decision == "rejected":
                corrected = proposal.before_text or "—"
            entries.append(
                {
                    "line_id": proposal.primary_line_id or "",
                    "status": status,
                    "corrected": corrected or "—",
                    "after_text": proposal.after_text or "",
                    "original": proposal.before_text or "—",
                    "decision": str(decision),
                    "actionable": proposal.actionable,
                    "removed": removed,
                    "proposed_removal": extra and decision == "pending",
                }
            )
        self.review_panel.set_corrections(entries)

    def refresh_lines(self, lines, *, selected_line_id: str | None = None) -> None:
        """Rebuild line overlays while preserving the current view and undo stack."""

        image_item = self.canvas.page_scene.image_item
        if image_item is None:
            return
        pixmap = image_item.pixmap()
        transform = self.canvas.transform()
        center = self.canvas.mapToScene(self.canvas.viewport().rect().center())
        self.canvas.overlay.set_line(None)
        self.canvas.page_scene.set_page(pixmap, lines)
        self.canvas.set_edit_mode(self.canvas.edit_mode)
        self.canvas.setTransform(transform)
        self.canvas.centerOn(center)
        if selected_line_id:
            item = self.canvas.page_scene.line_item(selected_line_id)
            if item is not None:
                item.setSelected(True)
        self._update_overlays()
        self._update_status()

    def request_save(self) -> None:
        self.canvas.overlay.commit_if_changed()
        self.saveRequested.emit()

    def mark_saved(self) -> None:
        self.undo_stack.clear()
        self.undo_stack.setClean()
        self.statusBar().showMessage("Saved", 3000)

    def previous_page(self) -> None:
        row = self.page_list.indexOfTopLevelItem(self.page_list.currentItem())
        if row > 0:
            item = self.page_list.topLevelItem(row - 1)
            if item is not None:
                self.page_list.setCurrentItem(item)

    def next_page(self) -> None:
        row = self.page_list.indexOfTopLevelItem(self.page_list.currentItem())
        if 0 <= row < self.page_list.topLevelItemCount() - 1:
            item = self.page_list.topLevelItem(row + 1)
            if item is not None:
                self.page_list.setCurrentItem(item)

    def set_theme(self, theme: Theme | str) -> None:
        self._theme = apply_theme(QApplication.instance(), theme)  # type: ignore[arg-type]
        self.canvas.page_scene.set_theme(self._theme)
        QSettings().setValue("ui/theme", self._theme.value)

    def set_transcription_mode(self, enabled: bool) -> None:
        self._transcription_mode = bool(enabled)
        self.canvas.set_transcription_focus(self._transcription_mode)
        self.mode_actions[EditMode.SELECT].trigger()
        for mode, action in self.mode_actions.items():
            action.setEnabled(
                not self._transcription_mode or mode in {EditMode.PAN, EditMode.SELECT}
            )
        self.tools_toolbar.setVisible(not self._transcription_mode)
        self._update_mode_indicator()
        self._update_overlays()
        label = "Transcription mode" if self._transcription_mode else "Geometry mode"
        self.statusBar().showMessage(f"{label} · Ctrl/Cmd+T to switch", 4000)

    def _activate_edit_mode(self, mode: EditMode | str) -> None:
        if self._transcription_mode:
            self.transcription_mode_action.trigger()
        self.mode_actions[EditMode(mode)].trigger()

    def _set_edit_mode(self, mode: EditMode | str) -> None:
        self.canvas.set_edit_mode(mode)
        self._update_mode_indicator()

    def _update_mode_indicator(self) -> None:
        if self._transcription_mode:
            self.mode_indicator.setText("Mode: Transcription")
            return
        mode = EditMode(self.canvas.edit_mode)
        self.mode_indicator.setText(f"Mode: {self.mode_actions[mode].text()}")

    def set_correction_progress(self, value: int | None, status: str = "") -> None:
        self.review_panel.set_correction_progress(value, status)
        if status:
            self.statusBar().showMessage(status)

    def set_validation(self, summary: str, messages: list[str] | tuple[str, ...] = ()) -> None:
        self.review_panel.set_validation(summary, messages)

    def confirm_discard_or_save(self, operation: str) -> bool:
        self.canvas.overlay.commit_if_changed()
        if self.undo_stack.isClean():
            return True
        answer = QMessageBox.warning(
            self,
            "Unsaved changes",
            f"The current page has unsaved changes. Save before {operation}?",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save,
        )
        if answer == QMessageBox.StandardButton.Cancel:
            return False
        if answer == QMessageBox.StandardButton.Save:
            self.saveRequested.emit()
            # Saving may be asynchronous. Stay on the current page until the
            # application service calls mark_saved and repeats the operation.
            return self.undo_stack.isClean()
        return True

    def _page_item_changed(
        self,
        current: QTreeWidgetItem | None,
        previous: QTreeWidgetItem | None,
    ) -> None:
        if current is None:
            return
        if previous is not None and not self.confirm_discard_or_save("changing pages"):
            self.page_list.blockSignals(True)
            self.page_list.setCurrentItem(previous)
            self.page_list.blockSignals(False)
            return
        payload = current.data(0, Qt.ItemDataRole.UserRole)
        self.pageRequested.emit(payload)

    def _commit_text(self, line: LineAdapter, value: str) -> None:
        if self.normalize_action.isChecked():
            value = unicodedata.normalize("NFC", value)
        before = line.text
        if before == value:
            return

        def notify(updated: LineAdapter) -> None:
            item = self.canvas.page_scene.line_item(updated.id)
            if item is not None:
                item.update()
            self.lineTextChanged.emit(updated.id, updated.text)

        self.undo_stack.push(TextEditCommand(line, before, value, notify))

    def _update_overlays(self) -> None:
        self.canvas.set_overlay_visibility(
            self.polygons_action.isChecked() and not self._transcription_mode,
            self.baselines_action.isChecked() and not self._transcription_mode,
        )

    def _update_diff(self) -> None:
        self.canvas.overlay.set_diff_visible(self.diff_action.isChecked())
        self.canvas.update_overlay_position()

    def _update_dirty_state(self, *args) -> None:
        del args
        dirty = not self.undo_stack.isClean()
        self.setWindowModified(dirty)
        self.setWindowTitle("PAGE Line Editor[*]")
        self._update_status()

    def _update_status(self, *args) -> None:
        del args
        item = self.canvas.page_scene.selected_line_item()
        selected = f" · Line {item.adapter.id}" if item is not None else ""
        dirty = " · Modified" if not self.undo_stack.isClean() else ""
        self.statusBar().showMessage(
            f"Zoom {self.canvas.zoom_factor * 100:.0f}% · "
            f"Rotation {self.canvas.view_rotation}°{selected}{dirty}"
        )

    def _restore_preferences(self) -> None:
        theme = str(QSettings().value("ui/theme", Theme.SYSTEM.value))
        if theme not in {value.value for value in Theme}:
            theme = Theme.SYSTEM.value
        self.theme_combo.setCurrentText(theme)
        self.set_theme(theme)

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.confirm_discard_or_save("quitting"):
            event.accept()
        else:
            event.ignore()

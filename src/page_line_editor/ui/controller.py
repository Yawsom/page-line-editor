"""Qt application controller joining the UI to PAGE and correction services."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot
from PySide6.QtGui import QUndoCommand
from PySide6.QtWidgets import QMessageBox

from page_line_editor.application.auto_workflow import (
    AutoCorrectionWorkflow,
    DocumentLineState,
    PageAutoCorrectionRun,
    ReviewDecision,
)
from page_line_editor.application.ground_truth import GroundTruthBook
from page_line_editor.application.history_service import DocumentHistory
from page_line_editor.application.project_scanner import PagePair
from page_line_editor.application.save_service import SaveError, ValidationFailed
from page_line_editor.application.session import EditorSession
from page_line_editor.correction import CancellationToken, PageCorrectionProposal
from page_line_editor.domain.page import PageDocument
from page_line_editor.pagexml.parser import parse_page

from .main_window import MainWindow
from .panels import ProjectPaths


class _WorkerSignals(QObject):
    completed = Signal(object)
    failed = Signal(str)
    progress = Signal(int, str)


class _CorrectionTask(QRunnable):
    """Run one immutable correction proposal job outside the GUI thread."""

    def __init__(
        self,
        operation: Callable[[CancellationToken, Callable[[int, str], None]], object],
    ) -> None:
        super().__init__()
        self.operation = operation
        self.token = CancellationToken()
        self.signals = _WorkerSignals()

    @Slot()
    def run(self) -> None:
        try:
            result = self.operation(self.token, self.signals.progress.emit)
        except Exception as error:  # routed to a user-visible error boundary
            self.signals.failed.emit(f"{type(error).__name__}: {error}")
        else:
            self.signals.completed.emit(result)


class _DocumentStateCommand(QUndoCommand):
    """One undo step for a complete automatic correction application."""

    def __init__(
        self,
        document: PageDocument,
        before: tuple[DocumentLineState, ...],
        after: tuple[DocumentLineState, ...],
        notify: Callable[[], None],
        label: str = "Apply automatic correction",
    ) -> None:
        super().__init__(label)
        self.document = document
        self.before = before
        self.after = after
        self.notify = notify

    def _restore(self, states: tuple[DocumentLineState, ...]) -> None:
        for state in states:
            try:
                line = self.document.line_by_id(state.line_id)
            except KeyError:
                continue
            state.restore(line)
        self.document.revision += 1
        self.notify()

    def redo(self) -> None:
        self._restore(self.after)

    def undo(self) -> None:
        self._restore(self.before)


class _ReviewDecisionCommand(QUndoCommand):
    """Keep/Reject as an undoable step, including EXTRA tombstones and run decisions."""

    def __init__(
        self,
        run: PageAutoCorrectionRun,
        action: str,
        line_ids: tuple[str, ...],
        notify: Callable[[], None],
        label: str,
    ) -> None:
        super().__init__(label)
        self.run = run
        self.action = action
        self.line_ids = line_ids
        self.notify = notify
        snapshots: list[tuple[str, ReviewDecision, tuple[DocumentLineState, ...]]] = []
        seen: set[str] = set()
        for line_id in line_ids:
            application = run.application_for_line(line_id)
            if application.proposal.proposal_id in seen:
                continue
            seen.add(application.proposal.proposal_id)
            states = tuple(
                DocumentLineState.capture(run.document.line_by_id(affected))
                for affected in application.proposal.line_ids
            )
            snapshots.append((application.proposal.proposal_id, application.decision, states))
        self._snapshots = tuple(snapshots)

    def redo(self) -> None:
        for line_id in self.line_ids:
            if self.action == "keep":
                self.run.keep_line(line_id)
            else:
                self.run.reject_line(line_id)
        self.notify()

    def undo(self) -> None:
        by_proposal = {item.proposal.proposal_id: item for item in self.run.applications}
        for proposal_id, decision, states in self._snapshots:
            application = by_proposal[proposal_id]
            for state in states:
                try:
                    state.restore(self.run.document.line_by_id(state.line_id))
                except KeyError:
                    continue
            application.decision = decision
        self.run.document.revision += 1
        self.run._write_manifest()
        self.notify()


@dataclass(frozen=True, slots=True)
class _BatchProposal:
    pair: PagePair
    document: PageDocument
    proposal: PageCorrectionProposal
    source_digest: str


@dataclass(frozen=True, slots=True)
class _BatchResult:
    proposals: tuple[_BatchProposal, ...]
    errors: tuple[str, ...] = ()
    cancelled: bool = False


def _source_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _parse_page_snapshot(path: Path) -> tuple[PageDocument, str]:
    """Parse a disk snapshot whose bytes remained stable throughout parsing."""
    for _attempt in range(3):
        before = _source_digest(path)
        document = parse_page(path)
        after = _source_digest(path)
        if before == after:
            return document, after
    raise RuntimeError(f"{path.name} changed repeatedly while it was being read")


class EditorController(QObject):
    """Own project state, background jobs, saving, and correction decisions."""

    def __init__(self, window: MainWindow) -> None:
        super().__init__(window)
        self.window = window
        self.session = EditorSession()
        self.workflow = AutoCorrectionWorkflow()
        self.thread_pool = QThreadPool.globalInstance()
        self.project_paths: ProjectPaths | None = None
        self.ground_truth: GroundTruthBook | None = None
        self.documents: dict[Path, PageDocument] = {}
        self.runs: dict[Path, PageAutoCorrectionRun] = {}
        self._task: _CorrectionTask | None = None
        self._connect()

    def _connect(self) -> None:
        window = self.window
        window.openProjectRequested.connect(self.open_project)
        window.pageRequested.connect(self.open_page)
        window.saveRequested.connect(self.save)
        window.autoCorrectPageRequested.connect(self.auto_correct_page)
        window.autoCorrectBatchRequested.connect(self.auto_correct_batch)
        window.cancelCorrectionRequested.connect(self.cancel_correction)
        window.keepCorrectionRequested.connect(self.keep_line)
        window.rejectCorrectionRequested.connect(self.reject_line)
        window.keepPageCorrectionsRequested.connect(self.keep_page)
        window.rejectPageCorrectionsRequested.connect(self.reject_page)
        window.normalize_action.toggled.connect(self._nfc_toggled)

    @Slot(object)
    def open_project(self, paths: ProjectPaths) -> None:
        try:
            ground_truth = (
                self.workflow.load_ground_truth(paths.ground_truth_path)
                if paths.ground_truth_path is not None
                else None
            )
            project = self.session.open_project(
                paths.image_directory,
                paths.xml_directory,
                paths.audit_directory,
            )
        except Exception as error:
            self._error("Could not open project", str(error))
            return
        self.project_paths = paths
        self.ground_truth = ground_truth
        self.session.normalize_nfc = paths.normalize_nfc
        self.window.normalize_action.setChecked(paths.normalize_nfc)
        self.documents.clear()
        self.runs.clear()
        if self.session.document is not None:
            self.documents[self.session.document.source_path] = self.session.document
        self.window.set_pages(project.pairs)
        diagnostics = len(project.diagnostics)
        self.window.statusBar().showMessage(
            f"Opened {len(project.pairs)} page pair(s) · {diagnostics} project warning(s)",
            6000,
        )

    @Slot(object)
    def open_page(self, pair: PagePair) -> None:
        if self.session.project is None:
            return
        current = self.session.document
        if current is not None and current.is_dirty and current.source_path != pair.xml_path:
            # The MainWindow only emits this signal after its Save/Discard/Cancel
            # decision. A remaining dirty model therefore means Discard.
            self.documents.pop(current.source_path, None)
            self.runs.pop(current.source_path, None)
        try:
            index = next(
                index
                for index, candidate in enumerate(self.session.project.pairs)
                if candidate.xml_path == pair.xml_path
            )
            document = self.documents.get(pair.xml_path)
            if document is None:
                document = parse_page(pair.xml_path)
                document.image_path = pair.image_path
                self.documents[pair.xml_path] = document
            self.session.current_index = index
            self.session.document = document
            self.session.history = DocumentHistory(document)
            self._display(document, pair)
        except Exception as error:
            self._error("Could not open PAGE document", str(error))

    def _display(self, document: PageDocument, pair: PagePair) -> None:
        self.window.load_page(
            pair.image_path,
            document.active_lines,
            page_payload=pair,
            page_size=(document.image_width, document.image_height),
        )
        self._show_validation(document)
        run = self.runs.get(document.source_path)
        self.window.set_correction_review(run)
        if run is not None and document.is_dirty:
            self._push_run_command(run)

    @Slot()
    def save(self) -> None:
        if self.session.document is None:
            return
        try:
            result = self.session.save()
        except ValidationFailed as error:
            self._show_validation_report(error.report)
            self._error(
                "PAGE validation failed",
                "The source XML was not changed. Resolve the blocking validation errors first.",
            )
            return
        except SaveError as error:
            self._error("Could not save PAGE XML", str(error))
            return
        self.window.mark_saved()
        self.runs.pop(self.session.document.source_path, None)
        for line in self.session.document.lines:
            line.proposal_id = None
            line.proposal_state = ""
            line.diff_text = ""
            line.pre_correction_text = None
            line.correction_status = ""
        self.window.set_correction_review(None)
        self._refresh_document()
        self._show_validation_report(result.validation)
        status = f"Saved {result.source_path.name}; backup: {result.backup_path}"
        if result.durability_warning is not None:
            status = f"{status} · Warning: {result.durability_warning}"
        self.window.statusBar().showMessage(status, 7000)

    @Slot()
    def auto_correct_page(self) -> None:
        document = self.session.document
        if document is None or not self._require_ground_truth() or self._task is not None:
            return
        if self._is_page_dirty():
            self._error(
                "Save or discard current changes",
                "Page auto-correct needs a saved PAGE document so the audit original "
                "matches the in-memory state. Save or discard first.",
            )
            return
        snapshot = deepcopy(document)
        book = self.ground_truth
        assert book is not None

        def operation(
            token: CancellationToken,
            progress: Callable[[int, str], None],
        ) -> PageCorrectionProposal:
            progress(10, "Preparing current page")
            proposal = self.workflow.propose(snapshot, book, cancel_token=token)
            progress(100, "Correction proposal ready")
            return proposal

        self._start_task(operation, self._apply_page_proposal)

    @Slot()
    def auto_correct_batch(self) -> None:
        project = self.session.project
        if project is None or not self._require_ground_truth() or self._task is not None:
            return
        if self._is_page_dirty():
            self._error(
                "Save or discard current changes",
                "Folder correction starts from the XML files on disk. Save or discard the "
                "current page first so no in-memory edit can be replaced.",
            )
            return
        book = self.ground_truth
        assert book is not None
        pairs = tuple(project.pairs)

        def operation(
            token: CancellationToken,
            progress: Callable[[int, str], None],
        ) -> _BatchResult:
            results: list[_BatchProposal] = []
            errors: list[str] = []
            count = max(1, len(pairs))
            cancelled = False
            for index, pair in enumerate(pairs):
                if token.cancelled:
                    cancelled = True
                    break
                progress(round(index * 100 / count), f"Correcting {pair.xml_path.name}")
                try:
                    document, source_digest = _parse_page_snapshot(pair.xml_path)
                    document.image_path = pair.image_path
                    proposal = self.workflow.propose(document, book, cancel_token=token)
                    results.append(
                        _BatchProposal(pair, document, proposal, source_digest)
                    )
                except Exception as error:
                    if token.cancelled:
                        cancelled = True
                        break
                    errors.append(f"{pair.xml_path.name}: {type(error).__name__}: {error}")
            progress(100, "Folder correction proposals ready")
            return _BatchResult(tuple(results), tuple(errors), cancelled=cancelled)

        self._start_task(operation, self._apply_batch_proposals)

    def _start_task(
        self,
        operation: Callable[..., object],
        completed: Callable[[Any], None],
    ) -> None:
        task = _CorrectionTask(operation)
        self._task = task
        task.signals.progress.connect(self.window.set_correction_progress)
        task.signals.failed.connect(self._correction_failed)
        task.signals.completed.connect(completed)
        task.signals.completed.connect(lambda _result: self._finish_task())
        self.window.set_correction_progress(0, "Starting automatic correction")
        self.thread_pool.start(task)

    @Slot()
    def cancel_correction(self) -> None:
        if self._task is not None:
            self._task.token.cancel()
            self.window.set_correction_progress(0, "Cancelling…")

    def _apply_page_proposal(self, proposal: PageCorrectionProposal) -> None:
        if self._task_cancelled():
            return
        document = self.session.document
        if document is None or self.project_paths is None:
            return
        if self._is_page_dirty():
            self._error(
                "Save or discard current changes",
                "The page changed while correction was running. The proposal was not applied.",
            )
            return
        try:
            run = self.workflow.apply(
                document,
                proposal,
                self.project_paths.audit_directory,
                normalize_nfc=self.session.normalize_nfc,
            )
        except Exception as error:
            self._error("Could not apply correction", str(error))
            return
        self.runs[document.source_path] = run
        self._push_run_command(run)
        self.window.set_correction_review(run)
        self.window.statusBar().showMessage(
            f"Correction applied in memory · audit: {run.audit.run_directory}", 8000
        )

    def _apply_batch_proposals(self, result_set: _BatchResult) -> None:
        if self._task_cancelled() or result_set.cancelled:
            self.window.statusBar().showMessage("Automatic correction cancelled", 5000)
            return
        if self.project_paths is None:
            return
        applied = 0
        failures = list(result_set.errors)
        current_path = (
            self.session.document.source_path if self.session.document is not None else None
        )
        live = self.session.document
        current_skipped = False
        for result in result_set.proposals:
            cached = self.documents.get(result.pair.xml_path)
            try:
                source_changed = (
                    _source_digest(result.pair.xml_path) != result.source_digest
                )
            except OSError as error:
                failures.append(
                    f"{result.pair.xml_path.name}: skipped; source could not be checked: {error}"
                )
                continue
            if source_changed:
                if result.pair.xml_path == current_path:
                    current_skipped = True
                failures.append(
                    f"{result.pair.xml_path.name}: skipped; source XML changed while correction ran"
                )
                continue
            if (
                live is not None
                and live.source_path == result.pair.xml_path
                and (
                    live.is_dirty
                    or not self.window.undo_stack.isClean()
                    or cached is not live
                    or self._run_has_actionable_state(result.pair.xml_path)
                )
            ):
                current_skipped = True
                failures.append(
                    f"{result.pair.xml_path.name}: skipped; live page has unsaved edits"
                )
                continue
            if cached is not None and cached is not live and (
                cached.is_dirty or self._run_has_actionable_state(result.pair.xml_path)
            ):
                failures.append(
                    f"{result.pair.xml_path.name}: skipped because cached edits would be replaced"
                )
                continue
            try:
                run = self.workflow.apply(
                    result.document,
                    result.proposal,
                    self.project_paths.audit_directory,
                    normalize_nfc=self.session.normalize_nfc,
                )
            except Exception as error:
                failures.append(f"{result.pair.xml_path.name}: {error}")
                continue
            self.documents[result.pair.xml_path] = result.document
            self.runs[result.pair.xml_path] = run
            applied += 1
        if (
            current_path is not None
            and current_path in self.documents
            and not current_skipped
        ):
            document = self.documents[current_path]
            self.session.document = document
            pair = next(
                pair
                for pair in self.session.project.pairs  # type: ignore[union-attr]
                if pair.xml_path == current_path
            )
            self._display(document, pair)
        message = f"Automatically applied correction to {applied} page(s) in memory"
        if failures:
            message += f"; {len(failures)} skipped or failed"
            self.window.set_validation(message, failures)
        self.window.statusBar().showMessage(message, 8000)

    def _push_run_command(self, run: PageAutoCorrectionRun) -> None:
        affected_ids = {
            snapshot.line_id
            for application in run.applications
            if application.proposal.actionable
            for snapshot in application.before
        }
        if not affected_ids:
            self._refresh_document()
            return
        before_by_id = {
            snapshot.line_id: snapshot
            for application in run.applications
            if application.proposal.actionable
            for snapshot in application.before
        }
        before = tuple(before_by_id[line_id] for line_id in sorted(affected_ids))
        after = tuple(
            DocumentLineState.capture(run.document.line_by_id(line_id))
            for line_id in sorted(affected_ids)
        )
        self.window.undo_stack.push(
            _DocumentStateCommand(run.document, before, after, self._refresh_document)
        )

    @Slot(str)
    def keep_line(self, line_id: str) -> None:
        run = self._current_run()
        if run is None:
            return
        try:
            application = run.application_for_line(line_id)
        except KeyError:
            return
        if not application.proposal.actionable or application.decision not in {
            ReviewDecision.PENDING,
            ReviewDecision.APPLIED,
        }:
            return
        self.window.undo_stack.push(
            _ReviewDecisionCommand(
                run,
                "keep",
                (line_id,),
                lambda: self._refresh_document(line_id),
                "Keep correction",
            )
        )

    @Slot(str)
    def reject_line(self, line_id: str) -> None:
        run = self._current_run()
        if run is None:
            return
        try:
            application = run.application_for_line(line_id)
        except KeyError:
            return
        if not application.proposal.actionable or application.decision not in {
            ReviewDecision.PENDING,
            ReviewDecision.APPLIED,
            ReviewDecision.KEPT,
        }:
            return
        self.window.undo_stack.push(
            _ReviewDecisionCommand(
                run,
                "reject",
                (line_id,),
                lambda: self._refresh_document(line_id),
                "Reject correction",
            )
        )
        self._sync_clean_state()

    @Slot()
    def keep_page(self) -> None:
        run = self._current_run()
        if run is None:
            return
        line_ids = tuple(
            application.proposal.line_ids[0]
            for application in run.applications
            if application.proposal.line_ids
            and application.proposal.actionable
            and application.decision
            in {ReviewDecision.PENDING, ReviewDecision.APPLIED}
        )
        if not line_ids:
            return
        self.window.undo_stack.push(
            _ReviewDecisionCommand(
                run, "keep", line_ids, self._refresh_document, "Keep page corrections"
            )
        )

    @Slot()
    def reject_page(self) -> None:
        run = self._current_run()
        if run is None:
            return
        line_ids = tuple(
            application.proposal.line_ids[0]
            for application in run.applications
            if application.proposal.line_ids
            and application.proposal.actionable
            and application.decision
            in {
                ReviewDecision.PENDING,
                ReviewDecision.APPLIED,
                ReviewDecision.KEPT,
            }
        )
        if not line_ids:
            return
        self.window.undo_stack.push(
            _ReviewDecisionCommand(
                run, "reject", line_ids, self._refresh_document, "Reject page corrections"
            )
        )
        self._sync_clean_state()

    def _current_run(self) -> PageAutoCorrectionRun | None:
        document = self.session.document
        return self.runs.get(document.source_path) if document is not None else None

    def _task_cancelled(self) -> bool:
        return self._task is not None and self._task.token.cancelled

    def _is_page_dirty(self) -> bool:
        document = self.session.document
        if document is None:
            return False
        if document.is_dirty or not self.window.undo_stack.isClean():
            return True
        return self._run_has_actionable_state(document.source_path)

    def _run_has_actionable_state(self, source_path: Path) -> bool:
        run = self.runs.get(source_path)
        if run is None:
            return False
        return any(
            application.decision
            in {ReviewDecision.PENDING, ReviewDecision.APPLIED, ReviewDecision.KEPT}
            and application.proposal.actionable
            for application in run.applications
        )

    @Slot(bool)
    def _nfc_toggled(self, checked: bool) -> None:
        self.session.normalize_nfc = checked

    def _refresh_document(self, selected_line_id: str | None = None) -> None:
        document = self.session.document
        if document is None:
            return
        self.window.refresh_lines(document.active_lines, selected_line_id=selected_line_id)
        self.window.set_correction_review(self.runs.get(document.source_path))

    def _sync_clean_state(self) -> None:
        document = self.session.document
        if document is not None and not document.is_dirty:
            self.window.undo_stack.setClean()

    def _require_ground_truth(self) -> bool:
        if self.ground_truth is not None:
            return True
        self._error(
            "Ground truth required",
            "Open the project again and choose its folio-delimited .docx file.",
        )
        return False

    def _show_validation(self, document: PageDocument) -> None:
        if document.validation_report is not None:
            self._show_validation_report(document.validation_report)

    def _show_validation_report(self, report: Any) -> None:
        strict = "valid" if report.strict_valid else "has vendor/schema differences"
        core = "valid" if report.core_valid else "invalid"
        summary = f"Strict PAGE: {strict} · editable PAGE core: {core}"
        messages = [
            f"{issue.severity.value}: {issue.message}"
            for issue in report.issues
        ]
        messages.extend(f"strict schema: {message}" for message in report.strict_schema_errors)
        self.window.set_validation(summary, messages)

    @Slot(str)
    def _correction_failed(self, message: str) -> None:
        if "CorrectionCancelled" in message:
            self.window.statusBar().showMessage("Automatic correction cancelled", 5000)
        else:
            self._error("Automatic correction failed", message)
        self._finish_task()

    def _finish_task(self) -> None:
        self._task = None
        self.window.set_correction_progress(None, "")

    def _error(self, title: str, message: str) -> None:
        QMessageBox.critical(self.window, title, message)


__all__ = ["EditorController"]

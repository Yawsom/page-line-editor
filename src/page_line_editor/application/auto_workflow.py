"""Qt-free automatic-correction orchestration and review state."""

from __future__ import annotations

import json
import shutil
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from uuid import uuid4

from page_line_editor.correction import (
    CancellationToken,
    CorrectionLine,
    CorrectionSettings,
    LineCorrectionProposal,
    LineState,
    PageCorrectionInput,
    PageCorrectionProposal,
    propose_page,
)
from page_line_editor.domain.geometry import Point, Polygon, Polyline
from page_line_editor.domain.page import PageDocument, TextLine
from page_line_editor.reports import write_html_report, write_json_report

from .ground_truth import GroundTruthBook, parse_ground_truth_docx


class AutoCorrectionWorkflowError(RuntimeError):
    pass


class StaleCorrectionProposal(AutoCorrectionWorkflowError):
    """The live page changed after its proposal snapshot was produced."""


class ReviewDecision(StrEnum):
    APPLIED = "applied"
    PENDING = "pending"
    KEPT = "kept"
    REJECTED = "rejected"
    REPORT_ONLY = "report_only"


@dataclass(frozen=True, slots=True)
class DocumentLineState:
    """Exact state of every line field changed by this workflow."""

    line_id: str
    text: str
    polygon: Polygon
    baseline: Polyline | None
    deleted: bool
    proposal_id: str | None
    proposal_state: str
    diff_text: str
    pre_correction_text: str | None
    correction_status: str

    @classmethod
    def capture(cls, line: TextLine) -> DocumentLineState:
        return cls(
            line_id=line.id,
            text=line.text,
            polygon=line.polygon,
            baseline=line.baseline,
            deleted=line.deleted,
            proposal_id=line.proposal_id,
            proposal_state=line.proposal_state,
            diff_text=line.diff_text,
            pre_correction_text=line.pre_correction_text,
            correction_status=line.correction_status,
        )

    def restore(self, line: TextLine) -> None:
        line.text = self.text
        line.polygon = self.polygon
        line.baseline = self.baseline
        line.deleted = self.deleted
        line.proposal_id = self.proposal_id
        line.proposal_state = self.proposal_state
        line.diff_text = self.diff_text
        line.pre_correction_text = self.pre_correction_text
        line.correction_status = self.correction_status


@dataclass(frozen=True, slots=True)
class AutoAuditPaths:
    run_directory: Path
    original_xml: Path
    json_report: Path
    html_index: Path
    manifest: Path


@dataclass(slots=True)
class AppliedProposal:
    proposal: LineCorrectionProposal
    before: tuple[DocumentLineState, ...]
    decision: ReviewDecision


def _point(value: tuple[int, int]) -> Point:
    return Point(value[0], value[1])


def _polygon(values: tuple[tuple[int, int], ...]) -> Polygon:
    return Polygon(tuple(_point(value) for value in values))


def _baseline(values: tuple[tuple[int, int], ...]) -> Polyline | None:
    return Polyline(tuple(_point(value) for value in values)) if values else None


def _correction_input(document: PageDocument) -> PageCorrectionInput:
    """Snapshot active domain lines without exposing the live document."""

    lines = tuple(
        CorrectionLine(
            line_id=line.id,
            text=line.text,
            polygon=tuple((point.x, point.y) for point in line.polygon.points),
            baseline=(
                tuple((point.x, point.y) for point in line.baseline.points)
                if line.baseline is not None
                else ()
            ),
            source_index=line.source_order,
            region_id=line.region_id,
        )
        for line in document.active_lines
    )
    return PageCorrectionInput(
        xml_filename=document.source_path.name,
        lines=lines,
        folio=Path(document.image_filename or document.source_path.name).stem,
        image_filename=document.image_filename,
    )


def _current_core(line: TextLine) -> tuple[object, ...]:
    return (
        line.text,
        tuple((point.x, point.y) for point in line.polygon.points),
        tuple((point.x, point.y) for point in line.baseline.points) if line.baseline else (),
        line.deleted,
    )


def _proposal_core(state: LineState) -> tuple[object, ...]:
    return (
        state.text,
        state.polygon,
        state.baseline,
        state.deleted,
    )


def _diff_label(proposal: LineCorrectionProposal) -> str:
    if proposal.after_text is None:
        return f"{proposal.status.value}: {proposal.before_text or '—'}"
    return f"{proposal.before_text or '—'} → {proposal.after_text or '—'}"


class PageAutoCorrectionRun:
    """An automatically applied page result with controller-friendly decisions."""

    def __init__(
        self,
        document: PageDocument,
        proposal: PageCorrectionProposal,
        applications: tuple[AppliedProposal, ...],
        audit: AutoAuditPaths,
    ) -> None:
        self.document = document
        self.proposal = proposal
        self.applications = applications
        self.audit = audit
        self._by_proposal_id = {
            item.proposal.proposal_id: item for item in applications
        }
        self._by_line_id = {
            line_id: item
            for item in applications
            for line_id in item.proposal.line_ids
        }
        self._write_manifest()

    def application_for_line(self, line_id: str) -> AppliedProposal:
        try:
            return self._by_line_id[line_id]
        except KeyError as exc:
            raise KeyError(f"Line {line_id!r} has no correction proposal") from exc

    def keep_line(self, line_id: str) -> AppliedProposal:
        application = self.application_for_line(line_id)
        if application.decision is ReviewDecision.KEPT:
            return application
        if application.decision in {ReviewDecision.APPLIED, ReviewDecision.PENDING}:
            if application.decision is ReviewDecision.PENDING:
                for state in application.proposal.after:
                    line = self.document.line_by_id(state.line_id)
                    line.text = state.text
                    line.polygon = _polygon(state.polygon)
                    line.baseline = _baseline(state.baseline)
                    line.deleted = state.deleted
                    line.correction_status = (
                        "REMOVED"
                        if application.proposal.status.value == "EXTRA" and state.deleted
                        else application.proposal.status.value
                    )
            application.decision = ReviewDecision.KEPT
            for affected_id in application.proposal.line_ids:
                line = self.document.line_by_id(affected_id)
                line.proposal_state = "accepted"
            self.document.revision += 1
            self._write_manifest()
        return application

    def reject_line(self, line_id: str) -> AppliedProposal:
        application = self.application_for_line(line_id)
        if application.decision is ReviewDecision.REJECTED:
            return application
        if application.decision is ReviewDecision.REPORT_ONLY:
            return application
        for snapshot in application.before:
            snapshot.restore(self.document.line_by_id(snapshot.line_id))
        application.decision = ReviewDecision.REJECTED
        self.document.revision += 1
        self._write_manifest()
        return application

    def keep_page(self) -> None:
        for application in self.applications:
            if application.proposal.line_ids:
                self.keep_line(application.proposal.line_ids[0])

    def reject_page(self) -> None:
        for application in self.applications:
            if application.proposal.line_ids:
                self.reject_line(application.proposal.line_ids[0])

    @property
    def decisions(self) -> dict[str, ReviewDecision]:
        return {
            application.proposal.proposal_id: application.decision
            for application in self.applications
        }

    def _write_manifest(self) -> None:
        payload = {
            "schema_version": 1,
            "source_xml": str(self.document.source_path),
            "original_xml": str(self.audit.original_xml),
            "records": {
                item.proposal.record_key: {
                    "proposal_id": item.proposal.proposal_id,
                    "line_ids": list(item.proposal.line_ids),
                    "status": item.proposal.status.value,
                    "decision": item.decision.value,
                }
                for item in self.applications
            },
        }
        temporary = self.audit.manifest.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temporary.replace(self.audit.manifest)


class AutoCorrectionWorkflow:
    """Prepare on a worker thread, then apply on the GUI thread without Qt."""

    def load_ground_truth(self, path: str | Path) -> GroundTruthBook:
        return parse_ground_truth_docx(path)

    def propose(
        self,
        document: PageDocument,
        ground_truth: GroundTruthBook | Iterable[object],
        settings: CorrectionSettings | None = None,
        cancel_token: CancellationToken | None = None,
    ) -> PageCorrectionProposal:
        lines = (
            ground_truth.lines_for_document(document)
            if isinstance(ground_truth, GroundTruthBook)
            else ground_truth
        )
        return propose_page(_correction_input(document), lines, settings, cancel_token)

    def apply(
        self,
        document: PageDocument,
        proposal: PageCorrectionProposal,
        audit_root: str | Path,
    ) -> PageAutoCorrectionRun:
        """Audit the source, then automatically apply all actionable proposals."""

        if Path(proposal.xml_filename).name != document.source_path.name:
            raise StaleCorrectionProposal(
                f"Proposal for {proposal.xml_filename} cannot apply to {document.source_path.name}"
            )

        # Prepare and validate every change before either auditing or mutating.
        prepared: dict[str, tuple[str, Polygon, Polyline | None, bool]] = {}
        snapshots: dict[str, DocumentLineState] = {}
        for item in proposal.proposals:
            for state in item.before:
                line = document.line_by_id(state.line_id)
                if _current_core(line) != _proposal_core(state):
                    raise StaleCorrectionProposal(
                        f"Line {state.line_id!r} changed after correction was proposed"
                    )
                snapshots.setdefault(state.line_id, DocumentLineState.capture(line))
            for state in item.after:
                prepared[state.line_id] = (
                    state.text,
                    _polygon(state.polygon),
                    _baseline(state.baseline),
                    state.deleted,
                )

        audit = self._create_audit(document, proposal, Path(audit_root))
        applications: list[AppliedProposal] = []
        for item in proposal.proposals:
            before = tuple(snapshots[state.line_id] for state in item.before)
            decision = ReviewDecision.REPORT_ONLY
            if item.actionable and item.automatically_applied:
                for state in item.after:
                    text, polygon, baseline, deleted = prepared[state.line_id]
                    line = document.line_by_id(state.line_id)
                    line.text = text
                    line.polygon = polygon
                    line.baseline = baseline
                    line.deleted = deleted
                    line.proposal_id = item.proposal_id
                    line.proposal_state = "applied"
                    line.diff_text = _diff_label(item)
                    line.pre_correction_text = snapshots[state.line_id].text
                    line.correction_status = (
                        "REMOVED"
                        if item.status.value == "EXTRA" and state.deleted
                        else item.status.value
                    )
                decision = ReviewDecision.APPLIED
            elif item.actionable:
                # An uncertain EXTRA is a pending deletion: keep its geometry
                # visible until the reviewer accepts it, while retaining the
                # complete proposed tombstone for a reversible decision.
                for line_id in item.line_ids:
                    line = document.line_by_id(line_id)
                    line.proposal_id = item.proposal_id
                    line.proposal_state = "pending"
                    line.diff_text = _diff_label(item)
                    line.pre_correction_text = snapshots[line_id].text
                    line.correction_status = item.status.value
                decision = ReviewDecision.PENDING
            else:
                # Keep report-only matches visible in the in-app comparison
                # without making the PAGE document dirty.
                for line_id in item.line_ids:
                    line = document.line_by_id(line_id)
                    line.proposal_id = item.proposal_id
                    line.proposal_state = "matched"
                    line.diff_text = _diff_label(item)
                    line.pre_correction_text = snapshots[line_id].text
                    line.correction_status = item.status.value
            applications.append(AppliedProposal(item, before, decision))
        if any(item.decision is ReviewDecision.APPLIED for item in applications):
            document.revision += 1
        return PageAutoCorrectionRun(document, proposal, tuple(applications), audit)

    def run_page(
        self,
        document: PageDocument,
        ground_truth: GroundTruthBook | Iterable[object],
        audit_root: str | Path,
        settings: CorrectionSettings | None = None,
        cancel_token: CancellationToken | None = None,
    ) -> PageAutoCorrectionRun:
        proposal = self.propose(document, ground_truth, settings, cancel_token)
        return self.apply(document, proposal, audit_root)

    def _create_audit(
        self,
        document: PageDocument,
        proposal: PageCorrectionProposal,
        audit_root: Path,
    ) -> AutoAuditPaths:
        source = document.source_path
        if not source.is_file():
            raise AutoCorrectionWorkflowError(f"Source XML does not exist: {source}")
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
        run_directory = audit_root / "auto" / f"{stamp}-{uuid4().hex[:8]}"
        originals = run_directory / "originals"
        reports = run_directory / "reports"
        originals.mkdir(parents=True, exist_ok=False)
        original_xml = originals / source.name
        shutil.copyfile(source, original_xml)
        json_report = write_json_report(proposal, reports / "alignment.json")
        html_index = write_html_report(proposal, reports)
        return AutoAuditPaths(
            run_directory=run_directory,
            original_xml=original_xml,
            json_report=json_report,
            html_index=html_index,
            manifest=run_directory / "manifest.json",
        )

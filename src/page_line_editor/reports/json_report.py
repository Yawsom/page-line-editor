"""Versioned JSON audit reports for correction proposals."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from page_line_editor.correction.models import (
    STATUSES,
    FolderCorrectionProposal,
    LineCorrectionProposal,
    PageCorrectionProposal,
)

SCHEMA_VERSION = 1


def _state_dict(state: Any) -> dict[str, Any]:
    return {
        "line_id": state.line_id,
        "text": state.text,
        "polygon": [list(point) for point in state.polygon],
        "baseline": [list(point) for point in state.baseline],
        "region_id": state.region_id,
        "deleted": state.deleted,
    }


def proposal_to_dict(proposal: LineCorrectionProposal) -> dict[str, Any]:
    """Return both the legacy alignment keys and reversible proposal data."""

    bbox = asdict(proposal.bbox) if proposal.bbox is not None else None
    return {
        "proposal_id": proposal.proposal_id,
        "record_key": proposal.record_key,
        "status": proposal.status.value,
        # Legacy keys retained for downstream report consumers.
        "xml_ids": list(proposal.line_ids),
        "xml_text": proposal.before_text,
        "gt_index": proposal.gt_indexes[0] if proposal.gt_indexes else None,
        "gt_text": proposal.after_text,
        "ratio": None if proposal.ratio is None else round(proposal.ratio, 4),
        "baseline_y": (
            None if proposal.baseline_y is None else round(proposal.baseline_y, 1)
        ),
        "bbox": bbox,
        "flags": list(proposal.flags),
        "char_spans": [
            {"tag": diff.tag, "xml": diff.before, "gt": diff.after}
            for diff in proposal.char_diffs
        ],
        # New fields make automatic application and rejection auditable.
        "gt_indexes": list(proposal.gt_indexes),
        "before": [_state_dict(state) for state in proposal.before],
        "after": [_state_dict(state) for state in proposal.after],
        "actionable": proposal.actionable,
        "automatically_applied": proposal.automatically_applied,
    }


def _counts(page: PageCorrectionProposal) -> dict[str, int]:
    counts = {status: 0 for status in STATUSES}
    for proposal in page.proposals:
        counts[proposal.status.value] += 1
    return counts


def _mean_ratio(page: PageCorrectionProposal) -> float | None:
    values = [proposal.ratio for proposal in page.proposals if proposal.ratio is not None]
    return sum(values) / len(values) if values else None


def page_to_dict(page: PageCorrectionProposal) -> dict[str, Any]:
    alignments = [proposal_to_dict(proposal) for proposal in page.proposals]
    records = {
        proposal.record_key: proposal_to_dict(proposal)
        for proposal in page.proposals
        if proposal.line_ids
    }
    unmatched = [
        proposal_to_dict(proposal) for proposal in page.proposals if not proposal.line_ids
    ]
    return {
        "folio": page.folio or Path(page.xml_filename).stem,
        "xml_path": page.xml_filename,
        "xml_filename": page.xml_filename,
        "image_filename": page.image_filename,
        "gt_line_count": page.ground_truth_line_count,
        "xml_line_count": page.source_line_count,
        "counts": _counts(page),
        "mean_ratio": _mean_ratio(page),
        "alignments": alignments,
        "records": records,
        "unmatched_ground_truth": unmatched,
        "note": "",
    }


def report_payload(
    result: PageCorrectionProposal | FolderCorrectionProposal,
) -> dict[str, Any]:
    folder = (
        result
        if isinstance(result, FolderCorrectionProposal)
        else FolderCorrectionProposal((result,))
    )
    pages = [page_to_dict(page) for page in folder.pages]
    records = {
        key: proposal_to_dict(proposal) for key, proposal in folder.records.items()
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "pages": pages,
        "records": records,
        "cancelled": folder.cancelled,
        "errors": dict(folder.errors),
        # Retain legacy top-level pairing keys.
        "gt_only_folios": [],
        "xml_only_folios": [],
    }


def write_json_report(
    result: PageCorrectionProposal | FolderCorrectionProposal, destination: Path
) -> Path:
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(report_payload(result), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return destination

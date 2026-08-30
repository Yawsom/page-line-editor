"""Side-effect-free automatic correction proposal service."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from .alignment import (
    AlignedLines,
    align_lines,
    apply_geometric_merges,
    connected_baselines,
    convex_hull,
)
from .cancellation import CancellationToken, CorrectionCancelled, NullCancellationToken
from .models import (
    CorrectionLine,
    CorrectionSettings,
    CorrectionStatus,
    FolderCorrectionProposal,
    LineCorrectionProposal,
    LineState,
    PageCorrectionInput,
    PageCorrectionProposal,
    coerce_ground_truth,
    coerce_page,
    record_key,
)


def _line_state(line: CorrectionLine, *, deleted: bool = False) -> LineState:
    return LineState(
        line_id=line.line_id,
        text=line.text,
        polygon=line.polygon,
        baseline=line.baseline,
        region_id=line.region_id,
        deleted=deleted,
    )


def _primary(lines: Sequence[CorrectionLine]) -> CorrectionLine:
    """Retain the legacy widest-line primary policy."""

    return max(lines, key=lambda line: (line.bbox.width, line.line_id))


def _proposal(
    page: PageCorrectionInput,
    alignment: AlignedLines,
    source_by_id: Mapping[str, CorrectionLine],
    settings: CorrectionSettings,
) -> LineCorrectionProposal:
    member_ids = tuple(
        line_id
        for line in alignment.lines
        for line_id in (line.merged_from or (line.line_id,))
    )
    members = tuple(source_by_id[line_id] for line_id in member_ids if line_id in source_by_id)
    gt_indexes = tuple(line.index for line in alignment.ground_truth)

    if not members:
        missing_id = f"__missing_gt_{gt_indexes[0] if gt_indexes else 'unknown'}"
        key = record_key(page.xml_filename, missing_id)
        return LineCorrectionProposal(
            proposal_id=key,
            record_key=key,
            xml_filename=page.xml_filename,
            status=alignment.status,
            line_ids=(),
            gt_indexes=gt_indexes,
            before=(),
            after=(),
            before_text=alignment.before_text,
            after_text=alignment.after_text,
            ratio=alignment.ratio,
            baseline_y=alignment.baseline_y,
            bbox=alignment.bbox,
            flags=alignment.flags,
            char_diffs=alignment.char_diffs,
            automatically_applied=False,
        )

    primary = _primary(members)
    ordered = (primary,) + tuple(line for line in members if line.line_id != primary.line_id)
    before = tuple(_line_state(line) for line in ordered)
    after: tuple[LineState, ...]
    automatically_applied: bool
    if alignment.status is CorrectionStatus.EXTRA:
        should_delete = settings.delete_all_extras or (
            settings.apply_noise_deletions and "noise" in alignment.flags
        )
        # Every EXTRA is a real deletion proposal. Confirmed noise may be
        # applied automatically; uncertain extras remain visible as pending
        # changes until the reviewer explicitly accepts them.
        after = tuple(_line_state(line, deleted=True) for line in ordered)
        automatically_applied = should_delete
    else:
        target_text = alignment.after_text if alignment.after_text is not None else primary.text
        if len(ordered) > 1:
            all_polygon_points = tuple(point for line in ordered for point in line.polygon)
            primary_after = LineState(
                line_id=primary.line_id,
                text=target_text,
                polygon=convex_hull(all_polygon_points),
                baseline=connected_baselines(ordered),
                region_id=primary.region_id,
            )
            after = (primary_after,) + tuple(
                _line_state(line, deleted=True) for line in ordered[1:]
            )
        else:
            after = (
                LineState(
                    line_id=primary.line_id,
                    text=target_text,
                    polygon=primary.polygon,
                    baseline=primary.baseline,
                    region_id=primary.region_id,
                ),
            )
        automatically_applied = before != after

    key = record_key(page.xml_filename, primary.line_id)
    return LineCorrectionProposal(
        proposal_id=key,
        record_key=key,
        xml_filename=page.xml_filename,
        status=alignment.status,
        line_ids=tuple(line.line_id for line in ordered),
        gt_indexes=gt_indexes,
        before=before,
        after=after,
        before_text=alignment.before_text,
        after_text=alignment.after_text,
        ratio=alignment.ratio,
        baseline_y=alignment.baseline_y,
        bbox=alignment.bbox,
        flags=alignment.flags,
        char_diffs=alignment.char_diffs,
        automatically_applied=automatically_applied,
    )


def propose_page(
    document_snapshot: Any,
    ground_truth: Iterable[Any],
    settings: CorrectionSettings | None = None,
    cancel_token: CancellationToken | None = None,
) -> PageCorrectionProposal:
    """Create reversible proposals without mutating the input or writing files."""

    page = coerce_page(document_snapshot)
    gt_lines = coerce_ground_truth(ground_truth)
    options = settings or CorrectionSettings()
    token = cancel_token or NullCancellationToken()
    token.raise_if_cancelled()

    # PAGE parsing historically supplied visual order.  Sorting a copied tuple
    # preserves that behavior without touching the document or geometry points.
    source_lines = tuple(
        sorted(page.lines, key=lambda line: (line.baseline_y, line.bbox.x_min, line.source_index))
    )
    working = apply_geometric_merges(source_lines, [line.text for line in gt_lines], token)
    alignments = align_lines(working, gt_lines, token)
    source_by_id = {line.line_id: line for line in source_lines}
    proposals = tuple(
        _proposal(page, alignment, source_by_id, options) for alignment in alignments
    )
    token.raise_if_cancelled()
    return PageCorrectionProposal(
        xml_filename=page.xml_filename,
        proposals=proposals,
        folio=page.folio,
        image_filename=page.image_filename,
        source_line_count=len(page.lines),
        ground_truth_line_count=len(gt_lines),
    )


def propose_folder(
    page_jobs: Iterable[tuple[Any, Iterable[Any]]],
    settings: CorrectionSettings | None = None,
    cancel_token: CancellationToken | None = None,
) -> FolderCorrectionProposal:
    """Propose a batch, retaining completed pages when cancellation occurs."""

    token = cancel_token or NullCancellationToken()
    pages: list[PageCorrectionProposal] = []
    errors: dict[str, str] = {}
    cancelled = False
    for document, ground_truth in page_jobs:
        if token.cancelled:
            cancelled = True
            break
        try:
            pages.append(propose_page(document, ground_truth, settings, token))
        except CorrectionCancelled:
            cancelled = True
            break
        except Exception as error:  # a malformed page must not abort a folder run
            try:
                page = coerce_page(document)
                name = page.xml_filename
            except Exception:
                name = f"page-{len(pages) + len(errors)}"
            errors[name] = f"{type(error).__name__}: {error}"
    return FolderCorrectionProposal(tuple(pages), cancelled=cancelled, errors=errors)


def automatically_applied_states(
    page: PageCorrectionProposal,
    *,
    rejected_proposal_ids: Iterable[str] = (),
) -> Mapping[str, LineState]:
    """Materialise the in-memory state after automatic apply and rejection.

    This helper remains pure; the GUI maps the returned states to undo commands.
    A rejected proposal contributes its complete ``before`` state.
    """

    rejected = set(rejected_proposal_ids)
    states: dict[str, LineState] = {}
    for proposal in page.proposals:
        selected = (
            proposal.after
            if proposal.automatically_applied and proposal.proposal_id not in rejected
            else proposal.before
        )
        for state in selected:
            states[state.line_id] = state
    return states


def jobs_from_mapping(
    pages: Iterable[Any], ground_truth_by_filename: Mapping[str, Iterable[Any]]
) -> tuple[tuple[Any, Iterable[Any]], ...]:
    """Pair page objects with a filename/stem keyed ground-truth mapping."""

    jobs: list[tuple[Any, Iterable[Any]]] = []
    for value in pages:
        page = coerce_page(value)
        filename = Path(page.xml_filename).name
        truth = ground_truth_by_filename.get(filename)
        if truth is None:
            truth = ground_truth_by_filename.get(Path(filename).stem, ())
        jobs.append((value, truth))
    return tuple(jobs)


class CorrectionService:
    """Stateless facade convenient for dependency injection in the Qt layer."""

    propose = staticmethod(propose_page)
    propose_folder = staticmethod(propose_folder)
    automatically_applied_states = staticmethod(automatically_applied_states)


# Concise functional spelling matching the architecture document.
propose = propose_page

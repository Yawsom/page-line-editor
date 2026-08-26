"""Public correction-engine API."""

from .cancellation import CancellationToken, CorrectionCancelled, NullCancellationToken
from .models import (
    STATUSES,
    BoundingBox,
    CharDiff,
    CorrectionLine,
    CorrectionSettings,
    CorrectionStatus,
    FolderCorrectionProposal,
    GroundTruthLine,
    LineCorrectionProposal,
    LineState,
    PageCorrectionInput,
    PageCorrectionProposal,
    record_key,
)
from .normalization import normalize_for_display, normalize_for_match, similarity
from .service import (
    CorrectionService,
    automatically_applied_states,
    jobs_from_mapping,
    propose,
    propose_folder,
    propose_page,
)

__all__ = [
    "STATUSES",
    "BoundingBox",
    "CancellationToken",
    "CharDiff",
    "CorrectionCancelled",
    "CorrectionLine",
    "CorrectionSettings",
    "CorrectionService",
    "CorrectionStatus",
    "FolderCorrectionProposal",
    "GroundTruthLine",
    "LineCorrectionProposal",
    "LineState",
    "NullCancellationToken",
    "PageCorrectionInput",
    "PageCorrectionProposal",
    "automatically_applied_states",
    "jobs_from_mapping",
    "normalize_for_display",
    "normalize_for_match",
    "propose",
    "propose_folder",
    "propose_page",
    "record_key",
    "similarity",
]

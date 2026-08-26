"""Qt-independent application services."""

from .history_service import DocumentHistory, HistoryService
from .project_scanner import PagePair, PairingMethod, ProjectScanResult, scan_project
from .save_service import SaveResult, SaveService
from .session import EditorSession

__all__ = [
    "DocumentHistory",
    "EditorSession",
    "HistoryService",
    "PagePair",
    "PairingMethod",
    "ProjectScanResult",
    "SaveResult",
    "SaveService",
    "scan_project",
]

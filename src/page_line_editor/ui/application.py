"""Application entry point kept separate for tests and future packaging."""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtWidgets import QApplication

from .controller import EditorController
from .main_window import MainWindow


def create_application(argv: Sequence[str] | None = None) -> QApplication:
    """Create application."""
    existing = QApplication.instance()
    if isinstance(existing, QApplication):
        return existing
    if existing is not None:
        raise RuntimeError("A non-GUI QCoreApplication already exists")
    QCoreApplication.setOrganizationName("PAGE Line Editor")
    QCoreApplication.setApplicationName("PAGE Line Editor")
    QCoreApplication.setApplicationVersion("0.1.0")
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    return QApplication(list(argv or ()))


def run_application(argv: Sequence[str] | None = None) -> int:
    """Run application."""
    app = create_application(argv)
    window = MainWindow()
    # QObject parenting keeps the controller alive for the window lifetime.
    EditorController(window)
    window.show()
    return app.exec()

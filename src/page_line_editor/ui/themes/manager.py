"""Semantic palettes for System, Light, and Dark modes."""

from __future__ import annotations

from enum import StrEnum

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication


class Theme(StrEnum):
    SYSTEM = "System"
    LIGHT = "Light"
    DARK = "Dark"


_SYSTEM_PALETTE: QPalette | None = None


def _light_palette() -> QPalette:
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor("#f5f7fa"))
    palette.setColor(QPalette.ColorRole.WindowText, QColor("#172033"))
    palette.setColor(QPalette.ColorRole.Base, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#eef2f7"))
    palette.setColor(QPalette.ColorRole.Text, QColor("#172033"))
    palette.setColor(QPalette.ColorRole.Button, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor("#172033"))
    palette.setColor(QPalette.ColorRole.Highlight, QColor("#3478f6"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    return palette


def _dark_palette() -> QPalette:
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor("#161b24"))
    palette.setColor(QPalette.ColorRole.WindowText, QColor("#e9edf5"))
    palette.setColor(QPalette.ColorRole.Base, QColor("#10141b"))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#202734"))
    palette.setColor(QPalette.ColorRole.Text, QColor("#e9edf5"))
    palette.setColor(QPalette.ColorRole.Button, QColor("#242c3a"))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor("#e9edf5"))
    palette.setColor(QPalette.ColorRole.Highlight, QColor("#6ea8fe"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#10141b"))
    return palette


def apply_theme(app: QApplication, theme: Theme | str) -> Theme:
    global _SYSTEM_PALETTE
    selected = Theme(theme)
    if _SYSTEM_PALETTE is None:
        _SYSTEM_PALETTE = QPalette(app.palette())
    if selected is Theme.SYSTEM:
        app.setPalette(_SYSTEM_PALETTE)
        app.setStyleSheet("")
    else:
        app.setPalette(_dark_palette() if selected is Theme.DARK else _light_palette())
        app.setStyleSheet(
            "QToolBar { spacing: 4px; padding: 4px; }"
            "QToolBar#toolsToolbar { spacing: 3px; padding: 5px; }"
            "QToolBar#toolsToolbar QToolButton { padding: 7px; border-radius: 5px; }"
            "QToolBar#toolsToolbar QToolButton:checked { background: palette(highlight); }"
            "QToolButton:focus, QPushButton:focus, QComboBox:focus { "
            "border: 2px solid palette(highlight); }"
            "QTreeWidget:focus { border: 2px solid palette(highlight); }"
            "QPushButton { padding: 5px 10px; }"
        )
    return selected


def overlay_colors(theme: Theme | str) -> dict[str, QColor]:
    dark = Theme(theme) is Theme.DARK
    return {
        "polygon": QColor("#44b5ff" if dark else "#0067c5"),
        "baseline": QColor("#f6c344" if dark else "#9b6400"),
        "selected": QColor("#ff6aa9" if dark else "#d4145a"),
        "proposed": QColor("#c084fc" if dark else "#7e22ce"),
        "error": QColor("#ff6b6b" if dark else "#c62828"),
        "handle": QColor("#ffffff" if dark else "#172033"),
        "handle_fill": QColor("#3478f6"),
    }

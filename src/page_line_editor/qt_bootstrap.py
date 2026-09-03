"""Prepare Qt runtime paths before importing PySide6.

Some macOS Python environments under Documents acquire ``com.apple.provenance``
attributes after installation. Qt can then fail to enumerate its own plugin
directory: the Cocoa plugin may disappear at startup, or image decoder plugins
may disappear later and produce a blank page behind otherwise valid overlays.
"""

from __future__ import annotations

import os
import shutil
import stat
import sys
from importlib import metadata, util
from pathlib import Path


def _clear_hidden_flags(root: Path) -> None:
    """Qt skips macOS files carrying UF_HIDDEN, even when names are normal."""

    chflags = getattr(os, "chflags", None)
    if not callable(chflags):
        return
    for path in (root, *root.rglob("*")):
        flags = getattr(path.stat(), "st_flags", 0)
        if flags & stat.UF_HIDDEN:
            chflags(path, flags & ~stat.UF_HIDDEN)


def prepare_qt_plugins() -> Path | None:
    """Return and configure a stable macOS Qt plugin mirror when needed."""

    if sys.platform != "darwin" or getattr(sys, "frozen", False):
        return None
    if os.environ.get("QT_PLUGIN_PATH"):
        return Path(os.environ["QT_PLUGIN_PATH"])
    if os.environ.get("PAGE_LINE_EDITOR_DISABLE_QT_PLUGIN_MIRROR") == "1":
        return None

    specification = util.find_spec("PySide6")
    if specification is None or specification.origin is None:
        return None
    source = Path(specification.origin).resolve().parent / "Qt" / "plugins"
    if not (source / "platforms" / "libqcocoa.dylib").is_file():
        return None

    try:
        version = metadata.version("PySide6")
    except metadata.PackageNotFoundError:
        version = "unknown"
    # On macOS, TMPDIR normally points back into a provenance-managed
    # /var/folders tree. /private/tmp is the stable system temporary location
    # in which Qt can enumerate copied plugin bundles normally.
    temporary_root = Path("/private/tmp") if Path("/private/tmp").is_dir() else Path("/tmp")
    cache = temporary_root / "page-line-editor" / f"qt-plugins-{version}"
    marker = cache / ".complete"
    expected = cache / "platforms" / "libqcocoa.dylib"
    if not marker.is_file() or not expected.is_file():
        cache.mkdir(parents=True, exist_ok=True)

        def ignore_stale(_directory: str, names: list[str]) -> set[str]:
            """Exclude renamed plugin binaries left behind by a pip downgrade."""
            # A pip downgrade can leave renamed, incompatible plugin copies.
            return {name for name in names if name.endswith(" 2.dylib")}

        try:
            shutil.copytree(source, cache, dirs_exist_ok=True, ignore=ignore_stale)
            _clear_hidden_flags(cache)
            marker.write_text(str(source), encoding="utf-8")
        except OSError:
            # A writable environment can still be repaired in place when the
            # system temporary directory is unavailable.
            _clear_hidden_flags(source)
            os.environ["QT_PLUGIN_PATH"] = str(source)
            return source
    else:
        _clear_hidden_flags(cache)
    os.environ["QT_PLUGIN_PATH"] = str(cache)
    return cache


__all__ = ["prepare_qt_plugins"]

from __future__ import annotations

import sys


def main() -> int:
    """Run the PAGE Line Editor desktop application."""
    from page_line_editor.qt_bootstrap import prepare_qt_plugins

    prepare_qt_plugins()
    from page_line_editor.ui.application import run_application

    return run_application(sys.argv)


if __name__ == "__main__":
    raise SystemExit(main())

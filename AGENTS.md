# AGENTS.md

## Scope

These instructions apply to the entire repository. Add a nested `AGENTS.md` only
when a subtree needs genuinely different commands or constraints.

## Project Summary

PAGE Line Editor is an offline Python 3.11+ / PySide6 desktop application for
Arabic manuscript transcription and PAGE 2013 XML geometry editing. `lxml`
handles PAGE parsing and validation; `python-docx` supplies folio-delimited
ground truth. The runtime must remain offline and has no database.

`align_report.py` is the legacy CLI. New application behavior normally belongs
under `src/page_line_editor/`; preserve CLI compatibility when touching shared
alignment behavior.

## Setup and Run

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install ".[dev]"
python -m page_line_editor
```

If editable imports fail on macOS, run directly from the checkout:

```bash
PYTHONPATH=src python -m page_line_editor
```

## Required Checks

Run focused tests while iterating. Before handing off a code change, run:

```bash
python scripts/check_no_private_data.py
ruff check .
mypy src/page_line_editor
pytest
```

For UI tests, use the configured `pytest-qt` setup and offscreen Qt. Do not
weaken a failing safety, XML, or privacy check merely to make the suite pass.

## Architecture Boundaries

- `domain/`: Qt-free PAGE documents and geometry value objects.
- `pagexml/`: secure parsing, narrow XML mutation, bundled XSD, validation.
- `correction/`: pure normalization, alignment, and reversible proposals.
- `application/`: sessions, pairing, audit, undo history, and safe persistence.
- `ui/`: PySide6 views, controller, commands, canvas, adapters, and themes.

Keep `domain`, `pagexml`, and `correction` independent of PySide6. Route UI
actions through `EditorController` and application services rather than writing
files or running correction logic directly from widgets.

## PAGE XML and Data Safety

- Preserve the raw XML tree and mutate only dirty line fields.
- Preserve namespaces, document order, metadata, and unknown vendor extensions.
- Validate candidate XML before saving; create a backup before atomic replace.
- Auto-correction must write its audit copy before mutating the in-memory model.
- Keep uncertain `EXTRA` deletions pending until explicit reviewer acceptance.
- Keep corrections reversible until explicit Save; never silently discard boxes.
- Generate test XML, images, and DOCX fixtures only in temporary directories.
- Never commit manuscript XML, images, DOCX files, reports, backups, correction
  history, manifests, or other generated project data.
- Run `python scripts/check_no_private_data.py` before staging or committing.

## Code Conventions

- Use `from __future__ import annotations`, type hints, and `pathlib.Path`.
- Use `snake_case` for modules/functions and `PascalCase` for classes.
- Prefer `@dataclass(slots=True)`; freeze value objects that should be immutable.
- Raise focused domain/application exceptions with actionable messages.
- Keep proposal generation pure; filesystem mutation belongs in services.
- Use NFC normalization only where the existing workflow explicitly requests it.
- Tests live in `tests/test_*.py` and use `test_*` names.

## Change Guide

- Canvas/tool behavior: `ui/canvas/`, `ui/main_window.py`, `ui/controller.py`.
- Undo/review commands: `ui/commands/`, `application/history_service.py`.
- XML parsing/writing: `pagexml/parser.py`, `writer.py`, and validator tests.
- Alignment behavior: `correction/`, then `application/auto_workflow.py`.
- Project pairing: `application/project_scanner.py`.
- User-visible workflows or shortcuts: update `docs/user_guide.md` and tests.

## Code Review Rules

- Flag any path that can overwrite live PAGE XML without validation, an exact
  backup, and same-directory atomic replacement. Safe path: use `SaveService`.
- Flag XML rewrites that rebuild the whole document or drop untouched metadata,
  namespaces, order, Word content, or vendor extensions. Safe path: mutate a
  cloned raw tree through `pagexml/writer.py`.
- Flag automatic correction that mutates a document before its audit copy exists
  or deletes uncertain extras without a reviewer decision.
- Flag PySide6 imports in `domain/`, `pagexml/`, or `correction/`.
- Flag tests or commits containing real manuscript data or generated artefacts.
- Flag UI behavior changes that omit corresponding pytest-qt coverage and user
  guide updates when shortcuts or workflows change.

## Git Conventions

- Use focused `codex/<topic>` branches.
- Follow the recent Conventional Commit style (`feat:`, `fix:`, `test:`, `docs:`).
- Do not stage unrelated existing changes or ignored/generated data.

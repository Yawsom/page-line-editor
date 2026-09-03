# AGENTS.md — PAGE Line Editor

## Scope and operating model

These instructions apply to the whole repository. More-specific nested
`AGENTS.md` files may add rules for a subtree; do not create one unless that
subtree has genuinely different commands or constraints.

PAGE Line Editor is an offline Python 3.11+ / PySide6 desktop editor for Arabic
manuscript transcription and PAGE 2013 XML geometry. There is no database and
the runtime must not make network requests. `align_report.py` is the retained
legacy CLI; new application behavior belongs in `src/page_line_editor/` and
must preserve shared CLI compatibility.

Before a non-trivial change, read the relevant source, its nearest tests, and:

- [`README.md`](README.md) for setup, supported file types, and release scope.
- [`docs/user_guide.md`](docs/user_guide.md) for user-visible behavior.
- [`RELEASING.md`](RELEASING.md) before changing packaging, tags, or releases.

## Start and verify

Create an isolated environment once, then use its interpreter explicitly. This
also works when `python` is not available globally.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install ".[dev]"
.venv/bin/python -m page_line_editor
```

For an editable-import problem on macOS, run from the checkout:

```bash
PYTHONPATH=src .venv/bin/python -m page_line_editor
```

Run focused tests while iterating. Before handing off code, all commands below
must pass; do not weaken safety, XML, privacy, or UI checks to get green.

```bash
.venv/bin/python scripts/check_no_private_data.py
.venv/bin/python -m ruff check .
.venv/bin/python -m mypy src/page_line_editor
QT_QPA_PLATFORM=minimal .venv/bin/python -m pytest
```

CI runs the same checks on Python 3.11 and 3.13 across Linux, macOS, and
Windows. Linux installs `libegl1`; use Qt's `minimal` backend for widget tests.
If local Qt plugin loading fails, keep the failure visible and consult the
macOS setup note in the README rather than changing application code or CI.

## Repository map

| Location | Responsibility |
| --- | --- |
| `domain/` | Qt-free PAGE documents and geometry value objects. |
| `pagexml/` | Secure parsing, narrow writes, bundled XSD, validation. |
| `correction/` | Pure normalization, alignment, and reversible proposals. |
| `application/` | Sessions, pairing, audit history, save service, workflows. |
| `ui/` | PySide6 controller, views, canvas, commands, panels, themes. |
| `tests/` | Unit and pytest-qt regression coverage. |
| `scripts/` | Privacy and release metadata gates. |
| `.github/workflows/` | CI matrix and tag-driven GitHub Release packaging. |

Keep `domain`, `pagexml`, and `correction` independent of PySide6. Widgets do
not write files or run correction logic directly: route user actions through
`EditorController` and application services.

## Non-negotiable data and XML rules

- Preserve the raw XML tree; mutate only dirty fields through `pagexml/writer.py`.
- Preserve namespaces, sibling order, metadata, Word/Glyph content, and unknown
  vendor extensions. Never rebuild the document from the domain model.
- Save only through `SaveService`: validate candidate XML, make an exact backup,
  then atomically replace the source in the same directory.
- Write the auto-correction audit copy before mutating the live document.
- Keep uncertain `EXTRA` deletions pending and every correction reversible until
  explicit Save; never silently discard geometry or boxes.
- Generate fixtures only in test temporary directories.
- Keep real manuscripts, images, PAGE XML, DOCX ground truth, reports, backups,
  manifests, and audit history in ignored `local_data/`; never stage them.

## Implementation conventions

- Use `from __future__ import annotations`, complete type hints, and `pathlib.Path`.
- Use PEP 257 triple-double-quoted docstrings: summarize behavior imperatively;
  document meaningful side effects, failures, and restrictions without repeating types.
- Use `snake_case` for modules/functions and `PascalCase` for classes.
- Prefer `@dataclass(slots=True)`; freeze value objects where mutation is unsafe.
- Raise focused domain/application exceptions with actionable messages.
- Keep proposal generation pure; filesystem effects belong in application services.
- Apply NFC only where the selected workflow already requests it.
- Add or update tests in `tests/test_*.py` using `test_*` names.

## Change routing and definition of done

| If changing… | Start with… | Also update… |
| --- | --- | --- |
| Canvas tools, hit testing, shortcuts | `ui/canvas/`, `ui/main_window.py` | pytest-qt tests and user guide. |
| Undo, review, correction decisions | `ui/commands/`, `application/` | Reversal/acceptance tests. |
| PAGE parsing, geometry, or writes | `pagexml/`, `domain/` | Validator and preservation tests. |
| Alignment or auto-merge behavior | `correction/` | Pure proposal and workflow tests. |
| Project pairing or input files | `application/project_scanner.py` | Scanner tests and README if formats change. |
| Package/release workflow | `pyproject.toml`, workflows | `scripts/check_release.py`, README, and release guide. |

A code change is done only when its focused regression coverage, applicable
user documentation, and the full verification gate are current and passing.

## Git and release conventions

- Use focused `codex/<topic>` branches and Conventional Commit subjects
  (`feat:`, `fix:`, `test:`, `docs:`, `refactor:`, `chore:`).
- Inspect `git status` before staging; never include unrelated, ignored, or
  generated changes.
- Run the privacy gate immediately before committing.
- Do not create tags, publish releases, or change GitHub settings unless the
  user explicitly requests it. A release tag must match `pyproject.toml` and
  pass `scripts/check_release.py`; artifacts are built by the release workflow.

Keep this file concise and durable. Put detailed product behavior in the user
guide and release procedure in `RELEASING.md`; update this file only when a
repository-wide command, invariant, or routing rule changes.

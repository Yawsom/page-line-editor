# PAGE Line Editor: implementation plan

**Status:** implemented for the Python-environment MVP; packaging remains a next step  
**Branch:** `codex/qt-xml-correction-editor`  
**Working title:** PAGE Line Editor  
**Primary stack:** Python 3.11+ and PySide6 / Qt Widgets  

## 1. Outcome and scope

Build an offline desktop application for macOS and Windows (with Linux supported where practical) that opens separate image and PAGE XML folders, presents matched pages, overlays every `TextLine/Coords` polygon and `TextLine/Baseline`, and supports manual transcription and geometry correction.

Clicking a polygon interior, polygon border, or baseline selects one logical line. A compact editor remains visually anchored immediately beneath that line and contains:

1. the editable line transcription, with Arabic right-to-left presentation initially;
2. an optional, read-only one-line auto-correction diff beneath it; and
3. keep/reject controls when an automatically applied correction exists.

The application will support explicit save, undo/redo, dirty-state warnings, per-page and folder-wide auto-correction previews, timestamped backups, retained reports, and PAGE XML validation before source files are replaced.

### MVP non-goals

- Manual line splitting and merging.
- Manual text-region editing.
- TIFF/multipage image support.
- A virtual keyboard or custom keyboard shortcuts beyond normal application actions.
- Editing PAGE namespace versions other than the repository's `2013-07-15` version.
- Shipping signed standalone installers in this iteration. The code and build layout will be packaging-ready.

The existing auto-correction behaviour is applied automatically to the in-memory document when a run finishes, but never written to XML until explicit Save. Each applied change remains reviewable: Keep confirms it and Reject restores the pre-correction value. Deferring manual split/merge must not make structural automatic changes silent.

## 2. Confirmed product decisions

- Use PySide6 and remain compatible with the community LGPLv3/GPLv3 Qt distribution.
- Work entirely offline at runtime.
- Support JPEG and PNG initially.
- Use a folder workflow with separate image and XML directories and one XML document per image.
- Prefer equal image/XML stems for pairing. Retain a compatibility fallback to PAGE `Page/@imageFilename` because the current local samples use names such as `transkribus-93v.xml` for `93v.jpg`. Fallback and ambiguous matches must be visible in the page-list diagnostics.
- Allow polygon and baseline vertex dragging, vertex insertion/removal, whole-shape movement, and replacement drawing.
- Keep page rotation as a view transform only; it must never change PAGE coordinates.
- Provide zoom, pan, fit, overlay toggles, and distinct normal/selected/proposed/error colours.
- Use explicit Save, timestamped backup, and dirty-state confirmation on page/project/app changes.
- Provide System, Light, and Dark themes.
- Use toggleable Unicode NFC normalization for saved transcription, enabled by default. This is separate from the existing aggressive Arabic matching normalization, which must remain match-only.
- Run auto-correction for the current page or the folder, apply results automatically in memory, and let Keep/Reject confirm or revert each result before explicit Save.
- Keep original XML and a diff report in a separate audit directory whenever auto-correction runs.

## 3. Repository findings that shape the design

The current implementation is healthy but is not yet an application service:

- `align_report.py` is a 1,079-line module containing domain models, PAGE parsing, alignment, mutation, HTML/JSON generation, folder orchestration, console output, and the CLI.
- All five existing regression tests pass on this branch.
- The parser reads full polygon/baseline points but the `XmlLine` model discards them and retains only an axis-aligned box and mean baseline Y. The editor needs full point geometry.
- `run()` writes reports and corrected XML immediately and prints to the console. Preview/accept/reject requires a side-effect-free proposal API.
- The current rewrite path can delete `Word` children, delete or merge `TextLine` elements, clear region-level Unicode, and reindex reading order. Manual saves must instead be narrow, explicit mutations.
- Current writes are neither atomic nor backed up.
- The PAGE namespace is hard-coded to `http://schema.primaresearch.org/PAGE/gts/pagecontent/2013-07-15`.
- The local Transkribus samples include `Metadata/TranskribusMetadata` in the PAGE namespace, but the official 2013 XSD permits only Creator, Created, LastChange, and optional Comments in Metadata. They are therefore not strictly XSD-valid before any edit. Validation must preserve and explain this vendor metadata rather than stripping it or presenting a false green badge.
- The existing geometric merge sorts/deduplicates baseline points. PAGE defines a baseline as a connected point sequence, so the refactor must preserve its order and never reverse it merely because the transcription is RTL.
- Existing private manuscript XML, Word data, reports, and corrected output are ignored and untracked. However, the ignore rules cover only the four existing directories, not arbitrary project/image folders.
- The local unedited samples are uniformly 1500 x 1898, have one `TextRegion`, and contain line polygons, baselines, and line-level Unicode without `Word` children. Synthetic tests must cover broader PAGE structures without committing manuscript data.

## 4. User experience

### 4.1 Main window

- **Top toolbar:** Open Project, Save, Undo, Redo, Previous/Next Page, zoom controls, Fit, rotate left/right/reset, polygon/baseline/diff toggles, theme, and Auto Correct.
- **Left tool palette:** Pan Canvas, Select/Edit, Move Whole Line, add/delete vertex, and polygon/baseline replacement as separate vector-editor-style tools.
- **Left page browser:** matched pairs, missing/ambiguous files, dirty marker, validation state, and auto-correction review counts.
- **Centre canvas:** page image plus vector overlays, vertex handles for only the selected line, and the anchored transcription/diff editor.
- **Right review panel:** project folders/settings, run progress, page-level accept/reject controls, filter by proposal status, and validation messages. It does not replace the anchored editor.
- **Status bar:** filename pair, image dimensions, PAGE namespace, zoom/rotation, selected line ID, dirty state, and background-job status.

### 4.2 Project opening and pairing

The Open Project flow requests:

- image folder;
- PAGE XML folder;
- ground-truth `.docx` used by automatic correction (optional until correction is run);
- audit/history folder, defaulting to a `correction_history` sibling of the XML folder; and
- normalization/theme preferences.

Scanner rules:

1. index `.jpg`, `.jpeg`, and `.png` case-insensitively;
2. index `.xml` case-insensitively;
3. pair a unique exact stem first;
4. use a unique case-insensitive stem only as a reported compatibility match;
5. use a unique PAGE `imageFilename` match only as a reported legacy fallback;
6. never guess between duplicates; show missing, duplicate, malformed, and metadata-dimension diagnostics;
7. isolate a malformed page rather than aborting the entire folder.

### 4.3 Selection and editing

- One logical graphics item owns a line's polygon and baseline, so any of the three requested hit areas produces the same selection.
- Hit tolerance, line width, and handles remain constant in screen pixels at every zoom.
- The active popup is a viewport overlay, not a widget embedded into every scene item. It stays horizontal and readable while the image rotates, but its anchor is recomputed from the transformed line geometry after zoom, pan, scroll, resize, rotation, or geometry edits.
- If the popup would fall below the viewport, the canvas scrolls or exposes a temporary lower scene margin. It is never flipped above the line.
- The editor uses Arabic RTL layout initially and normal OS input methods. Language and direction are data/configuration properties so future languages can use LTR or automatic direction.
- Text is buffered while typing. `Ctrl/Cmd+Enter` commits an undoable text edit; selection/page changes also commit a non-empty changed buffer after validation; Escape restores the current committed text. `Ctrl/Cmd+S` writes the document to disk.

### 4.4 Geometry tools

- **Select/Edit:** select a single line by default, Shift-click for multi-select, and drag vertex handles without moving the whole line.
- **Pan Canvas:** left-drag to navigate; Ctrl/Command temporarily invokes pan from any tool.
- **Move Whole Line:** deliberately move the polygon and baseline together as a separate, less-common operation.
- **Add Vertex:** insert at the closest segment of the chosen polygon or baseline.
- **Delete Vertex:** delete a selected handle while enforcing at least three polygon points and two baseline points.
- **Replace Shape:** click a new point sequence; Enter or double-click commits, Escape cancels.
- Whole-line movement is isolated from normal selection to prevent accidental geometry edits.
- Dragging previews continuously but creates one undo command at mouse release.
- Coordinates stay in raw image-pixel space and are quantized to non-negative PAGE integers only when an edit commits.
- Edited polygons cannot self-intersect; edited baselines must remain inside the line polygon; edited line geometry must remain inside image bounds and its parent region. Existing legacy inconsistencies are warnings, but a new edit that introduces an inconsistency is blocked.

## 5. Technical architecture

Use a `src/` package layout and keep core/document code independent of Qt:

```text
src/page_line_editor/
  __main__.py                 # python -m page_line_editor
  cli.py                      # compatibility and headless workflows
  domain/
    geometry.py               # Point, Polygon, Polyline, validation
    page.py                   # PageDocument, TextRegion, TextLine
    correction.py             # proposals, decisions, run state
  pagexml/
    parser.py                 # namespace-aware, secure parser
    writer.py                 # narrow patches and serialization
    validator.py              # XSD plus semantic checks
    schemas/
      pagecontent-2013-07-15.xsd
  correction/
    normalization.py
    noise.py
    aligner.py
    service.py                # side-effect-free proposal API
  reports/
    model.py
    json_report.py
    html_report.py
  application/
    project_scanner.py
    session.py
    save_service.py
    history_service.py
    job_runner.py
  ui/
    main_window.py
    canvas/
      view.py
      scene.py
      line_item.py
      vertex_handle.py
      transcription_overlay.py
    commands/                 # QUndoCommand implementations
    panels/
    themes/
  resources/
align_report.py               # temporary compatibility shim
tests/
```

### 5.1 Domain model

Qt types must not appear in the model. Core objects include:

- `Point(x: int, y: int)`, `Polygon(points)`, and `Polyline(points)`.
- `TextLine`: stable line/region IDs, original and current text, original and current polygon/baseline, child-content presence, reading/source order, warnings, dirty fields, and proposal state.
- `PageDocument`: source path, namespace/version, image metadata/path, ordered regions/lines, original raw XML tree adapter, validation report, revision, and dirty state.
- `PagePair`: image/XML paths, pairing method, and diagnostics.
- `CorrectionSettings`: current thresholds and deletion/normalization policy rather than module globals.
- `LineProposal`: affected IDs, action, before/after text and geometry, status, ratio, flags, character diff, and pending/accepted/rejected decision.
- `CorrectionRun`: run ID, settings, page proposals, progress, cancellation state, and report/history paths.

Original values are immutable snapshots. Current values change only through commands. UI items render model state and emit intent; they are never the source of truth.

### 5.2 PAGE XML adapter

Use `lxml.etree` for XML parsing, controlled mutation, and offline XSD validation. Parse securely with network access, recovery, and entity resolution disabled while retaining comments, processing instructions, whitespace, namespace maps, element order, unknown elements, and attributes where the library permits.

The GUI writer will:

- mutate only accepted `TextLine/Coords/@points`, `TextLine/Baseline/@points`, and `TextLine/TextEquiv/Unicode` fields;
- insert missing elements in the schema-significant TextLine order (`Coords`, optional Baseline, Words, optional TextEquiv, optional TextStyle) and preserve optional `PlainText` before required `Unicode`;
- update `Metadata/LastChange` in UTC with a `Z` suffix and record the application in Creator/UserDefined only after the metadata policy is approved during implementation;
- preserve region-level text, Words/Glyphs, custom attributes, comments, unknown namespaces, and reading order unless an explicitly accepted auto proposal requires structural change;
- preserve baseline/polygon vertex order and the source polygon-closure convention; do not sort baseline points or append a duplicate first polygon point merely for display closure;
- preserve the source XML declaration's encoding/standalone setting where practical;
- never promise byte-for-byte preservation of XML formatting, quote style, or empty-tag spelling; it will promise semantic preservation of untouched content;
- retain the existing one-line Transkribus serializer as a legacy CLI mode until compatibility tests establish that it can be retired.

MVP read/write support is restricted to PAGE `2013-07-15`. Other namespaces are detected and reported, with read-only inspection preferred over accidental conversion. The adapter registry will allow later schema versions.

### 5.3 Validation policy

Bundle the exact official 2013 XSD so validation works offline. Report two schema statuses because Transkribus extends Metadata outside what that XSD permits:

- **Strict PAGE 2013:** validate the unchanged real tree against the official XSD and report every error, including vendor metadata.
- **PAGE core with preserved vendor extensions:** validate a temporary clone after removing only explicitly allowlisted vendor-only Metadata children. Never remove those elements from the real tree or output.

Saving uses two levels:

1. **Blocking structural validation:** well-formed XML; expected namespace; no new strict-schema errors; PAGE-core XSD validity; unique IDs; required line coordinates; valid non-negative integer point syntax; positive page dimensions; coordinates inside `[0, width-1] x [0, height-1]`; minimum polygon/polyline sizes; and no newly introduced self-intersections.
2. **Consistency diagnostics:** baseline within line polygon, line within region, PAGE image dimensions matching the actual image, and stale region/Word/Glyph transcriptions. Pre-existing warnings remain visible; new invalid geometry cannot be committed.

Validation compares the candidate with load-time diagnostics. A pre-existing, allowlisted Transkribus extension error does not block a narrow edit, but a new error or any PAGE-core failure does. The UI must never collapse these two states into a single unqualified “valid” badge.

The exact policy for multi-level `TextEquiv` consistency is deliberately flagged for later interoperability work. The MVP will not silently delete Words/Glyphs or rewrite region text merely to make a line edit. Auto proposals that would do so must surface the effect for confirmation.

### 5.4 Save and audit safety

An explicit save performs:

1. commit the active editor buffer into the undo model;
2. build candidate XML bytes in memory;
3. run blocking validation on those bytes;
4. create a timestamped backup of the exact source XML in the configured history directory;
5. write and flush a same-directory temporary file;
6. atomically replace the source with `os.replace` only after validation and successful flush;
7. mark the undo stack clean only after replacement succeeds.

No validation or I/O failure may damage the source. Manual saves use:

```text
correction_history/
  manual/YYYYMMDDTHHMMSSZ-<id>/originals/<name>.xml
```

Auto-correction runs use:

```text
correction_history/
  auto/YYYYMMDDTHHMMSSZ-<id>/
    originals/<name>.xml
    reports/alignment.json
    reports/index.html
    reports/pages/<stem>.html
    manifest.json
```

The run report and originals are retained even when proposals are rejected. Line records are keyed by XML filename plus persistent `TextLine/@id`. The manifest records proposed, accepted, rejected, skipped, failed, and cancelled actions. A batch uses a two-phase preflight (serialize/validate all accepted pages, then back up and replace per file). Cross-file replacement cannot be globally atomic, so the manifest must record any partial batch failure and make recovery straightforward.

## 6. Auto-correction refactor and workflow

### 6.1 Extract without changing established behaviour

Move current pure functions into focused modules and keep compatibility re-exports through `align_report.py`. Preserve:

- Arabic match-only normalization;
- noise detection thresholds and defaults;
- Needleman-Wunsch alignment behaviour;
- status names and meanings;
- the default of deleting only independently confirmed noise extras;
- existing report JSON keys and CLI flags/defaults; and
- current widest-primary/convex-hull merge behaviour, initially behind proposal generation.

Baseline union is an exception to byte-for-byte legacy parity: the current implementation sorts points and can change a connected polyline's meaning. The replacement algorithm must preserve or explicitly reconstruct a continuous ordered baseline and lock that corrected behaviour with tests.

Golden regression tests must prove that the refactor produces the same alignments and legacy CLI outputs before the GUI uses it.

### 6.2 Proposal API

Replace the GUI's use of the writing `run()` function with:

```python
proposal = correction_service.propose(document_snapshot, ground_truth, settings, cancel_token)
updated_document = correction_service.apply(document, accepted_proposal_ids)
```

`propose()` has no source-file writes and returns stable ID-addressed proposals. `apply()` runs on the GUI thread through undo commands. Rejecting does not mutate the document.

### 6.3 Review experience

- Current-page mode proposes changes for the active page.
- Batch mode scans all valid pairs and sends immutable progress/results back to the UI.
- Proposed lines use a distinct overlay colour and display the current-to-proposed one-line diff below the editor.
- Results are applied automatically as one undo macro when a run completes. Users can keep/reject one result, all filtered results on a page, or all reviewed results in a batch; Reject restores its recorded before-state.
- `MISSING` remains report-only because there is no geometry to attach.
- `MERGE` or delete actions display affected IDs and geometry before acceptance.
- The automatic application is an undo macro, so one Undo restores the pre-run page state.
- Reports are generated from the proposal/decision model, avoiding a second divergent diff implementation.

## 7. Qt implementation choices

### 7.1 Graphics view

Use `QGraphicsView`/`QGraphicsScene` with:

- one `QGraphicsPixmapItem` background using bounding-rectangle shape mode;
- one custom `QGraphicsObject` per line, painting both polygon and baseline;
- a custom `shape()` that unions polygon fill/border and a widened baseline stroke for hit testing;
- cosmetic pens and transform-ignoring handles for stable screen-pixel appearance;
- image coordinates as scene coordinates; and
- view transformations for zoom/rotation only.

Every geometry mutation calls `prepareGeometryChange()` before altering item bounds. Only the selected line creates visible handle items.

### 7.2 Undo and dirty state

Use `QUndoStack` with commands for text edit, vertex move/insert/delete, whole-shape move, shape replacement, automatic correction application, keep confirmation, and rejection/reversion. Merge typing and drag updates into meaningful units. Use the undo stack's clean index as the single dirty-state authority.

### 7.3 Background work and cancellation

Use a `QObject` worker moved to `QThread`, queued signals, immutable inputs/results, and cooperative cancellation checks between pages and expensive alignment phases. Qt interruption is advisory, so the correction service also receives an explicit cancellation token. Never call `QThread.terminate()` and never touch widgets, scene items, or the live document from a worker.

Keep the application runner pluggable. A later packaged build may use the same importable correction module through a `QProcess --worker` mode for stronger crash/cancellation isolation without duplicating correction logic.

### 7.4 Image memory policy

Use `QImageReader` to inspect dimensions before decoding and compare them with PAGE `imageWidth`/`imageHeight`. Do not apply EXIF auto-rotation silently because PAGE coordinates reference raw pixels.

- Warn when estimated decoded memory (`width * height * 4`) reaches 256 MiB.
- Refuse by default at 512 MiB (about 134 million pixels), with an explicit advanced override up to 1 GiB.
- Retain Qt's allocation guard and show its error message rather than disabling it globally.
- Keep only the current full-resolution pixmap plus small page-list thumbnails in memory.
- Hide the limits behind an `ImageSource` abstraction so a later tiled/mipmap decoder can support substantially larger pages.

There is no encoded-file-size limit; safety is based on decoded memory.

### 7.5 Theme, accessibility, and future languages

- System/Light/Dark modes use `QPalette` semantic roles and a small targeted stylesheet.
- Overlay colours are semantic tokens with separate values for both themes: normal polygon, baseline, selected, proposed, accepted, rejected/error, and handles.
- Do not depend on colour alone; selection and proposal states also vary stroke pattern/weight and labels.
- All actions receive names, tooltips, accessible labels, and standard macOS/Windows key sequences.
- Store language and direction in project/document settings rather than Arabic-specific UI code.
- Defer Qt Virtual Keyboard: it has different Qt licensing implications and needs an explicit later decision.

## 8. Data privacy and repository guardrails

No manuscript PAGE XML, images, Word ground truth, generated reports, backups, or correction history may be committed locally or remotely.

Phase 0 will:

- recommend project data live outside the source checkout;
- expand ignore rules for common manuscript/project paths and file extensions without hiding approved source assets or the public `.xsd` schema;
- keep tests self-contained by generating XML strings and tiny synthetic images inside temporary directories;
- add a repository/CI guard that rejects tracked raster manuscript formats, `.docx`, correction-history/report paths, and PAGE-looking data files unless explicitly allowlisted as public source resources such as the official XSD;
- use SVG/code-generated application icons during development; and
- document a safe fixture policy before accepting outside contributions.

The current ignored private samples are for local verification only and will never be added to Git.

## 9. Dependency and project management

Introduce `pyproject.toml` immediately, even though this iteration runs from a virtual environment.

Runtime dependencies:

- PySide6;
- lxml;
- python-docx.

Development dependencies:

- pytest;
- pytest-qt;
- coverage;
- Ruff;
- mypy, initially strict for the Qt-independent core and incrementally tightened for UI adapters.

Use a pinned tested range rather than unbounded minimums. The initial compatibility target is Python 3.11-3.13; Python 3.14 can remain a local compatibility job once the complete dependency set is confirmed. Provide `python -m page_line_editor` and retain `python align_report.py`.

## 10. Testing and quality strategy

### 10.1 Core tests

- Point parsing/formatting, point quantization, bounds, polygon self-intersection, baseline containment, vertex insertion/removal, and shape moves.
- PAGE parsing for multiple regions, comments, unknown elements/namespaces, custom attributes, missing baselines, line/region/word text levels, malformed files, and unsupported namespaces.
- Targeted writer tests proving that only accepted fields change semantically.
- Strict XSD versus PAGE-core/vendor-extension validation, candidate-versus-baseline error comparison, and useful diagnostics.
- Atomic-save and backup tests with injected clock and simulated write/replace failures.
- Folder matching for case/extension variants, missing/duplicate files, legacy `imageFilename`, corrupt XML, and image-dimension mismatch.
- Unicode NFC toggle tests distinct from match-only Arabic normalization.

### 10.2 Correction tests

- Preserve all five current regressions.
- Add alignment golden tests for match/OCR/extra/missing/merge/split and cancellation.
- Prove proposal generation has no writes.
- Prove rejected actions never alter a document or save output.
- Prove structural proposals expose every deleted/merged ID and geometry change.
- Version the report schema while preserving current keys.

### 10.3 UI tests

Using `pytest-qt`/QTest in offscreen mode:

- clicking polygon interior, border, and baseline selects the same line;
- hit tolerance and handle size remain stable across zoom;
- popup remains below the transformed line after pan/zoom/rotation/resize;
- RTL input, commit, cancel, diff toggle, and accept/reject work;
- all geometry edit modes and minimum-point constraints work;
- one drag/text commit equals one undo step;
- clean/dirty state, Save, page change, close warning, and failed-save state are correct;
- background progress/cancel leaves source XML untouched; and
- Light/Dark/System theme switching does not lose editor state.

### 10.4 Continuous integration

Run lint, type checks, core tests, and headless Qt tests on Windows, macOS, and Linux. Keep manuscript data out of CI. Add packaging smoke jobs only after the Python-environment MVP is stable.

## 11. Implementation phases and acceptance gates

### Phase 0 - project safety and package skeleton

- Add `pyproject.toml`, `src/` package, tool configuration, contributor documentation, and repository data guards.
- Keep the existing CLI and tests working.

**Gate:** clean install in a new venv; existing tests pass; CI/data guard proves private data is untracked.

### Phase 1 - extract the correction engine

- Separate domain, normalization, alignment, report generation, and legacy rewrite policy.
- Add side-effect-free proposal models/service and a compatibility shim.

**Gate:** golden parity with current CLI, reports, statuses, and safe extra-deletion defaults; proposals make no writes.

### Phase 2 - PAGE document, pairing, validation, and safe save

- Implement full geometry model, secure lxml adapter, folder scanner, 2013 XSD validation, history service, and atomic targeted writer.

**Gate:** synthetic round-trip tests preserve all untouched semantic content; invalid candidates cannot replace source; backups restore exactly.

### Phase 3 - viewer and navigation

- Implement the main window, page browser, image loading, scene/view, overlays, selection, zoom/pan/fit/rotation, theme tokens, and diagnostics.

**Gate:** navigate a private local folder without data entering Git; every polygon/baseline aligns to its image and selects reliably.

### Phase 4 - manual text and geometry editing

- Add anchored RTL editor, normalization toggle, all four geometry edit operations, undo/redo, dirty state, explicit Save, warnings, and accessibility metadata.

**Gate:** edit text/polygon/baseline, undo/redo, save, and reopen PAGE-core-valid targeted XML with no new strict-schema errors and a timestamped backup.

### Phase 5 - current-page automatic correction review

- Run correction in a worker, show progress/cancel, overlay/diff proposals, and implement per-line/page accept/reject as undo commands.
- Persist original XML and complete reports to the audit folder.

**Gate:** a completed run updates the in-memory page immediately, cancellation/rejection never changes source, rejection restores the before-state, explicit Save persists the remaining applied actions, and report/backup identify every action.

### Phase 6 - batch review and hardening

- Add folder-wide processing, filters, batch accept/reject, two-phase save preflight, recovery manifest, failure isolation, performance tests, and UI polish.

**Gate:** mixed valid/invalid folder completes without aborting good pages; partial failures are recoverable and accurately reported.

### Phase 7 - open-source and standalone release preparation (next iteration)

- Finalize project license and third-party notices.
- Add a checked-in `pysidedeploy.spec` and platform-native CI builds using Qt's `pyside6-deploy`/Nuitka path.
- Build separately on Windows and macOS, smoke-test on clean machines, sign Windows artifacts, and sign/notarize the macOS app/DMG.
- Decide update strategy and release provenance/SBOM.

**Gate:** offline packaged app passes open/edit/save/validate/auto-correct smoke tests on clean Windows and macOS systems.

## 12. Risks and explicit write-up considerations

1. **PAGE semantic consistency:** XSD validity alone does not enforce baseline/polygon containment or consistent text across Region/Line/Word/Glyph. MVP combines XSD with application checks, does not silently destroy lower-level structures, and leaves a documented policy decision for broader PAGE interoperability. Current Transkribus metadata is also outside the strict 2013 XSD, so strict and extension-tolerant core results must remain distinct.
2. **XML round-trip format:** lxml can preserve semantic tree content, comments, namespaces, and order, but not byte-identical whitespace/quotes/empty-tag style. Tests will define and enforce semantic preservation.
3. **Existing auto-correction destructiveness:** merge/delete/Word removal and region-text clearing must be separated into visible proposal policies before GUI integration.
4. **Legacy pairing:** new projects should use equal stems, while current Transkribus files require `imageFilename` fallback. The UI must label fallbacks rather than silently normalizing names.
5. **Large images:** a full pixmap can need multiple decoded copies. The MVP uses conservative memory limits; genuinely huge pages require later tiling.
6. **Batch atomicity:** individual XML replacement can be atomic, but an entire folder cannot be one filesystem transaction. Preflight, backups, and a manifest provide recovery.
7. **Qt licensing and virtual keyboard:** PySide6/Qt community licensing and third-party notices must be followed. Qt Virtual Keyboard is deferred until its GPL/commercial implications are deliberately accepted.
8. **Packaging:** Windows and macOS artifacts must be built and tested on their target OS; signing/notarization credentials and release policy are separate next-step decisions.

## 13. Definition of MVP done

The Python-environment MVP is done only when a user can open separate private image/XML folders, review diagnostics, navigate pages, select any line through any requested geometry, edit Arabic text/polygon/baseline with undo/redo, view an anchored optional auto diff, accept/reject current-page and batch proposals, explicitly save PAGE-core-valid XML with no newly introduced strict-schema errors through an atomic backed-up write, reopen the exact saved state, and find complete originals/reports in the audit directory. All of this must work offline, pass automated tests on macOS/Windows/Linux, and leave no manuscript data tracked by Git.

## 14. Research basis

- [Qt for Python overview and licensing](https://doc.qt.io/qtforpython-6/)
- [Qt for Python getting started and Python requirements](https://doc.qt.io/qtforpython-6/gettingstarted.html)
- [Qt Graphics View framework](https://doc.qt.io/qtforpython-6/overviews/qtwidgets-graphicsview.html)
- [QGraphicsScene item lookup](https://doc.qt.io/qtforpython-6/PySide6/QtWidgets/QGraphicsScene.html)
- [QGraphicsItem shape and hit testing](https://doc.qt.io/qtforpython-6/PySide6/QtWidgets/QGraphicsItem.html)
- [QPainterPathStroker](https://doc.qt.io/qtforpython-6/PySide6/QtGui/QPainterPathStroker.html)
- [QUndoStack clean state, macros, and command compression](https://doc.qt.io/qtforpython-6/PySide6/QtGui/QUndoStack.html)
- [QThread worker-object pattern and cooperative interruption](https://doc.qt.io/qtforpython-6/PySide6/QtCore/QThread.html)
- [QImageReader allocation protection](https://doc.qt.io/qtforpython-6/PySide6/QtGui/QImageReader.html)
- [Qt for Python deployment guidance](https://doc.qt.io/qtforpython-6/deployment/index.html)
- [Official PAGE 2013-07-15 XSD](https://www.primaresearch.org/schema/PAGE/gts/pagecontent/2013-07-15/pagecontent.xsd)
- [Official PRImA PAGE-XML repository](https://github.com/PRImA-Research-Lab/PAGE-XML)
- [lxml parsing controls](https://lxml.de/parsing.html)
- [lxml XMLSchema validation](https://lxml.de/validation.html#xmlschema)
- [Python ElementTree parsing behaviour](https://docs.python.org/3/library/xml.etree.elementtree.html)
- [OCR-D PAGE validation checks](https://ocr-d.de/core/api/ocrd/ocrd.cli.validate.html)

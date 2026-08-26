# PAGE Line Editor

An offline PySide6 desktop editor for PAGE 2013 XML transcription, line polygons,
baselines, and automatic Arabic ground-truth correction.

The application opens separate image and XML folders, pairs JPEG/PNG pages with
their XML, overlays every `TextLine/Coords` polygon and `TextLine/Baseline`, and
keeps an Arabic right-to-left transcription editor anchored beneath the selected
line. Clicking the polygon interior, border, or baseline selects the same line.

## Current capabilities

- Folder browser with exact-stem, case-insensitive, and PAGE `imageFilename`
  pairing diagnostics.
- Zoom, pan, fit, view-only 90-degree rotation, overlay toggles, and System,
  Light, and Dark themes.
- Undoable transcription editing and polygon/baseline vertex drag, add, delete,
  whole-line move, and shape replacement.
- Geometry guards for minimum vertex counts, image bounds, self-intersections,
  and newly introduced baselines outside their polygons.
- Toggleable Unicode NFC normalization for manual transcription edits.
- Current-page and cancellable folder automatic correction.
- Automatic in-memory application of corrections. Keep confirms an applied
  result; Reject restores its exact pre-correction text, geometry, deletion, and
  proposal metadata. XML is not changed until explicit Save.
- Timestamped audit runs containing the untouched original XML, JSON/HTML diff
  reports, and a decision manifest.
- Narrow PAGE XML mutation, offline official PAGE 2013 XSD plus semantic
  validation, exact pre-save backup, and atomic source replacement.

Manual structural split/merge is intentionally deferred. Automatic merge and
confirmed-noise deletion remain reviewable and reversible.

## Development setup

Python 3.11 or newer is required. From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
python -m pip install ".[dev]"
python -m page_line_editor
```

Use a normal local install as shown above. In some macOS/Python 3.14
environments, setuptools' editable-install path file can be marked hidden and
then skipped, so `pip install -e .` may report success while
`page_line_editor` remains unimportable. When developing without reinstalling,
launch directly from the checkout instead:

```bash
PYTHONPATH=src python -m page_line_editor   # macOS/Linux
```

On macOS, the launcher automatically creates a temporary, unhidden mirror of
Qt's plugins when filesystem flags would otherwise hide the Cocoa or JPEG/PNG
plugins. If Qt was partially installed and still reports that `cocoa` cannot be
found, refresh the pinned Qt runtime once:

```bash
python -m pip install --force-reinstall --no-deps \
  PySide6==6.10.1 PySide6_Essentials==6.10.1 \
  PySide6_Addons==6.10.1 shiboken6==6.10.1
```

In the application, choose **Open Project** and provide:

1. the JPEG/PNG folder;
2. the PAGE XML folder;
3. the optional folio-delimited ground-truth `.docx`; and
4. an audit/history directory outside the live XML folder.

Ground-truth pages use paragraphs such as `[93v]`; each following non-empty
paragraph is one manuscript line until the next folio header.

In **Select / Move** mode, left-drag the empty page or background to pan. Drag a
line to move its geometry, drag its handles to edit vertices, or middle-drag
from anywhere to pan without changing tools. Use Ctrl/Command + wheel to zoom.

The historical command-line workflow remains available during the transition:

```bash
python align_report.py --help
```

## Safety and privacy

Manuscript XML, Word files, images, reports, and correction history are ignored
globally by repository policy. Run the data guard before any commit:

```bash
python scripts/check_no_private_data.py
```

Automatic correction always writes its audit copy before changing the in-memory
model. Explicit Save validates candidate bytes, writes an exact timestamped
backup, flushes a same-directory temporary file, and then uses atomic replace.

## Quality checks

```bash
ruff check .
mypy src/page_line_editor
pytest
```

CI covers Python 3.11 and 3.13 on Windows, macOS, and Linux. Runtime behavior is
offline; no network request is made by the editor.

## Packaging and open-source next steps

Qt documents `pyside6-deploy` as its supported cross-platform freezing path for
Windows, macOS, and Linux. A later release should add reproducible platform jobs,
application icons, signing/notarization, installer smoke tests, and bundled
license notices. PySide6 is available under LGPLv3/GPLv3 or a commercial Qt
license; the application project's own open-source license still needs an
explicit maintainer decision before public release.

The validator bundles the official PRImA PAGE 2013 XSD. Strict validation reports
vendor-only Transkribus metadata; the separate editable-core result validates a
temporary clone with only the known `TranskribusMetadata` extension removed. The
real XML always retains that metadata.

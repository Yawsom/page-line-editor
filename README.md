# PAGE Line Editor

An offline PySide6 desktop editor for PAGE 2013 XML transcription, line polygons,
baselines, and automatic Arabic ground-truth correction.

> **Early alpha:** this project is ready for evaluator feedback, not production
> manuscript processing. Keep independent backups of source XML and review every
> automatic correction before saving. See [RELEASING.md](RELEASING.md) for the
> guarded release process and current alpha limitations.

The application opens separate image and XML folders, pairs JPEG/PNG pages with
their XML, overlays every `TextLine/Coords` polygon and `TextLine/Baseline`, and
keeps an Arabic right-to-left transcription editor anchored beneath the selected
line. Clicking the polygon interior, border, or baseline selects the same line.

See the [User Guide](docs/user_guide.md) for the complete tool and shortcut
reference.

## Current capabilities

- Folder browser with exact-stem, case-insensitive, and PAGE `imageFilename`
  pairing diagnostics.
- Zoom, pan, fit, view-only 90-degree rotation, overlay toggles, and System,
  Light, and Dark themes.
- Undoable transcription editing and polygon/baseline vertex drag, add, delete,
  whole-line move, and shape replacement.
- Geometry-scaled transcription editing and in-app correction cards showing the
  correction as a green addition above the red original PAGE text. Added
  characters are highlighted, removed characters are struck through, and
  MATCHED/OCR/REMOVED-style tags are color coded.
- Dedicated geometry and transcription work modes. Transcription mode hides
  polygons, baselines, vertices, and geometry-only tools while preserving line
  selection and the anchored editor.
- Left-side vector tool palette separating canvas pan, line selection/vertex
  editing, whole-line movement, and vertex/shape operations.
- Geometry guards for minimum vertex counts, image bounds, self-intersections,
  and newly introduced baselines outside their polygons.
- Toggleable Unicode NFC normalization for manual transcription edits.
- Current-page and cancellable folder automatic correction.
- Automatic in-memory application of text and geometry corrections. Pending
  `EXTRA` deletions remain visible until Keep/Enter removes the line; Reject
  preserves it. XML is not changed until explicit Save.
- Timestamped audit runs containing the untouched original XML, JSON/HTML diff
  reports, and a decision manifest.
- Narrow PAGE XML mutation, offline official PAGE 2013 XSD plus semantic
  validation, exact pre-save backup, and atomic source replacement.

Manual structural split/merge is intentionally deferred. Automatic merges and
pending EXTRA deletions remain reviewable and reversible.

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

## Recommended local project layout

Keep every manuscript, transcription, report, and audit file outside the
tracked source tree. This checkout reserves the ignored `local_data/` folder for
that purpose:

```text
local_data/
  images/                         # page images selected in Open Project
    93v.jpg
    94r.png
  transcribed_xml/                # live PAGE XML selected in Open Project
    93v.xml
    94r.xml
  ground_truth/                   # optional Word ground truth
    transcription.docx
  correction_history/             # automatic backups, manifests, and audits
  reports/                        # legacy CLI report-only output
  corrected_xml/                  # legacy CLI corrected-XML output
```

For the smoothest pairing, give each page image and its PAGE XML the same stem:
`93v.jpg` with `93v.xml`, for example. The folders named above are ignored by
Git; do not add real manuscript data to another tracked folder.

### File and folder requirements

| Item | Required | Accepted format and setup |
| --- | --- | --- |
| Image folder | Yes | A directory containing one page per `.jpg`, `.jpeg`, or `.png` file (case-insensitive). TIFF, PDF, and multipage-image input are not supported. Use unique stems and pair `93v.jpg` with `93v.xml` where possible. |
| PAGE XML folder | Yes | A separate directory containing `.xml` files (case-insensitive) in the PAGE 2013-07-15 namespace. Each XML must resolve to one image: exact matching stem is preferred; case-insensitive matching and `Page/@imageFilename` are compatibility fallbacks shown in diagnostics. |
| Ground-truth file | Optional | One `.docx` file, not `.doc`, PDF, or plain text. Use a paragraph containing a numeric folio key such as `[93v]` or `[94r]`; every following non-empty paragraph is one line until the next folio key. The key must match an image or XML stem. |
| Correction-history folder | Yes | A writable directory outside the live XML folder. The app stores timestamped exact backups, original XML, JSON/HTML audit reports, and decision manifests here. The default is a `correction_history/` sibling of the chosen XML folder. |
| CLI report folder | CLI only | A writable output directory for `align_report.py` HTML/JSON reports; the recommended location is `local_data/reports/`. |
| CLI corrected-XML folder | CLI only | A writable output directory for `align_report.py --corrected-dir`; it must be different from the source XML folder. Use `local_data/corrected_xml/`. |

In the application, choose **Open Project** and provide:

1. the JPEG/PNG folder;
2. the PAGE XML folder;
3. the optional folio-delimited ground-truth `.docx`; and
4. an audit/history directory outside the live XML folder.

Ground-truth pages use paragraphs such as `[93v]`; each following non-empty
paragraph is one manuscript line until the next folio header.

Use **Select / Edit** to select one line and edit its vertex handles; Shift-click
extends or toggles a multi-selection. Use **Pan Canvas** to drag the page and
**Move Whole Line** for the deliberately separate, less-common geometry move.
Holding Ctrl/Command temporarily pans with the left mouse button from any tool,
and middle-drag also pans. Use Ctrl/Command + wheel to zoom.

Toggle **Transcription Mode** in the top toolbar, or press Ctrl/Command+T, to
switch between geometry assessment and distraction-free transcription review.
In transcription mode the line regions remain clickable even though their
geometry is hidden. Right-click a line for its context menu, including text
editing, isolated selection, centering, geometry-tool shortcuts, and copying the
PAGE `TextLine` ID. Press Up or Down on the canvas or in the transcription editor
to select the previous or next line in PAGE document order.

An active automatic correction shows a character-level comparison until it is
accepted or rejected. **Keep** accepts the already-applied correction and then
collapses the line to a neutral transcription row; **Reject** restores the
original line and also removes the comparison. Lines that have not been through
automatic correction are neutral from the outset. Press Enter to accept the
selected change or Backspace to reject it while the canvas has focus.

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

## Packaging and distribution

The project is licensed under [Apache License 2.0](LICENSE). CI runs privacy,
lint, type, and test checks on Python 3.11 and 3.13 across Windows, macOS, and
Linux. Alpha releases attach a wheel and source archive; see
[RELEASING.md](RELEASING.md) for the release process.

There is not yet a native desktop installer. Qt documents `pyside6-deploy` as
its supported cross-platform freezing path; application icons, native package
builds, signing/notarization, installer smoke tests, and bundled third-party
notices remain later release work. PySide6 is available under LGPLv3/GPLv3 or a
commercial Qt license, so distribution work must retain the applicable Qt
notices.

The validator bundles the official PRImA PAGE 2013 XSD. Strict validation reports
vendor-only Transkribus metadata; the separate editable-core result validates a
temporary clone with only the known `TranskribusMetadata` extension removed. The
real XML always retains that metadata.

---
Credits : Youssef Elkomy & Robert Turnbull in collaboration with MDAP (Melbourne Data Analytics Platform) 

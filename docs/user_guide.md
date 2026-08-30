# PAGE Line Editor User Guide

This guide is the canonical reference for user-facing tools, mouse gestures,
and keyboard shortcuts. Any change that adds, removes, or changes a user tool
or shortcut must update this file in the same change.

## Opening and saving a project

Choose **Open Project…** and select the separate image and PAGE XML folders.
The optional ground-truth Word file enables automatic correction. Choose an
audit/history folder outside the live XML folder so original XML and correction
reports remain separate.

The editor pairs JPEG or PNG images with XML files by filename. Changes remain
in memory until **Save**. Saving validates the PAGE XML, creates a timestamped
backup, and atomically replaces the source XML.

| Action | Shortcut |
| --- | --- |
| Open project | Ctrl/Command+O |
| Save current PAGE XML | Ctrl/Command+S |
| Undo | Ctrl/Command+Z |
| Redo | Platform-standard redo shortcut |
| Previous page | Page Up |
| Next page | Page Down |

## Work modes

**Geometry mode** shows the left tool palette, polygons, baselines, and vertex
handles. Use it to inspect or repair PAGE geometry.

**Transcription Mode** hides geometry and geometry-only tools while keeping each
line's invisible interior selectable. This provides a clear manuscript view for
transcription and correction assessment. Toggle it from the top toolbar or with
Ctrl/Command+T.

## Selecting and navigating lines

- Click a polygon interior, border, or baseline to select that TextLine.
- Clicking another line replaces the selection.
- Shift-click adds or removes a line from a multi-selection.
- Click the canvas background to clear the selection.
- Up selects the previous TextLine in PAGE document order.
- Down selects the next TextLine in PAGE document order.
- Navigation stops at the first and last line.
- Right-click a line to edit its transcription, select it alone, center it,
  switch to a geometry tool, or copy its PAGE TextLine ID.

## Left tool palette

| Tool | Shortcut | Use |
| --- | --- | --- |
| Pan Canvas | H | Drag the page without changing PAGE geometry. |
| Select / Edit | V | Select lines and drag individual polygon or baseline vertices. |
| Move Whole Line | M | Move a complete polygon and baseline together. |
| Add Vertex | A | Select a line, then click near the polygon or baseline segment that should receive a vertex. |
| Delete Vertex | D | Select a line, then click near the vertex to remove. Minimum shape sizes are enforced. |
| Replace Polygon | P | Click the new polygon points, then double-click or press Enter to finish. Press Escape to cancel. |
| Replace Baseline | B | Click the new baseline points, then double-click or press Enter to finish. Press Escape to cancel. |

Geometry edits are undoable. Invalid edits—such as self-intersecting polygons,
out-of-image points, or newly invalid baselines—are rejected with a status
message.

## Panning, zooming, and view controls

| Action | Shortcut or gesture |
| --- | --- |
| Temporarily pan from any tool | Hold Ctrl/Command and left-drag |
| Pan without changing tools | Middle-drag |
| Zoom at the pointer | Ctrl/Command+mouse wheel |
| Zoom in/out | Platform-standard zoom shortcuts or top toolbar |
| Fit page | F |
| Rotate left | `[` |
| Rotate right | `]` |
| Reset rotation | View menu |
| Toggle polygons, baselines, correction diff, or Unicode NFC normalization | View menu |
| Change System/Light/Dark theme | Theme selector in the top toolbar |

Rotation changes only the view; it does not rewrite PAGE coordinates.

## Editing transcriptions

Selecting a line opens an editor immediately below its lowest visible vertex.
The editor uses right-to-left layout for Arabic and scales its font and width to
the selected line. Manual edits support optional Unicode NFC normalization.

- Enter commits a manual transcription. If the line has an active automatic
  correction, Enter also accepts that correction.
- Escape discards uncommitted text and restores the last committed value.
- Up and Down commit the current edit before moving to the adjacent line.
- Backspace behaves normally while the text field has typing focus.

## Reviewing automatic correction

Run **Auto-correct current page** or **Auto-correct folder** from the top menu or
Review panel. Text and geometry corrections are applied in memory and remain
reversible until Save. The GitHub-style comparison highlights added characters
in green and strikes removed characters in red.

| Review action | Shortcut or control |
| --- | --- |
| Accept selected change | Enter/Return, or **Keep** |
| Reject selected change | Backspace while the canvas/line has focus, or **Reject / Revert** |
| Accept all page changes | **Keep all on page** |
| Reject all page changes | **Reject / revert all on page** |

An uncertain `EXTRA` is a pending deletion. Its text and bounding geometry stay
visible until it is accepted. Accepting it removes the TextLine from the active
page and the next Save removes its XML element. Rejecting it keeps the line.
Explicit correction-engine settings may still opt into automatic bulk deletion.

After a correction is accepted or rejected, its inline diff is hidden and the
line becomes neutral. The audit directory retains the untouched original XML,
JSON and HTML reports, and the decision manifest.

Automatic correction will not start over unsaved edits or a page with an
unfinished correction review. If a source XML changes while folder correction
is running, that page is skipped so the newer saved version is never replaced.

## Command-line correction reports

`align_report.py` runs in report-only mode by default. To write corrected XML,
provide an explicit `--corrected-dir`; it must be different from the source XML
folder. EXTRA lines are retained unless deletion is explicitly enabled with
`--delete-noise-extras` (high-confidence noise only) or
`--delete-all-extras` (all EXTRA lines). Keep reports, corrected output, and
source XML in separate directories.

## Important data behavior

- Images and XML always remain one-to-one and live in separate folders.
- Manuscript images, XML, ground truth, reports, and audit history must never be
  committed to the source repository.
- Closing, opening another project, or changing pages with unsaved work shows a
  dirty-state warning.
- Manual structural split and merge tools are not yet implemented.

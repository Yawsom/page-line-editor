# PAGE XML ground-truth alignment

Correct Transkribus PAGE XML transcriptions against a line-by-line Word ground truth. The tool aligns physical manuscript lines (not sentences), reports OCR and segmentation errors, and writes corrected PAGE XML that keeps the original bounding boxes and baselines.

It is built for medieval Arabic (and Coptic-script punctuation marks used in this witness). Matching uses `difflib` after Arabic-only normalisation, plus geometry so a junk line or a split box does not shift the rest of the page.

## Layout

```
ground_truth/       Word .docx (one paragraph per manuscript line, pages marked [93v])
transcribed_xml/    Transkribus PAGE XML (model output)
corrected_xml/      written by the tool
reports/            written by the tool (RTL HTML + alignment.json)
align_report.py     CLI
```

Folder structure is in git; file contents are not. Put your own Word document and PAGE XML in `ground_truth/` and `transcribed_xml/`.

Pair XML to Word by folio: `imageFilename="93v.jpg"` matches a `[93v]` paragraph in the .docx. Unpaired GT pages are listed in the report index.

## Setup

Python 3.10+ (tested on 3.14).

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Usage

From the project root:

```bash
python align_report.py
```

Defaults:

| Flag | Default |
|---|---|
| `--gt` | `ground_truth/S155-transcription.docx` |
| `--xml-dir` | `transcribed_xml` |
| `--out` | `reports` |
| `--corrected-dir` | `corrected_xml` |
| `--delete-all-extras` | off |

```bash
python align_report.py --no-xml                  # HTML/JSON report only
python align_report.py --xml-dir path/to/xml     # more Transkribus pages
python align_report.py --delete-all-extras       # also delete uncertain extras
```

Drop new PAGE XML files into `transcribed_xml/` named so the folio matches the Word header (`93v.jpg` ↔ `[93v]`). Re-run the command.

## What it does

**Word.** A paragraph matching `[93v]` / `[94r]` / `[1r]` starts a folio. Every other non-empty paragraph is one manuscript line. Special marks in the GT (`⦿`, `✢`, `✣`, `:`) are real text.

**PAGE XML.** Each `TextLine` keeps `Coords`, `Baseline`, and `Unicode`. Lines are ordered by baseline Y, not `readingOrder` (that attribute is not always 0-based).

**Alignment.**

1. Flag noise (narrow + short + digits/low Arabic), e.g. a margin folio number.
2. Merge XML fragments that share a baseline Y and whose joined text matches GT better than either fragment alone.
3. Sequence-align remaining XML lines to GT with Needleman–Wunsch, scoring pairs with `difflib.SequenceMatcher.ratio` (`autojunk=False`).
4. Character-level diff for the HTML report.

Normalisation (alef forms, tashkeel, `ى`/`ي`, punctuation) is **match-only**. The report and corrected XML show the original GT spelling.

## Status labels

| Status | Meaning |
|---|---|
| `MATCH` | Aligned, similarity ≥ 0.95 |
| `OCR` | Aligned 1:1, character differences |
| `MERGE` | Two XML boxes, one GT line |
| `SPLIT` | One XML box, two GT lines |
| `EXTRA` | XML line with no GT (ornament, margin number) |
| `MISSING` | GT line with no XML box (not invented) |

Typical extras are ornament OCR and margin folio numbers; a split manuscript line becomes `MERGE`.

## Outputs

**`reports/index.html`** — per-folio counts. Open a folio page for a right-to-left side-by-side diff (red = XML-only, green = GT-only).

**`reports/alignment.json`** — the same mapping, for later tooling.

**`corrected_xml/`** — Transkribus-style PAGE XML (one line, `standalone="yes"`):

- `MATCH` / `OCR`: replace `Unicode` with the GT line; keep coordinates and baseline
- `EXTRA`: delete lines independently flagged as noise; preserve uncertain extras
- `MERGE`: keep the wider box, union polygon + baseline, write the GT line
- reindex `readingOrder` on remaining lines
- leave the region-level `Unicode` empty, as Transkribus does

`MISSING` lines are skipped: there is no box to attach them to.
Use `--delete-all-extras` to restore aggressive deletion of every `EXTRA` line.

## Requirements

- `python-docx` to read the Word ground truth
- Standard library otherwise (`xml.etree`, `difflib`)

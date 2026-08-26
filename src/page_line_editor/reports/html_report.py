"""Small self-contained HTML reports derived from proposal data."""

from __future__ import annotations

import html
import re
from pathlib import Path

from page_line_editor.correction.models import (
    STATUSES,
    CharDiff,
    FolderCorrectionProposal,
    LineCorrectionProposal,
    PageCorrectionProposal,
)

CSS = """
:root { color-scheme: light dark; --rule:#8c8170; --ins:#a9d6ae; --del:#edaaa4; }
body { max-width:1100px; margin:auto; padding:1.5rem; font-family:"Noto Naskh Arabic",sans-serif; }
a { color:inherit; } table { width:100%; border-collapse:collapse; }
th,td { text-align:start; border-bottom:1px solid var(--rule); padding:.45rem; }
.record { border:1px solid var(--rule); border-radius:9px; padding:.8rem; margin:.8rem 0; }
.meta { font: .82rem system-ui,sans-serif; opacity:.78; }
.pair { display:grid; grid-template-columns:1fr 1fr; gap:1rem; font-size:1.15rem; }
.del { background:var(--del); text-decoration:line-through; } .ins { background:var(--ins); }
.badge { font:bold .75rem system-ui,sans-serif; border:1px solid currentColor;
         border-radius:1rem; padding:.1rem .45rem; }
@media(max-width:700px) { .pair { grid-template-columns:1fr; } }
"""


def _render_diffs(diffs: tuple[CharDiff, ...], side: str) -> str:
    parts: list[str] = []
    for diff in diffs:
        value = diff.before if side == "before" else diff.after
        if not value:
            continue
        escaped = html.escape(value)
        if diff.tag == "equal":
            parts.append(escaped)
        elif diff.tag == "replace":
            css_class = "del" if side == "before" else "ins"
            parts.append(f'<span class="{css_class}">{escaped}</span>')
        elif diff.tag == "delete" and side == "before":
            parts.append(f'<span class="del">{escaped}</span>')
        elif diff.tag == "insert" and side == "after":
            parts.append(f'<span class="ins">{escaped}</span>')
    return "".join(parts) or "—"


def _record_html(proposal: LineCorrectionProposal) -> str:
    before = (
        _render_diffs(proposal.char_diffs, "before")
        if proposal.char_diffs
        else html.escape(proposal.before_text or "—")
    )
    after = (
        _render_diffs(proposal.char_diffs, "after")
        if proposal.char_diffs
        else html.escape(proposal.after_text or "—")
    )
    ratio = "—" if proposal.ratio is None else f"{proposal.ratio:.3f}"
    applied = "applied" if proposal.automatically_applied else "report only"
    return f"""
<article class="record" id="{html.escape(proposal.record_key)}"
         data-record-key="{html.escape(proposal.record_key)}">
  <div class="meta"><span class="badge">{proposal.status.value}</span>
  · {html.escape(proposal.record_key)} · ratio {ratio} · {applied}</div>
  <div class="pair" dir="rtl">
    <div><small>Before</small><div>{before}</div></div>
    <div><small>After</small><div>{after}</div></div>
  </div>
</article>"""


def page_html(page: PageCorrectionProposal) -> str:
    records = "".join(_record_html(proposal) for proposal in page.proposals)
    title = page.folio or Path(page.xml_filename).stem
    return f"""<!doctype html>
<html lang="ar" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title><style>{CSS}</style></head>
<body><p><a href="../index.html">All pages</a></p>
<h1>{html.escape(title)}</h1><p>{html.escape(page.xml_filename)}</p>{records}</body></html>"""


def _safe_stem(filename: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", Path(filename).stem).strip("._")
    return stem or "page"


def index_html(folder: FolderCorrectionProposal) -> str:
    rows: list[str] = []
    for page in folder.pages:
        counts = {status: 0 for status in STATUSES}
        for proposal in page.proposals:
            counts[proposal.status.value] += 1
        cells = "".join(f"<td>{counts[status]}</td>" for status in STATUSES)
        filename = f"pages/{_safe_stem(page.xml_filename)}.html"
        label = page.folio or Path(page.xml_filename).stem
        rows.append(
            f'<tr><td><a href="{html.escape(filename)}">{html.escape(label)}</a></td>{cells}</tr>'
        )
    headings = "".join(f"<th>{status}</th>" for status in STATUSES)
    cancelled = (
        "<p>Run cancelled; this report contains partial results.</p>"
        if folder.cancelled
        else ""
    )
    return f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>PAGE correction report</title><style>{CSS}</style></head><body>
<h1>PAGE correction report</h1>{cancelled}<table><thead><tr><th>Page</th>{headings}</tr></thead>
<tbody>{''.join(rows)}</tbody></table></body></html>"""


def write_html_report(
    result: PageCorrectionProposal | FolderCorrectionProposal, destination: Path
) -> Path:
    folder = (
        result
        if isinstance(result, FolderCorrectionProposal)
        else FolderCorrectionProposal((result,))
    )
    destination = Path(destination)
    pages_directory = destination / "pages"
    pages_directory.mkdir(parents=True, exist_ok=True)
    (destination / "index.html").write_text(index_html(folder), encoding="utf-8")
    used: set[str] = set()
    for index, page in enumerate(folder.pages):
        stem = _safe_stem(page.xml_filename)
        if stem in used:
            stem = f"{stem}-{index + 1}"
        used.add(stem)
        (pages_directory / f"{stem}.html").write_text(page_html(page), encoding="utf-8")
    return destination / "index.html"

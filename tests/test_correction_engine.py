from __future__ import annotations

import json
from dataclasses import dataclass

import pytest

from page_line_editor.correction import (
    CancellationToken,
    CorrectionCancelled,
    CorrectionLine,
    CorrectionSettings,
    CorrectionStatus,
    GroundTruthLine,
    PageCorrectionInput,
    automatically_applied_states,
    normalize_for_match,
    propose_page,
    similarity,
)
from page_line_editor.reports import write_html_report, write_json_report


def line(
    line_id: str,
    text: str,
    *,
    x: int = 0,
    y: int = 0,
    width: int = 500,
    baseline: tuple[tuple[int, int], ...] | None = None,
    noise: bool | None = None,
) -> CorrectionLine:
    return CorrectionLine(
        line_id=line_id,
        text=text,
        polygon=((x, y), (x + width, y), (x + width, y + 20), (x, y + 20)),
        baseline=baseline if baseline is not None else ((x, y + 15), (x + width, y + 15)),
        noise=noise,
    )


def test_arabic_normalization_preserves_legacy_semantics() -> None:
    assert normalize_for_match("أَلسَّلامـة؟") == "السلامه"
    assert normalize_for_match("⦿ ✢ ✣ :") == "⦿✢✣:"
    assert similarity("سلام؟", "سلام") == 1.0
    assert similarity("⦿", "✢") < 1.0


def test_proposal_is_read_only_and_carries_reversible_applied_state(tmp_path) -> None:
    source = line("l1", "قديم")
    page = PageCorrectionInput("folio.xml", (source,), folio="1r")
    before_files = tuple(tmp_path.iterdir())

    result = propose_page(page, (GroundTruthLine(0, "جديد"),))

    assert page.lines == (source,)
    assert tuple(tmp_path.iterdir()) == before_files
    proposal = result.proposals[0]
    assert proposal.status is CorrectionStatus.OCR
    assert proposal.before[0].text == "قديم"
    assert proposal.after[0].text == "جديد"
    assert proposal.automatically_applied
    assert automatically_applied_states(result)["l1"].text == "جديد"
    assert automatically_applied_states(
        result, rejected_proposal_ids=(proposal.proposal_id,)
    )["l1"].text == "قديم"
    assert any(diff.tag == "replace" for diff in proposal.char_diffs)


def test_merge_keeps_member_baseline_point_order() -> None:
    left_baseline = ((0, 15), (20, 13), (40, 15))
    right_baseline = ((60, 16), (80, 12), (100, 16))
    page = PageCorrectionInput(
        "folio.xml",
        (
            line("l1", "world", x=0, width=40, baseline=left_baseline, noise=False),
            line("l2", "hello", x=60, width=40, baseline=right_baseline, noise=False),
        ),
    )

    result = propose_page(page, ("hello world",))
    proposal = result.proposals[0]

    assert proposal.status is CorrectionStatus.MERGE
    assert proposal.line_ids == ("l2", "l1")
    assert proposal.after[0].baseline == right_baseline + left_baseline
    assert proposal.after[1].deleted


def test_extras_are_pending_by_default_and_noise_deletion_is_explicit() -> None:
    uncertain = propose_page(
        PageCorrectionInput("a.xml", (line("real", "السلام عليكم ورحمة الله"),)), ()
    )
    assert uncertain.proposals[0].status is CorrectionStatus.EXTRA
    assert uncertain.proposals[0].actionable
    assert uncertain.proposals[0].after[0].deleted
    assert not uncertain.proposals[0].automatically_applied

    noise = propose_page(
        PageCorrectionInput("b.xml", (line("noise", "1", width=20),)), ()
    )
    assert noise.proposals[0].after[0].deleted
    assert not noise.proposals[0].automatically_applied
    opted_in = propose_page(
        PageCorrectionInput("c.xml", (line("noise", "1", width=20),)),
        (),
        CorrectionSettings(apply_noise_deletions=True),
    )
    assert opted_in.proposals[0].automatically_applied


def test_reports_are_keyed_by_filename_and_line_id(tmp_path) -> None:
    result = propose_page(
        PageCorrectionInput("folio.xml", (line("line-7", "النسخة القديمة"),)),
        ("النسخة الجديده",),
    )
    json_path = write_json_report(result, tmp_path / "alignment.json")
    index_path = write_html_report(result, tmp_path / "html")

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert "folio.xml::line-7" in payload["records"]
    assert "folio.xml::line-7" in payload["pages"][0]["records"]
    assert payload["pages"][0]["alignments"][0]["xml_ids"] == ["line-7"]
    page_html = (tmp_path / "html" / "pages" / "folio.html").read_text(
        encoding="utf-8"
    )
    assert 'data-record-key="folio.xml::line-7"' in page_html
    assert index_path.exists()


def test_pre_cancelled_token_stops_page_proposal() -> None:
    token = CancellationToken()
    token.cancel()
    with pytest.raises(CorrectionCancelled):
        propose_page(
            PageCorrectionInput("folio.xml", (line("l1", "old"),)),
            ("new",),
            cancel_token=token,
        )


@dataclass
class DuckLine:
    id: str
    current_text: str
    coords: list[tuple[int, int]]
    current_baseline: list[tuple[int, int]]


@dataclass
class DuckPage:
    filename: str
    lines: list[DuckLine]


def test_duck_typed_page_and_line_are_accepted() -> None:
    page = DuckPage(
        "duck.xml",
        [
            DuckLine(
                "d1",
                "النسخة القديمة",
                [(0, 0), (300, 0), (300, 20)],
                [(0, 15), (300, 15)],
            )
        ],
    )
    result = propose_page(page, ["النسخة الجديده"])
    assert result.proposals[0].record_key == "duck.xml::d1"
    assert result.proposals[0].after[0].text == "النسخة الجديده"

"""Character-level markup shared by the canvas and correction review dock."""

from __future__ import annotations

import html
from dataclasses import dataclass
from difflib import SequenceMatcher


@dataclass(frozen=True, slots=True)
class DiffSegment:
    kind: str
    text: str
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class TextDiff:
    before: tuple[DiffSegment, ...]
    after: tuple[DiffSegment, ...]

    @property
    def addition_ranges(self) -> tuple[tuple[int, int], ...]:
        return tuple(
            (segment.start, segment.end)
            for segment in self.after
            if segment.kind in {"insert", "replace"} and segment.end > segment.start
        )


def compare_text(before: str, after: str) -> TextDiff:
    before_segments: list[DiffSegment] = []
    after_segments: list[DiffSegment] = []
    matcher = SequenceMatcher(None, before, after, autojunk=False)
    for kind, before_start, before_end, after_start, after_end in matcher.get_opcodes():
        if before_end > before_start:
            before_segments.append(
                DiffSegment(kind, before[before_start:before_end], before_start, before_end)
            )
        if after_end > after_start:
            after_segments.append(
                DiffSegment(kind, after[after_start:after_end], after_start, after_end)
            )
    return TextDiff(tuple(before_segments), tuple(after_segments))


def rich_diff_text(
    segments: tuple[DiffSegment, ...],
    *,
    side: str,
    dark: bool,
) -> str:
    addition = "#2ea04366" if dark else "#abf2bc"
    deletion = "#f8514966" if dark else "#ff818266"
    parts: list[str] = ["<span style='white-space:pre'>"]
    for segment in segments:
        escaped = html.escape(segment.text).replace(" ", "&nbsp;")
        changed = (
            side == "after" and segment.kind in {"insert", "replace"}
        ) or (
            side == "before" and segment.kind in {"delete", "replace"}
        )
        if not changed:
            parts.append(escaped)
        elif side == "before":
            parts.append(
                f"<span style='background-color:{deletion};text-decoration:line-through;"
                f"font-weight:600'>{escaped}</span>"
            )
        else:
            parts.append(
                f"<span style='background-color:{addition};font-weight:600'>{escaped}</span>"
            )
    parts.append("</span>")
    return "".join(parts)


__all__ = ["DiffSegment", "TextDiff", "compare_text", "rich_diff_text"]

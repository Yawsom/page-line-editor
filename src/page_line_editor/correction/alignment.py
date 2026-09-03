"""Pure legacy-compatible line alignment.

Nothing in this module parses or writes PAGE XML.  It operates exclusively on
immutable snapshots, which keeps it safe to run in a background worker.
"""

from __future__ import annotations

import statistics
from collections.abc import Sequence
from dataclasses import dataclass, replace
from difflib import SequenceMatcher

from .cancellation import CancellationToken
from .models import (
    BoundingBox,
    CharDiff,
    CorrectionLine,
    CorrectionStatus,
    GroundTruthLine,
    Point,
)
from .normalization import (
    DIGIT_RE,
    arabic_letter_ratio,
    digit_ratio,
    normalize_for_display,
    similarity,
)

GAP_COST = 0.52
MERGE_GAP_COST = 0.18
MATCH_FLOOR = 0.42
OCR_RATIO = 0.95
NOISE_WIDTH = 150
NOISE_LEN = 10
MERGE_Y_FRAC = 0.35
MERGE_Y_MIN = 25.0
JOIN_IMPROVE = 0.06


@dataclass(frozen=True, slots=True)
class AlignedLines:
    status: CorrectionStatus
    lines: tuple[CorrectionLine, ...]
    ground_truth: tuple[GroundTruthLine, ...]
    before_text: str
    after_text: str | None
    ratio: float | None
    bbox: BoundingBox | None
    baseline_y: float | None
    flags: tuple[str, ...]
    char_diffs: tuple[CharDiff, ...]


def is_noise_line(line: CorrectionLine) -> bool:
    """Return whether noise line."""
    if line.noise is not None:
        return line.noise
    text = line.text.strip()
    if not text:
        return True
    short = len(text) < NOISE_LEN
    narrow = line.bbox.width < NOISE_WIDTH
    arabic_ratio = arabic_letter_ratio(text)
    number_ratio = digit_ratio(text)
    if narrow and short and (arabic_ratio < 0.5 or number_ratio > 0.2 or DIGIT_RE.search(text)):
        return True
    if short and arabic_ratio < 0.4:
        return True
    return number_ratio >= 0.4 and short


def _with_noise(line: CorrectionLine) -> CorrectionLine:
    """Return a line with an inferred noise classification."""
    return line if line.noise is not None else replace(line, noise=is_noise_line(line))


def _median_spacing(lines: Sequence[CorrectionLine]) -> float:
    """Return the median vertical spacing between adjacent lines."""
    ys = [line.baseline_y for line in lines]
    distances = [
        right - left for left, right in zip(ys, ys[1:], strict=False) if right - left > 1
    ]
    return float(statistics.median(distances)) if distances else 60.0


def _complementary_x(left: CorrectionLine, right: CorrectionLine) -> bool:
    """Return whether two lines occupy complementary horizontal spans."""
    overlap = min(left.bbox.x_max, right.bbox.x_max) - max(left.bbox.x_min, right.bbox.x_min)
    min_width = min(left.bbox.width, right.bbox.width) or 1
    return overlap <= 0 or overlap / min_width < 0.25


def rtl_order(lines: Sequence[CorrectionLine]) -> tuple[CorrectionLine, ...]:
    """Return lines sorted in right-to-left visual order."""
    return tuple(sorted(lines, key=lambda line: -line.bbox.x_max))


def join_rtl_text(lines: Sequence[CorrectionLine]) -> str:
    """Return non-empty line text joined in right-to-left order."""
    return " ".join(line.text.strip() for line in rtl_order(lines) if line.text.strip())


def _merge_lines(lines: Sequence[CorrectionLine]) -> CorrectionLine:
    """Merge lines."""
    ordered = rtl_order(lines)
    box = ordered[0].bbox
    for line in ordered[1:]:
        box = box.union(line.bbox)
    polygon: tuple[Point, ...] = (
        (box.x_min, box.y_min),
        (box.x_max, box.y_min),
        (box.x_max, box.y_max),
        (box.x_min, box.y_max),
    )
    return CorrectionLine(
        line_id=ordered[0].line_id,
        text=join_rtl_text(ordered),
        polygon=polygon,
        baseline=tuple(point for line in ordered for point in line.baseline),
        source_index=min(line.source_index for line in ordered),
        region_id=ordered[0].region_id,
        noise=False,
        merged_from=tuple(line.line_id for line in ordered),
    )


def apply_geometric_merges(
    lines: Sequence[CorrectionLine],
    ground_truth_texts: Sequence[str],
    cancel_token: CancellationToken,
) -> tuple[CorrectionLine, ...]:
    """Apply geometric merges."""
    if len(lines) < 2:
        return tuple(lines)
    spacing = _median_spacing(lines)
    y_threshold = max(MERGE_Y_MIN, MERGE_Y_FRAC * spacing)
    result: list[CorrectionLine] = []
    index = 0
    while index < len(lines):
        cancel_token.raise_if_cancelled()
        current = lines[index]
        if (
            index + 1 < len(lines)
            and not is_noise_line(current)
            and not is_noise_line(lines[index + 1])
            and abs(lines[index + 1].baseline_y - current.baseline_y) <= y_threshold
            and _complementary_x(current, lines[index + 1])
        ):
            following = lines[index + 1]
            joined = join_rtl_text((current, following))
            solo = max(
                max((similarity(current.text, text) for text in ground_truth_texts), default=0.0),
                max((similarity(following.text, text) for text in ground_truth_texts), default=0.0),
            )
            joined_best = max(
                (similarity(joined, text) for text in ground_truth_texts), default=0.0
            )
            if joined_best >= solo + JOIN_IMPROVE:
                result.append(_merge_lines((current, following)))
                index += 2
                continue
        result.append(current)
        index += 1
    return tuple(result)


def _pair_cost(before: str, after: str) -> float:
    """Return the dynamic-programming cost of one alignment pair."""
    ratio = similarity(before, after)
    if ratio < MATCH_FLOOR:
        return 1.0 + (MATCH_FLOOR - ratio)
    return 1.0 - ratio


def _join_improves(left: CorrectionLine, right: CorrectionLine, after: str) -> bool:
    """Return whether joining two XML lines improves the target match."""
    if is_noise_line(left) or is_noise_line(right):
        return False
    solo = max(similarity(left.text, after), similarity(right.text, after))
    return similarity(join_rtl_text((left, right)), after) >= solo + JOIN_IMPROVE


def _gt_join_improves(
    before: str, left: GroundTruthLine, right: GroundTruthLine
) -> bool:
    """Return whether joining ground-truth lines improves the match."""
    solo = max(similarity(before, left.text), similarity(before, right.text))
    return similarity(before, f"{left.text} {right.text}") >= solo + JOIN_IMPROVE


def _char_diffs(before: str, after: str) -> tuple[CharDiff, ...]:
    """Return character-level differences between normalized strings."""
    left = normalize_for_display(before)
    right = normalize_for_display(after)
    return tuple(
        CharDiff(tag, left[i1:i2], right[j1:j2])
        for tag, i1, i2, j1, j2 in SequenceMatcher(
            a=left, b=right, autojunk=False
        ).get_opcodes()
    )


def _flags(lines: Sequence[CorrectionLine]) -> tuple[str, ...]:
    """Return diagnostic flags inferred from the aligned lines."""
    flags: set[str] = set()
    for line in lines:
        if is_noise_line(line):
            flags.add("noise")
        if line.bbox.width < NOISE_WIDTH:
            flags.add("narrow")
        if len(line.text.strip()) < NOISE_LEN:
            flags.add("short")
        if line.merged_from:
            flags.add("geom_merge")
    return tuple(sorted(flags))


def _make_alignment(
    lines: Sequence[CorrectionLine], ground_truth: Sequence[GroundTruthLine]
) -> AlignedLines:
    """Build an alignment record from source and ground-truth lines."""
    before = lines[0].text if len(lines) == 1 else join_rtl_text(lines) if lines else ""
    after = " ".join(line.text for line in ground_truth) if ground_truth else None
    ratio = similarity(before, after) if lines and ground_truth and after is not None else None
    geometric_merge = any(line.merged_from for line in lines)
    if lines and not ground_truth:
        status = CorrectionStatus.EXTRA
    elif ground_truth and not lines:
        status = CorrectionStatus.MISSING
    elif len(lines) > 1 or geometric_merge:
        status = CorrectionStatus.MERGE
    elif len(ground_truth) > 1:
        status = CorrectionStatus.SPLIT
    elif ratio is not None and ratio >= OCR_RATIO:
        status = CorrectionStatus.MATCH
    else:
        status = CorrectionStatus.OCR

    bbox: BoundingBox | None = None
    baseline_y: float | None = None
    if lines:
        bbox = lines[0].bbox
        for line in lines[1:]:
            bbox = bbox.union(line.bbox)
        baseline_y = statistics.mean(line.baseline_y for line in lines)
    return AlignedLines(
        status=status,
        lines=tuple(lines),
        ground_truth=tuple(ground_truth),
        before_text=before,
        after_text=after,
        ratio=ratio,
        bbox=bbox,
        baseline_y=baseline_y,
        flags=_flags(lines),
        char_diffs=_char_diffs(before, after) if before and after else (),
    )


def align_lines(
    lines: Sequence[CorrectionLine],
    ground_truth: Sequence[GroundTruthLine],
    cancel_token: CancellationToken,
) -> tuple[AlignedLines, ...]:
    """Align XML and ground-truth lines using the legacy dynamic program."""

    source = tuple(_with_noise(line) for line in lines)
    target = tuple(ground_truth)
    n, m = len(source), len(target)
    infinity = 10**6
    cost = [[float(infinity)] * (m + 1) for _ in range(n + 1)]
    back: list[list[tuple[str, int, int]]] = [[("", 0, 0)] * (m + 1) for _ in range(n + 1)]
    cost[0][0] = 0.0
    for i in range(1, n + 1):
        cost[i][0] = i * GAP_COST
        back[i][0] = ("extra", i - 1, 0)
    for j in range(1, m + 1):
        cost[0][j] = j * GAP_COST
        back[0][j] = ("missing", 0, j - 1)

    for i in range(1, n + 1):
        cancel_token.raise_if_cancelled()
        for j in range(1, m + 1):
            candidate = cost[i - 1][j - 1] + _pair_cost(source[i - 1].text, target[j - 1].text)
            operation = ("match", i - 1, j - 1)
            extra = cost[i - 1][j] + GAP_COST
            if extra < candidate:
                candidate, operation = extra, ("extra", i - 1, j)
            missing = cost[i][j - 1] + GAP_COST
            if missing < candidate:
                candidate, operation = missing, ("missing", i, j - 1)
            if i >= 2 and _join_improves(source[i - 2], source[i - 1], target[j - 1].text):
                merged = join_rtl_text(source[i - 2 : i])
                merge_cost = (
                    cost[i - 2][j - 1]
                    + _pair_cost(merged, target[j - 1].text)
                    + MERGE_GAP_COST
                )
                if merge_cost < candidate:
                    candidate, operation = merge_cost, ("merge_xml", i - 2, j - 1)
            if j >= 2 and _gt_join_improves(source[i - 1].text, target[j - 2], target[j - 1]):
                combined = f"{target[j - 2].text} {target[j - 1].text}"
                split_cost = (
                    cost[i - 1][j - 2]
                    + _pair_cost(source[i - 1].text, combined)
                    + MERGE_GAP_COST
                )
                if split_cost < candidate:
                    candidate, operation = split_cost, ("split_xml", i - 1, j - 2)
            cost[i][j] = candidate
            back[i][j] = operation

    aligned: list[AlignedLines] = []
    i, j = n, m
    while i > 0 or j > 0:
        cancel_token.raise_if_cancelled()
        operation_name, _, _ = back[i][j]
        if operation_name == "match":
            aligned.append(_make_alignment((source[i - 1],), (target[j - 1],)))
            i, j = i - 1, j - 1
        elif operation_name == "extra":
            aligned.append(_make_alignment((source[i - 1],), ()))
            i -= 1
        elif operation_name == "missing":
            aligned.append(_make_alignment((), (target[j - 1],)))
            j -= 1
        elif operation_name == "merge_xml":
            aligned.append(_make_alignment(source[i - 2 : i], (target[j - 1],)))
            i, j = i - 2, j - 1
        elif operation_name == "split_xml":
            aligned.append(_make_alignment((source[i - 1],), target[j - 2 : j]))
            i, j = i - 1, j - 2
        else:  # defensive: a malformed backtrace must not loop forever
            raise RuntimeError(f"Invalid alignment backtrace at {i}, {j}")
    aligned.reverse()
    return tuple(aligned)


def convex_hull(points: Sequence[Point]) -> tuple[Point, ...]:
    """Return the convex hull enclosing the supplied points."""
    unique = sorted(set(points))
    if len(unique) <= 2:
        return tuple(unique)

    def cross(origin: Point, left: Point, right: Point) -> int:
        """Return the orientation cross product used by the hull algorithm."""
        return (left[0] - origin[0]) * (right[1] - origin[1]) - (
            left[1] - origin[1]
        ) * (right[0] - origin[0])

    lower: list[Point] = []
    for point in unique:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], point) <= 0:
            lower.pop()
        lower.append(point)
    upper: list[Point] = []
    for point in reversed(unique):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], point) <= 0:
            upper.pop()
        upper.append(point)
    return tuple(lower[:-1] + upper[:-1])


def connected_baselines(lines: Sequence[CorrectionLine]) -> tuple[Point, ...]:
    """Concatenate member baselines while preserving every polyline's order.

    The legacy writer sorted all points by x/y, which can scramble a curved or
    right-to-left polyline.  Member ordering is geometric, but points inside
    each member are never sorted or deduplicated.
    """

    usable = tuple(line for line in lines if line.baseline)
    if not usable:
        return ()

    # Text is joined in right-to-left reading order, but PAGE baseline points
    # describe a geometric stroke.  Joining left-to-right point sequences in
    # RTL text order creates a long return stroke (the visible "double
    # underline" reported in #1).  Follow the direction encoded by the source
    # polylines and preserve every member's internal point order.
    direction = sum(line.baseline[-1][0] - line.baseline[0][0] for line in usable)
    if direction >= 0:
        ordered = sorted(usable, key=lambda line: (line.baseline[0][0], line.source_index))
    else:
        ordered = sorted(usable, key=lambda line: (-line.baseline[0][0], line.source_index))
    return tuple(point for line in ordered for point in line.baseline)

#!/usr/bin/env python3
"""Align Transkribus PAGE XML lines with Word ground-truth lines and write a report."""

from __future__ import annotations

import argparse
import html
import json
import re
import statistics
import sys
import unicodedata
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path

from docx import Document

PAGE_NS_URI = "http://schema.primaresearch.org/PAGE/gts/pagecontent/2013-07-15"
PAGE_NS = {"p": PAGE_NS_URI}
FOLIO_RE = re.compile(r"^\[(\d+[rv])\]$")
READING_ORDER_RE = re.compile(r"readingOrder\s*\{index:\s*\d+;\}")

TASHKEEL_RE = re.compile(r"[\u064B-\u065F\u0670]")
ALEF_RE = re.compile(r"[أإآٱ]")
PUNCT_RE = re.compile(r"[⦿✢✣.:،؛!?()«»\"'،\-–—_/\\]+")
WHITESPACE_RE = re.compile(r"\s+")
ARABIC_LETTER_RE = re.compile(r"[\u0621-\u064A\u0671-\u06D3]")
DIGIT_RE = re.compile(r"[0-9٠-٩]")

# DP minimises (1 - ratio). A gap must be cheaper than a bad match, costlier than OCR.
GAP_COST = 0.52
MERGE_GAP_COST = 0.18  # extra cost for 2-to-1 / 1-to-2 so 1-to-1 is preferred when equal
MATCH_FLOOR = 0.42  # below this, treat as a gap rather than a pair
OCR_RATIO = 0.95
NOISE_WIDTH = 150
NOISE_LEN = 10
MERGE_Y_FRAC = 0.35
MERGE_Y_MIN = 25.0
JOIN_IMPROVE = 0.06

STATUSES = ("MATCH", "OCR", "MERGE", "SPLIT", "EXTRA", "MISSING")


@dataclass
class BBox:
    x_min: int
    y_min: int
    x_max: int
    y_max: int

    @property
    def width(self) -> int:
        return self.x_max - self.x_min

    @property
    def height(self) -> int:
        return self.y_max - self.y_min

    def union(self, other: BBox) -> BBox:
        return BBox(
            min(self.x_min, other.x_min),
            min(self.y_min, other.y_min),
            max(self.x_max, other.x_max),
            max(self.y_max, other.y_max),
        )


@dataclass
class XmlLine:
    ids: list[str]
    text: str
    baseline_y: float
    bbox: BBox
    source_index: int
    noise: bool = False
    merged_from: list[str] = field(default_factory=list)

    @property
    def width(self) -> int:
        return self.bbox.width

    @property
    def id_label(self) -> str:
        return " + ".join(self.ids)


@dataclass
class GtLine:
    index: int
    text: str


@dataclass
class CharSpan:
    tag: str  # equal | replace | delete | insert
    xml: str
    gt: str


@dataclass
class Alignment:
    status: str
    xml_ids: list[str]
    xml_text: str
    gt_index: int | None
    gt_text: str | None
    ratio: float | None
    baseline_y: float | None
    bbox: dict | None
    flags: list[str]
    char_spans: list[CharSpan] = field(default_factory=list)


@dataclass
class PageResult:
    folio: str
    xml_path: str | None
    image_filename: str | None
    gt_line_count: int
    xml_line_count: int
    alignments: list[Alignment]
    unpaired: bool = False
    note: str = ""


def normalize_for_match(text: str) -> str:
    """Aggressive Arabic normalize used only for similarity scoring."""
    text = unicodedata.normalize("NFC", text or "")
    text = TASHKEEL_RE.sub("", text)
    text = text.replace("\u0640", "")  # tatweel
    text = ALEF_RE.sub("ا", text)
    text = text.replace("ى", "ي").replace("ئ", "ي").replace("ؤ", "و")
    text = text.replace("ة", "ه")
    text = PUNCT_RE.sub("", text)
    text = WHITESPACE_RE.sub("", text)
    return text


def normalize_for_display(text: str) -> str:
    return WHITESPACE_RE.sub(" ", (text or "").strip())


def similarity(a: str, b: str) -> float:
    na, nb = normalize_for_match(a), normalize_for_match(b)
    if not na and not nb:
        return 1.0
    if not na or not nb:
        return 0.0
    return SequenceMatcher(a=na, b=nb, autojunk=False).ratio()


def arabic_letter_ratio(text: str) -> float:
    if not text:
        return 0.0
    letters = len(ARABIC_LETTER_RE.findall(text))
    return letters / max(len(text.replace(" ", "")), 1)


def digit_ratio(text: str) -> float:
    compact = (text or "").replace(" ", "")
    if not compact:
        return 0.0
    return len(DIGIT_RE.findall(compact)) / len(compact)


def is_noise_line(line: XmlLine) -> bool:
    text = line.text.strip()
    if not text:
        return True
    short = len(text) < NOISE_LEN
    narrow = line.width < NOISE_WIDTH
    ar = arabic_letter_ratio(text)
    dr = digit_ratio(text)
    if narrow and short and (ar < 0.5 or dr > 0.2 or DIGIT_RE.search(text)):
        return True
    if short and ar < 0.4:
        return True
    if dr >= 0.4 and short:
        return True
    return False


def parse_points(points: str | None) -> list[tuple[int, int]]:
    if not points:
        return []
    out: list[tuple[int, int]] = []
    for token in points.split():
        if "," not in token:
            continue
        x_s, y_s = token.split(",", 1)
        try:
            out.append((int(float(x_s)), int(float(y_s))))
        except ValueError:
            continue
    return out


def line_text(elem: ET.Element) -> str:
    unicode_el = elem.find("p:TextEquiv/p:Unicode", PAGE_NS)
    if unicode_el is not None and unicode_el.text:
        return unicode_el.text
    return ""


def parse_page_xml(path: Path) -> tuple[str, str | None, list[XmlLine]]:
    tree = ET.parse(path)
    root = tree.getroot()
    page = root.find("p:Page", PAGE_NS)
    if page is None:
        raise ValueError(f"No Page element in {path}")
    image_filename = page.get("imageFilename")
    folio = Path(image_filename).stem if image_filename else path.stem.replace("transkribus-", "")
    lines: list[XmlLine] = []
    for idx, elem in enumerate(page.findall(".//p:TextLine", PAGE_NS)):
        coords_el = elem.find("p:Coords", PAGE_NS)
        baseline_el = elem.find("p:Baseline", PAGE_NS)
        # Coords/Baseline are empty elements; do not use truthiness on them.
        coords = parse_points(None if coords_el is None else coords_el.get("points"))
        baseline = parse_points(None if baseline_el is None else baseline_el.get("points"))
        if coords:
            xs = [p[0] for p in coords]
            ys = [p[1] for p in coords]
            bbox = BBox(min(xs), min(ys), max(xs), max(ys))
        else:
            bbox = BBox(0, 0, 0, 0)
        if baseline:
            baseline_y = statistics.mean(p[1] for p in baseline)
        else:
            baseline_y = (bbox.y_min + bbox.y_max) / 2
        line = XmlLine(
            ids=[elem.get("id") or f"line_{idx}"],
            text=line_text(elem),
            baseline_y=baseline_y,
            bbox=bbox,
            source_index=idx,
        )
        line.noise = is_noise_line(line)
        lines.append(line)
    lines.sort(key=lambda ln: (ln.baseline_y, ln.bbox.x_min, ln.source_index))
    return folio, image_filename, lines


def parse_ground_truth(path: Path) -> dict[str, list[GtLine]]:
    document = Document(str(path))
    pages: dict[str, list[GtLine]] = {}
    current: str | None = None
    for para in document.paragraphs:
        text = (para.text or "").strip()
        if not text:
            continue
        header = FOLIO_RE.match(text)
        if header:
            current = header.group(1)
            pages.setdefault(current, [])
            continue
        if current is None:
            continue
        pages[current].append(GtLine(index=len(pages[current]), text=text))
    return pages


def median_spacing(lines: list[XmlLine]) -> float:
    ys = [ln.baseline_y for ln in lines]
    diffs = [b - a for a, b in zip(ys, ys[1:]) if b - a > 1]
    if not diffs:
        return 60.0
    return float(statistics.median(diffs))


def complementary_x(a: XmlLine, b: XmlLine) -> bool:
    overlap = min(a.bbox.x_max, b.bbox.x_max) - max(a.bbox.x_min, b.bbox.x_min)
    min_w = min(a.width, b.width) or 1
    if overlap <= 0:
        return True
    return (overlap / min_w) < 0.25


def join_rtl_text(lines: list[XmlLine]) -> str:
    ordered = sorted(lines, key=lambda ln: -ln.bbox.x_max)
    return " ".join(ln.text.strip() for ln in ordered if ln.text.strip())


def merge_xml_lines(members: list[XmlLine]) -> XmlLine:
    members_sorted = sorted(members, key=lambda ln: -ln.bbox.x_max)
    bbox = members_sorted[0].bbox
    for extra in members_sorted[1:]:
        bbox = bbox.union(extra.bbox)
    ids = [i for ln in members_sorted for i in ln.ids]
    return XmlLine(
        ids=ids,
        text=join_rtl_text(members),
        baseline_y=statistics.mean(ln.baseline_y for ln in members),
        bbox=bbox,
        source_index=min(ln.source_index for ln in members),
        noise=False,
        merged_from=ids[:],
    )


def apply_geometric_merges(lines: list[XmlLine], gt_texts: list[str]) -> list[XmlLine]:
    if len(lines) < 2:
        return lines
    spacing = median_spacing(lines)
    y_thresh = max(MERGE_Y_MIN, MERGE_Y_FRAC * spacing)
    out: list[XmlLine] = []
    i = 0
    while i < len(lines):
        cur = lines[i]
        if (
            i + 1 < len(lines)
            and not cur.noise
            and not lines[i + 1].noise
            and abs(lines[i + 1].baseline_y - cur.baseline_y) <= y_thresh
            and complementary_x(cur, lines[i + 1])
        ):
            nxt = lines[i + 1]
            joined = join_rtl_text([cur, nxt])
            solo = max(
                (similarity(cur.text, gt) for gt in gt_texts),
                default=0.0,
            )
            solo = max(solo, max((similarity(nxt.text, gt) for gt in gt_texts), default=0.0))
            joined_best = max((similarity(joined, gt) for gt in gt_texts), default=0.0)
            if joined_best >= solo + JOIN_IMPROVE:
                out.append(merge_xml_lines([cur, nxt]))
                i += 2
                continue
        out.append(cur)
        i += 1
    return out


def pair_cost(xml_text: str, gt_text: str) -> float:
    ratio = similarity(xml_text, gt_text)
    if ratio < MATCH_FLOOR:
        return 1.0 + (MATCH_FLOOR - ratio)
    return 1.0 - ratio


def join_improves(left: XmlLine, right: XmlLine, gt_text: str) -> bool:
    if left.noise or right.noise:
        return False
    joined = join_rtl_text([left, right])
    solo = max(similarity(left.text, gt_text), similarity(right.text, gt_text))
    return similarity(joined, gt_text) >= solo + JOIN_IMPROVE


def gt_join_improves(xml_text: str, left: GtLine, right: GtLine) -> bool:
    combined = f"{left.text} {right.text}"
    solo = max(similarity(xml_text, left.text), similarity(xml_text, right.text))
    return similarity(xml_text, combined) >= solo + JOIN_IMPROVE


def dp_align(xml_lines: list[XmlLine], gt_lines: list[GtLine]) -> list[Alignment]:
    n, m = len(xml_lines), len(gt_lines)
    inf = 10**6
    cost = [[inf] * (m + 1) for _ in range(n + 1)]
    back: list[list[tuple[str, int, int]]] = [[("", 0, 0)] * (m + 1) for _ in range(n + 1)]
    cost[0][0] = 0.0
    for i in range(1, n + 1):
        cost[i][0] = i * GAP_COST
        back[i][0] = ("extra", i - 1, 0)
    for j in range(1, m + 1):
        cost[0][j] = j * GAP_COST
        back[0][j] = ("missing", 0, j - 1)

    def xml_text(i0: int, i1: int) -> str:
        chunk = xml_lines[i0:i1]
        if len(chunk) == 1:
            return chunk[0].text
        return join_rtl_text(chunk)

    def gt_text(j0: int, j1: int) -> str:
        return " ".join(g.text for g in gt_lines[j0:j1])

    for i in range(1, n + 1):
        for j in range(1, m + 1):
            # 1-to-1
            c = cost[i - 1][j - 1] + pair_cost(xml_lines[i - 1].text, gt_lines[j - 1].text)
            op = ("match", i - 1, j - 1)
            # extra xml
            c_extra = cost[i - 1][j] + GAP_COST
            if c_extra < c:
                c, op = c_extra, ("extra", i - 1, j)
            # missing gt
            c_miss = cost[i][j - 1] + GAP_COST
            if c_miss < c:
                c, op = c_miss, ("missing", i, j - 1)
            # 2 xml -> 1 gt, only when concatenating actually helps
            if i >= 2 and join_improves(xml_lines[i - 2], xml_lines[i - 1], gt_lines[j - 1].text):
                merged = xml_text(i - 2, i)
                c_merge = cost[i - 2][j - 1] + pair_cost(merged, gt_lines[j - 1].text) + MERGE_GAP_COST
                if c_merge < c:
                    c, op = c_merge, ("merge_xml", i - 2, j - 1)
            # 1 xml -> 2 gt
            if j >= 2 and gt_join_improves(xml_lines[i - 1].text, gt_lines[j - 2], gt_lines[j - 1]):
                combined = gt_text(j - 2, j)
                c_split = cost[i - 1][j - 2] + pair_cost(xml_lines[i - 1].text, combined) + MERGE_GAP_COST
                if c_split < c:
                    c, op = c_split, ("split_xml", i - 1, j - 2)
            cost[i][j] = c
            back[i][j] = op

    aligned: list[Alignment] = []
    i, j = n, m
    while i > 0 or j > 0:
        op, pi, pj = back[i][j]
        if op == "match":
            xml_ln = xml_lines[i - 1]
            gt_ln = gt_lines[j - 1]
            aligned.append(make_alignment([xml_ln], [gt_ln]))
            i, j = i - 1, j - 1
        elif op == "extra":
            aligned.append(make_alignment([xml_lines[i - 1]], []))
            i -= 1
        elif op == "missing":
            aligned.append(make_alignment([], [gt_lines[j - 1]]))
            j -= 1
        elif op == "merge_xml":
            aligned.append(make_alignment(xml_lines[i - 2 : i], [gt_lines[j - 1]]))
            i -= 2
            j -= 1
        elif op == "split_xml":
            aligned.append(make_alignment([xml_lines[i - 1]], gt_lines[j - 2 : j]))
            i -= 1
            j -= 2
        else:
            break
    aligned.reverse()
    return aligned


def char_spans(xml_text: str, gt_text: str) -> list[CharSpan]:
    a = normalize_for_display(xml_text)
    b = normalize_for_display(gt_text)
    sm = SequenceMatcher(a=a, b=b, autojunk=False)
    spans: list[CharSpan] = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        spans.append(CharSpan(tag=tag, xml=a[i1:i2], gt=b[j1:j2]))
    return spans


def flags_for(xml_lines: list[XmlLine]) -> list[str]:
    flags: list[str] = []
    for ln in xml_lines:
        if ln.noise:
            flags.append("noise")
        if ln.width < NOISE_WIDTH:
            flags.append("narrow")
        if len(ln.text.strip()) < NOISE_LEN:
            flags.append("short")
        if ln.merged_from:
            flags.append("geom_merge")
    return sorted(set(flags))


def classify(xml_lines: list[XmlLine], gt_lines: list[GtLine], ratio: float | None) -> str:
    if xml_lines and not gt_lines:
        return "EXTRA"
    if gt_lines and not xml_lines:
        return "MISSING"
    geom_merged = any(ln.merged_from or len(ln.ids) > 1 for ln in xml_lines)
    if len(xml_lines) > 1 or geom_merged:
        return "MERGE"
    if len(gt_lines) > 1:
        return "SPLIT"
    if ratio is not None and ratio >= OCR_RATIO:
        return "MATCH"
    return "OCR"


def make_alignment(xml_lines: list[XmlLine], gt_lines: list[GtLine]) -> Alignment:
    xml_text = xml_lines[0].text if len(xml_lines) == 1 else join_rtl_text(xml_lines) if xml_lines else ""
    if xml_lines and any(ln.merged_from for ln in xml_lines) and len(xml_lines) == 1:
        xml_text = xml_lines[0].text
    gt_text = " ".join(g.text for g in gt_lines) if gt_lines else None
    ratio = similarity(xml_text, gt_text) if xml_lines and gt_lines else None
    bbox = None
    baseline_y = None
    if xml_lines:
        box = xml_lines[0].bbox
        for extra in xml_lines[1:]:
            box = box.union(extra.bbox)
        bbox = asdict(box)
        baseline_y = statistics.mean(ln.baseline_y for ln in xml_lines)
    ids = [i for ln in xml_lines for i in ln.ids]
    spans = char_spans(xml_text, gt_text or "") if xml_text and gt_text else []
    return Alignment(
        status=classify(xml_lines, gt_lines, ratio),
        xml_ids=ids,
        xml_text=xml_text,
        gt_index=gt_lines[0].index if gt_lines else None,
        gt_text=gt_text,
        ratio=ratio,
        baseline_y=baseline_y,
        bbox=bbox,
        flags=flags_for(xml_lines),
        char_spans=spans,
    )


def align_page(folio: str, xml_path: Path | None, image_filename: str | None,
               xml_lines: list[XmlLine], gt_lines: list[GtLine]) -> PageResult:
    gt_texts = [g.text for g in gt_lines]
    working = apply_geometric_merges(xml_lines, gt_texts)
    alignments = dp_align(working, gt_lines)
    return PageResult(
        folio=folio,
        xml_path=str(xml_path) if xml_path else None,
        image_filename=image_filename,
        gt_line_count=len(gt_lines),
        xml_line_count=len(xml_lines),
        alignments=alignments,
    )


def qname(tag: str) -> str:
    return f"{{{PAGE_NS_URI}}}{tag}"


def format_points(points: list[tuple[int, int]]) -> str:
    return " ".join(f"{x},{y}" for x, y in points)


def convex_hull(points: list[tuple[int, int]]) -> list[tuple[int, int]]:
    pts = sorted(set(points))
    if len(pts) <= 2:
        return pts

    def cross(o: tuple[int, int], a: tuple[int, int], b: tuple[int, int]) -> int:
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower: list[tuple[int, int]] = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper: list[tuple[int, int]] = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def elem_points(elem: ET.Element, tag: str) -> list[tuple[int, int]]:
    child = elem.find(f"p:{tag}", PAGE_NS)
    if child is None:
        return []
    return parse_points(child.get("points"))


def elem_width(elem: ET.Element) -> int:
    pts = elem_points(elem, "Coords")
    if not pts:
        return 0
    return max(p[0] for p in pts) - min(p[0] for p in pts)


def set_points(elem: ET.Element, tag: str, points: list[tuple[int, int]]) -> None:
    child = elem.find(f"p:{tag}", PAGE_NS)
    if child is None:
        child = ET.SubElement(elem, qname(tag))
        # PAGE order is Coords, Baseline, TextEquiv — keep new tags near the front.
        elem.remove(child)
        elem.insert(0 if tag == "Coords" else 1, child)
    child.set("points", format_points(points))


def set_line_unicode(elem: ET.Element, text: str) -> None:
    for word in list(elem.findall("p:Word", PAGE_NS)):
        elem.remove(word)
    te = elem.find("p:TextEquiv", PAGE_NS)
    if te is None:
        te = ET.SubElement(elem, qname("TextEquiv"))
    uni = te.find("p:Unicode", PAGE_NS)
    if uni is None:
        uni = ET.SubElement(te, qname("Unicode"))
    uni.text = text


def set_reading_order(elem: ET.Element, index: int) -> None:
    replacement = f"readingOrder {{index:{index};}}"
    custom = elem.get("custom") or ""
    if READING_ORDER_RE.search(custom):
        custom = READING_ORDER_RE.sub(replacement, custom)
    else:
        custom = f"{custom} {replacement}".strip()
    elem.set("custom", custom)


def pick_primary_id(ids: list[str], by_id: dict[str, ET.Element]) -> str:
    present = [i for i in ids if i in by_id]
    if not present:
        return ids[0]
    return max(present, key=lambda i: (elem_width(by_id[i]), i))


def union_line_geometry(primary: ET.Element, members: list[ET.Element]) -> None:
    coords: list[tuple[int, int]] = []
    baseline: list[tuple[int, int]] = []
    for elem in members:
        coords.extend(elem_points(elem, "Coords"))
        baseline.extend(elem_points(elem, "Baseline"))
    if coords:
        set_points(primary, "Coords", convex_hull(coords))
    if baseline:
        set_points(primary, "Baseline", sorted(set(baseline), key=lambda p: (p[0], p[1])))


def rewrite_page_xml(src: Path, alignments: list[Alignment], dest: Path) -> dict[str, int]:
    """Drop EXTRA lines, merge split-line geometry, replace Unicode with GT."""
    tree = ET.parse(src)
    root = tree.getroot()
    page = root.find("p:Page", PAGE_NS)
    if page is None:
        raise ValueError(f"No Page element in {src}")

    by_id = {el.get("id"): el for el in page.findall(".//p:TextLine", PAGE_NS) if el.get("id")}
    parent = {child: node for node in root.iter() for child in node}
    delete_ids: set[str] = set()
    missing = 0

    for item in alignments:
        if item.status == "EXTRA":
            delete_ids.update(item.xml_ids)
            continue
        if item.status == "MISSING" or not item.gt_text or not item.xml_ids:
            if item.status == "MISSING":
                missing += 1
            continue
        members = [by_id[i] for i in item.xml_ids if i in by_id]
        if not members:
            continue
        primary_id = pick_primary_id(item.xml_ids, by_id)
        primary = by_id[primary_id]
        set_line_unicode(primary, item.gt_text)
        if item.status == "MERGE" or len(members) > 1:
            union_line_geometry(primary, members)
            for other in item.xml_ids:
                if other != primary_id:
                    delete_ids.add(other)

    for line_id in delete_ids:
        elem = by_id.get(line_id)
        if elem is not None and elem in parent:
            parent[elem].remove(elem)

    stats = {"kept": 0, "deleted": len(delete_ids), "missing_skipped": missing}
    line_index = 0
    for region in page.findall("p:TextRegion", PAGE_NS):
        for idx, line in enumerate(region.findall("p:TextLine", PAGE_NS)):
            set_reading_order(line, idx)
            line_index += 1
        # Leave region Unicode empty, as in Transkribus export.
        # Only refresh readingOrder if the region already had it.
        if region.get("custom") and READING_ORDER_RE.search(region.get("custom") or ""):
            set_reading_order(region, 0)
    stats["kept"] = line_index

    last_change = root.find("p:Metadata/p:LastChange", PAGE_NS)
    if last_change is not None:
        last_change.text = datetime.now().astimezone().isoformat(timespec="milliseconds")

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(serialize_transkribus_xml(root), encoding="utf-8")
    return stats


def serialize_transkribus_xml(root: ET.Element) -> str:
    """Match Transkribus PAGE XML: one line, standalone declaration, compact empty tags."""
    ET.register_namespace("", PAGE_NS_URI)
    body = ET.tostring(root, encoding="unicode", short_empty_elements=True)
    if body.startswith("<?xml"):
        body = body.split("?>", 1)[1]
    body = body.replace(" />", "/>")
    body = body.replace("<Unicode/>", "<Unicode></Unicode>")
    body = "".join(body.splitlines())
    return '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' + body


def write_corrected_xml(pages: list[PageResult], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for page in pages:
        if not page.xml_path:
            continue
        src = Path(page.xml_path)
        dest = out_dir / src.name
        stats = rewrite_page_xml(src, page.alignments, dest)
        print(
            f"  XML {page.folio}: kept {stats['kept']}  deleted {stats['deleted']}"
            + (f"  skipped {stats['missing_skipped']} missing" if stats["missing_skipped"] else "")
            + f"  -> {dest}"
        )


def alignment_to_dict(item: Alignment) -> dict:
    return {
        "status": item.status,
        "xml_ids": item.xml_ids,
        "xml_text": item.xml_text,
        "gt_index": item.gt_index,
        "gt_text": item.gt_text,
        "ratio": None if item.ratio is None else round(item.ratio, 4),
        "baseline_y": None if item.baseline_y is None else round(item.baseline_y, 1),
        "bbox": item.bbox,
        "flags": item.flags,
        "char_spans": [asdict(span) for span in item.char_spans],
    }


def page_counts(page: PageResult) -> dict[str, int]:
    counts = {key: 0 for key in STATUSES}
    for item in page.alignments:
        counts[item.status] = counts.get(item.status, 0) + 1
    return counts


def mean_ratio(page: PageResult) -> float | None:
    ratios = [a.ratio for a in page.alignments if a.ratio is not None]
    if not ratios:
        return None
    return sum(ratios) / len(ratios)


def render_spans(spans: list[CharSpan], side: str) -> str:
    parts: list[str] = []
    for span in spans:
        text = span.xml if side == "xml" else span.gt
        if not text:
            continue
        escaped = html.escape(text)
        if span.tag == "equal":
            parts.append(escaped)
        elif span.tag == "replace":
            cls = "del" if side == "xml" else "ins"
            parts.append(f'<span class="{cls}">{escaped}</span>')
        elif span.tag == "delete" and side == "xml":
            parts.append(f'<span class="del">{escaped}</span>')
        elif span.tag == "insert" and side == "gt":
            parts.append(f'<span class="ins">{escaped}</span>')
    return "".join(parts) or '<span class="empty">—</span>'


CSS = """
:root {
  --ink: #1c1410;
  --paper: #f4ead7;
  --rule: #cbb79a;
  --muted: #6d5c4d;
  --match: #2f6b4f;
  --ocr: #8a5a12;
  --merge: #1f4e79;
  --split: #5b3d8f;
  --extra: #8b2e2e;
  --missing: #5c5c5c;
  --del-bg: #f4c7c2;
  --ins-bg: #c9e4c9;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  background: var(--paper);
  color: var(--ink);
  font-family: "Noto Naskh Arabic", "Amiri", "Scheherazade New", "Georgia", serif;
  line-height: 1.55;
}
header, main { max-width: 1100px; margin: 0 auto; padding: 1.25rem 1.5rem; }
header h1 { margin: 0 0 .35rem; font-size: 1.7rem; }
header p { margin: 0; color: var(--muted); }
nav a { color: var(--ink); }
table { width: 100%; border-collapse: collapse; margin-top: 1rem; }
th, td { border-bottom: 1px solid var(--rule); padding: .45rem .5rem; text-align: start; }
.badge {
  display: inline-block;
  padding: .1rem .55rem;
  border-radius: 999px;
  font-size: .78rem;
  letter-spacing: .02em;
  color: #fff;
  font-family: "IBM Plex Sans", "Helvetica Neue", sans-serif;
}
.MATCH { background: var(--match); }
.OCR { background: var(--ocr); }
.MERGE { background: var(--merge); }
.SPLIT { background: var(--split); }
.EXTRA { background: var(--extra); }
.MISSING { background: var(--missing); }
.row {
  background: #fffaf1;
  border: 1px solid var(--rule);
  border-radius: 10px;
  padding: .85rem 1rem;
  margin: .8rem 0;
}
.meta { color: var(--muted); font-size: .85rem; font-family: "IBM Plex Sans", sans-serif; }
.pair { display: grid; grid-template-columns: 1fr 1fr; gap: .75rem; margin-top: .5rem; }
.label { font-size: .75rem; color: var(--muted); font-family: "IBM Plex Sans", sans-serif; }
.text { font-size: 1.15rem; }
.del { background: var(--del-bg); text-decoration: line-through; }
.ins { background: var(--ins-bg); }
.empty { color: var(--muted); }
@media (max-width: 800px) { .pair { grid-template-columns: 1fr; } }
"""


def page_html(page: PageResult) -> str:
    counts = page_counts(page)
    avg = mean_ratio(page)
    avg_s = "—" if avg is None else f"{avg:.3f}"
    rows = []
    for idx, item in enumerate(page.alignments, start=1):
        xml_html = render_spans(item.char_spans, "xml") if item.char_spans else html.escape(item.xml_text or "—")
        gt_html = render_spans(item.char_spans, "gt") if item.char_spans else html.escape(item.gt_text or "—")
        if not item.gt_text:
            gt_html = '<span class="empty">—</span>'
        if not item.xml_text:
            xml_html = '<span class="empty">—</span>'
        ratio_s = "—" if item.ratio is None else f"{item.ratio:.3f}"
        ids = ", ".join(item.xml_ids) if item.xml_ids else "—"
        bbox = item.bbox or {}
        geom = (
            f"y={item.baseline_y:.0f}" if item.baseline_y is not None else "y=—"
        )
        if bbox:
            geom += f"  box={bbox['x_min']},{bbox['y_min']}–{bbox['x_max']},{bbox['y_max']}  w={bbox['x_max']-bbox['x_min']}"
        flag_s = ", ".join(item.flags) if item.flags else "—"
        rows.append(
            f"""
<article class="row">
  <div class="meta">
    <span class="badge {html.escape(item.status)}">{html.escape(item.status)}</span>
    #{idx}
    · ratio {ratio_s}
    · ids {html.escape(ids)}
    · GT line {item.gt_index if item.gt_index is not None else "—"}
    · {html.escape(geom)}
    · flags {html.escape(flag_s)}
  </div>
  <div class="pair">
    <div><div class="label">XML</div><div class="text">{xml_html}</div></div>
    <div><div class="label">Ground truth</div><div class="text">{gt_html}</div></div>
  </div>
</article>"""
        )
    count_bits = " · ".join(f"{k} {counts[k]}" for k in STATUSES)
    return f"""<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
  <meta charset="utf-8">
  <title>Folio {html.escape(page.folio)}</title>
  <style>{CSS}</style>
</head>
<body>
<header>
  <p><a href="index.html">كل الصفحات</a></p>
  <h1>الورقة {html.escape(page.folio)}</h1>
  <p>XML {page.xml_line_count} سطر · GT {page.gt_line_count} سطر · متوسط التشابه {avg_s} · {html.escape(count_bits)}</p>
  <p>{html.escape(page.xml_path or page.note or "")}</p>
</header>
<main>
{''.join(rows)}
</main>
</body>
</html>
"""


def index_html(pages: list[PageResult], gt_only: list[str], xml_only: list[str]) -> str:
    body_rows = []
    for page in pages:
        counts = page_counts(page)
        avg = mean_ratio(page)
        avg_s = "—" if avg is None else f"{avg:.3f}"
        href = f"{page.folio}.html"
        body_rows.append(
            f"<tr><td><a href='{html.escape(href)}'>{html.escape(page.folio)}</a></td>"
            f"<td>{page.xml_line_count}</td><td>{page.gt_line_count}</td>"
            f"<td>{counts['MATCH']}</td><td>{counts['OCR']}</td><td>{counts['MERGE']}</td>"
            f"<td>{counts['SPLIT']}</td><td>{counts['EXTRA']}</td><td>{counts['MISSING']}</td>"
            f"<td>{avg_s}</td></tr>"
        )
    extra = ""
    if gt_only:
        extra += "<p>صفحات في الحقيقة دون XML: " + ", ".join(html.escape(x) for x in gt_only) + "</p>"
    if xml_only:
        extra += "<p>صفحات XML دون حقيقة: " + ", ".join(html.escape(x) for x in xml_only) + "</p>"
    return f"""<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
  <meta charset="utf-8">
  <title>PAGE XML alignment</title>
  <style>{CSS}</style>
</head>
<body>
<header>
  <h1>مقابلة النسخ</h1>
  <p>PAGE XML مقابل الحقيقة من Word. الأحمر في XML = حذف/خطأ، الأخضر في الحقيقة = الزيادة الصحيحة.</p>
</header>
<main>
<table>
  <thead>
    <tr>
      <th>الورقة</th><th>XML</th><th>GT</th>
      <th>MATCH</th><th>OCR</th><th>MERGE</th><th>SPLIT</th><th>EXTRA</th><th>MISSING</th>
      <th>mean ratio</th>
    </tr>
  </thead>
  <tbody>
    {''.join(body_rows)}
  </tbody>
</table>
{extra}
</main>
</body>
</html>
"""


def write_reports(pages: list[PageResult], gt_only: list[str], xml_only: list[str], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "pages": [
            {
                "folio": page.folio,
                "xml_path": page.xml_path,
                "image_filename": page.image_filename,
                "gt_line_count": page.gt_line_count,
                "xml_line_count": page.xml_line_count,
                "counts": page_counts(page),
                "mean_ratio": mean_ratio(page),
                "alignments": [alignment_to_dict(a) for a in page.alignments],
                "note": page.note,
            }
            for page in pages
        ],
        "gt_only_folios": gt_only,
        "xml_only_folios": xml_only,
    }
    (out_dir / "alignment.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out_dir / "index.html").write_text(index_html(pages, gt_only, xml_only), encoding="utf-8")
    for page in pages:
        (out_dir / f"{page.folio}.html").write_text(page_html(page), encoding="utf-8")


def print_summary(pages: list[PageResult], gt_only: list[str], xml_only: list[str]) -> None:
    print(f"{'folio':<8} {'xml':>4} {'gt':>4} {'MATCH':>6} {'OCR':>5} {'MERGE':>6} {'SPLIT':>6} {'EXTRA':>6} {'MISS':>5} {'ratio':>7}")
    for page in pages:
        c = page_counts(page)
        avg = mean_ratio(page)
        avg_s = "—" if avg is None else f"{avg:.3f}"
        print(
            f"{page.folio:<8} {page.xml_line_count:4d} {page.gt_line_count:4d} "
            f"{c['MATCH']:6d} {c['OCR']:5d} {c['MERGE']:6d} {c['SPLIT']:6d} "
            f"{c['EXTRA']:6d} {c['MISSING']:5d} {avg_s:>7}"
        )
        for item in page.alignments:
            if item.status in {"MERGE", "SPLIT", "EXTRA", "MISSING"}:
                preview = (item.xml_text or item.gt_text or "")[:60]
                print(f"    {item.status:8} ids={item.xml_ids} ratio={item.ratio} {preview}")
    if gt_only:
        print("GT without XML:", ", ".join(gt_only))
    if xml_only:
        print("XML without GT:", ", ".join(xml_only))


def load_xml_pages(xml_dir: Path) -> dict[str, tuple[Path, str | None, list[XmlLine]]]:
    pages: dict[str, tuple[Path, str | None, list[XmlLine]]] = {}
    for path in sorted(xml_dir.glob("*.xml")):
        folio, image_filename, lines = parse_page_xml(path)
        pages[folio] = (path, image_filename, lines)
    return pages


def run(gt_path: Path, xml_dir: Path, out_dir: Path, corrected_dir: Path | None = None) -> list[PageResult]:
    gt_pages = parse_ground_truth(gt_path)
    xml_pages = load_xml_pages(xml_dir)
    paired = sorted(set(gt_pages) & set(xml_pages), key=folio_sort_key)
    gt_only = sorted(set(gt_pages) - set(xml_pages), key=folio_sort_key)
    xml_only = sorted(set(xml_pages) - set(gt_pages), key=folio_sort_key)
    results: list[PageResult] = []
    for folio in paired:
        path, image_filename, lines = xml_pages[folio]
        results.append(align_page(folio, path, image_filename, lines, gt_pages[folio]))
    write_reports(results, gt_only, xml_only, out_dir)
    print_summary(results, gt_only, xml_only)
    if corrected_dir is not None:
        print("Corrected PAGE XML:")
        write_corrected_xml(results, corrected_dir)
    return results


def folio_sort_key(folio: str) -> tuple[int, str]:
    match = re.match(r"(\d+)([rv])", folio)
    if not match:
        return (10**9, folio)
    return (int(match.group(1)), match.group(2))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gt", type=Path, default=Path("ground_truth/S155-transcription.docx"))
    parser.add_argument("--xml-dir", type=Path, default=Path("transcribed_xml"))
    parser.add_argument("--out", type=Path, default=Path("reports"))
    parser.add_argument("--corrected-dir", type=Path, default=Path("corrected_xml"))
    parser.add_argument("--no-xml", action="store_true", help="Skip writing corrected PAGE XML")
    args = parser.parse_args(argv)
    if not args.gt.exists():
        print(f"Ground truth not found: {args.gt}", file=sys.stderr)
        return 1
    if not args.xml_dir.exists():
        print(f"XML directory not found: {args.xml_dir}", file=sys.stderr)
        return 1
    corrected = None if args.no_xml else args.corrected_dir
    run(args.gt, args.xml_dir, args.out, corrected)
    print(f"Wrote reports to {args.out.resolve()}")
    if corrected is not None:
        print(f"Wrote corrected XML to {corrected.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

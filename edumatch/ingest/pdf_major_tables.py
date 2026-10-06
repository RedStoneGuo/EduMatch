"""Extract **per-major** rows from employment-quality report PDFs.

This is the primary source for major-level indicators. The curated docx台账 is
NOT used here - it serves only as an independent golden set for verification
(see ``scripts/validate_extraction.py``).

Chinese employment reports print per-major tables as one line per major:

    人工智能 42 24 57.14 38 90.48 38 90.48
    └ 专业   └人数 └深造人数 └深造率  └签约人数 └签约率 └落实人数 └落实率

Every candidate row is **self-validated** before acceptance:

* counts are integers and never exceed the graduate count;
* each rate equals count/total within 1.5 percentage points;
* rates lie in [0, 100].

A row that fails the identity check is rejected, which is what keeps this
extractor from silently shifting columns (the failure mode we hit earlier on
docx tables).
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Iterable

ROW_RE = re.compile(
    r"(?P<major>[\u4e00-\u9fffA-Za-z（）()·．.＋+\-、]{2,30}?)\s+"
    r"(?P<nums>(?:\d+(?:\.\d+)?\s+){2,7}\d+(?:\.\d+)?)"
)
STOP_MAJOR = ("人数", "比例", "专业", "学院", "总计", "小计", "合计", "总数", "平均",
              "其中", "以上", "合计", "毕业", "就业", "深造", "签约", "落实", "学历",
              "本科", "硕士", "博士", "专科", "女", "男", "表", "注", "单位", "项目")


@dataclass
class MajorRow:
    school: str
    year: int | None
    major: str
    graduates: int
    further_study_rate: float | None
    signing_rate: float | None
    placement_rate: float | None
    page: int | None
    raw_text: str
    source_document: str
    layout: str  # "full7" | "compact4"
    evidence_level: str = "A"
    confidence: float = 0.9

    def to_dict(self) -> dict:
        return asdict(self)


def _close(rate: float | None, count: int, total: int, tol: float = 1.5) -> bool:
    if rate is None or total <= 0:
        return False
    expected = count / total * 100.0
    return abs(expected - rate) <= tol


def _parse_full7(nums: list[float]) -> tuple[int, float, float, float] | None:
    total = int(nums[0])
    further_n, further_r = int(nums[1]), nums[2]
    sign_n, sign_r = int(nums[3]), nums[4]
    place_n, place_r = int(nums[5]), nums[6]
    if total <= 0:
        return None
    for value in (further_r, sign_r, place_r):
        if not 0 <= value <= 100:
            return None
    for count in (further_n, sign_n, place_n):
        if count < 0 or count > total:
            return None
    # 三项一致性校验（允许 1.5 个百分点误差）
    if not (_close(further_r, further_n, total) and _close(sign_r, sign_n, total)
            and _close(place_r, place_n, total)):
        return None
    return total, further_r, sign_r, place_r


def _parse_compact4(nums: list[float]) -> tuple[int, float, float, float] | None:
    total = int(nums[0])
    further_r, sign_r, place_r = nums[1], nums[2], nums[3]
    if total <= 0:
        return None
    if not all(0 <= v <= 100 for v in (further_r, sign_r, place_r)):
        return None
    if not (further_r <= sign_r + 1.5 and sign_r <= place_r + 1.5):
        return None
    return total, further_r, sign_r, place_r


def _clean_major(name: str) -> str | None:
    name = name.strip(" 　·．.-+")
    if len(name) < 2 or len(name) > 24:
        return None
    if name.isdigit():
        return None
    if any(bad in name for bad in STOP_MAJOR):
        return None
    # 严格闸门：剔除企业名/统计行等错位产物（见 edumatch.majors.is_plausible_major）
    from ..majors import is_plausible_major

    if not is_plausible_major(name):
        return None
    return name


COLLEGE_PREFIX = re.compile(r"^.*?(?:学部（院）|学部|学院|院系|系)\s*")


def _strip_college_prefix(head: str) -> str:
    """'信息学部 电子科学与技术' -> '电子科学与技术'（保留专业名本体）。"""
    parts = head.split()
    if len(parts) >= 2 and COLLEGE_PREFIX.match(parts[0]):
        return " ".join(parts[1:])
    return head


def extract_major_rows(text: str, *, school: str, year: int | None,
                       source_document: str, page_of=None) -> list[MajorRow]:
    rows: list[MajorRow] = []
    lines = text.splitlines()
    # 逐行页码，供表头驱动策略记录来源页（可追溯性）
    line_pages: list[int | None] = []
    offset = 0
    for line in lines:
        line_pages.append(page_of(offset) if page_of else None)
        offset += len(line) + 1
    # 策略 B：按表头列映射（覆盖各校不同列顺序）
    rows.extend(extract_header_driven(lines, school=school, year=year,
                                      source_document=source_document, line_pages=line_pages))
    # 策略 A：单行 7 数字的"人数+比例"成对结构（带强一致性校验）
    # 表头锚定：只有出现在"专业 … 人数/比例"表头之后的区块才接受 compact4 行，
    # 否则会把"美国 92 45 33 12"这类国别/行业分布表当成专业行。
    header_after = _header_line_indices(lines)
    cursor = 0
    for index, line in enumerate(lines):
        page = page_of(cursor) if page_of else None
        cursor += len(line) + 1
        stripped = line.strip()
        if len(stripped) < 8 or len(stripped) > 400:
            continue
        in_major_table = any(0 <= index - h <= 80 for h in header_after)
        for match in ROW_RE.finditer(stripped):
            major = _clean_major(match.group("major"))
            if not major:
                continue
            try:
                nums = [float(v) for v in match.group("nums").split()]
            except ValueError:
                continue
            parsed = None
            layout = ""
            if len(nums) == 7:
                parsed, layout = _parse_full7(nums), "full7"
            elif len(nums) == 4:
                if not in_major_table:
                    continue
                parsed, layout = _parse_compact4(nums), "compact4"
            if not parsed:
                continue
            total, further_r, sign_r, place_r = parsed
            rows.append(MajorRow(
                school=school, year=year, major=major, graduates=total,
                further_study_rate=round(further_r / 100, 6),
                signing_rate=round(sign_r / 100, 6),
                placement_rate=round(place_r / 100, 6),
                page=page, raw_text=stripped[:300], source_document=source_document,
                layout=layout, confidence=0.92 if layout == "full7" else 0.8,
            ))
    # 去重：同一专业优先 full7（强校验）> header_driven > compact4，其次人数多者
    priority = {"full7": 0, "header_driven": 1, "compact4": 2}
    best: dict[tuple, MajorRow] = {}
    for row in rows:
        key = (row.major, row.graduates)
        current = best.get(key)
        if current is None:
            best[key] = row
            continue
        if (priority.get(row.layout, 9), -row.graduates) < (priority.get(current.layout, 9), -current.graduates):
            best[key] = row
    return list(best.values())


HEADER_HINT_A = re.compile(r"专业")
HEADER_HINT_B = re.compile(r"人数|比例|就业率|落实率|深造率|签约率|毕业生")
SECTION_BREAK = re.compile(r"^\s*(第[一二三四五六七八九十]+部分|表\s*\d|单位[:：]|注[:：])")

#: 表头列名 → 规范字段。按"最长匹配优先"归一化，避免"深造率"吞掉"国内深造率"。
COLUMN_TOKENS: list[tuple[str, re.Pattern[str]]] = [
    ("college", re.compile(r"^(学部（院）|学部|学院|院系|系别|系|培养单位)$")),
    ("major", re.compile(r"^(专业|专业名称|专业方向)$")),
    ("graduates", re.compile(r"^(人数|毕业生人数|总人数|毕业人数)$")),
    ("placement_rate", re.compile(r"^(毕业去向落实率|落实率|毕业去向落实比例)$")),
    ("employment_rate", re.compile(r"^(就业率|总体就业率)$")),
    ("signing_rate", re.compile(r"^(签约率|协议签约率)$")),
    ("domestic_study_rate", re.compile(r"^(国内深造率|境内深造率)$")),
    ("overseas_study_rate", re.compile(r"^(出国（境）深造率|出国深造率|境外深造率|出国（境）率)$")),
    ("further_study_rate", re.compile(r"^(深造率|升学率)$")),
    ("ratio_marker", re.compile(r"^(比例.*|.*%）)$")),
]
NUMERIC_COLUMNS = ("graduates", "placement_rate", "employment_rate", "signing_rate",
                   "domestic_study_rate", "overseas_study_rate", "further_study_rate")


def _normalise_header_cells(window: str) -> tuple[list[str], str | None]:
    """Turn a header window into ordered column keys + the major column name if any."""
    text = re.sub(r"[\s\u3000]+", " ", window)
    raw_cells = [c.strip(" 　|") for c in re.split(r"[\s|]+", text) if c.strip(" 　|")]
    cells: list[str] = []
    buffer = ""
    for cell in raw_cells:
        # 表头常被换行切断（"毕业去向" + "落实率"、"出国（境）" + "深造率"）
        if buffer and not any(p.match(buffer) for _, p in COLUMN_TOKENS):
            buffer = buffer + cell
        else:
            if buffer:
                cells.append(buffer)
            buffer = cell
        if any(p.match(buffer) for _, p in COLUMN_TOKENS):
            cells.append(buffer)
            buffer = ""
    if buffer:
        cells.append(buffer)

    columns: list[str] = []
    major_col: str | None = None
    for cell in cells:
        matched = None
        for key, pattern in COLUMN_TOKENS:
            if pattern.match(cell):
                matched = key
                break
        if matched == "major":
            major_col = cell
            continue
        if matched in NUMERIC_COLUMNS:
            # 北交大式表头是"人数 比例"成对出现，这里只保留数值列本身
            columns.append(matched)
    return columns, major_col


def _header_line_indices(lines: list[str]) -> list[int]:
    """Indices of lines that look like a per-major table header (or its first row)."""
    out: list[int] = []
    for i, line in enumerate(lines):
        window = " ".join(lines[i:i + 3])
        if HEADER_HINT_A.search(window) and HEADER_HINT_B.search(window):
            out.append(i)
    return out


NUMBER_TOKEN = re.compile(r"^\d+(?:\.\d+)?%?$")


def extract_header_driven(lines: list[str], *, school: str, year: int | None,
                          source_document: str,
                          line_pages: list[int | None] | None = None) -> list[MajorRow]:
    """Parse per-major tables by mapping each header column to a canonical field.

    Handles the layout used by e.g. 北京工业大学 (专业 人数 落实率 国内深造率 出国深造率 深造率)
    in addition to the count/rate-pair layout used by 北京交通大学.
    """
    rows: list[MajorRow] = []
    index = 0
    while index < len(lines):
        span = None
        columns: list[str] = []
        for candidate in (3, 2, 1):
            window = " ".join(lines[index:index + candidate])
            columns, major_col = _normalise_header_cells(window)
            # 必须同时出现"专业"列与"人数"列，否则学校去向/雇主分布表会被误当专业表
            if major_col and "graduates" in columns and len(columns) >= 2:
                span = candidate
                break
        if span is None:
            index += 1
            continue

        cursor = index + span
        consumed = 0
        while cursor < len(lines) and consumed < 120:
            raw = lines[cursor].strip()
            cursor += 1
            if not raw or len(raw) > 200:
                continue
            # 分页会重复打印表头：跳过即可，不能终止区块（否则只抽到第一段）
            if HEADER_HINT_A.search(raw) and HEADER_HINT_B.search(raw) and not NUMBER_TOKEN.search(raw):
                continue
            tokens = raw.split()
            if len(tokens) < 2:
                continue
            numbers = [t for t in tokens if NUMBER_TOKEN.match(t)]
            if len(numbers) != len(columns):
                continue
            head = " ".join(tokens[:len(tokens) - len(numbers)]).strip()
            # 专业名可能被换行切断：上一行是纯文本时拼回来
            if head and cursor - 2 >= 0 and len(head) <= 6:
                previous = lines[cursor - 2].strip()
                if (previous and 2 <= len(previous) <= 12
                        and not any(NUMBER_TOKEN.match(t) for t in previous.split())
                        and not any(bad in previous for bad in STOP_MAJOR)):
                    head = previous + head
            major = _clean_major(_strip_college_prefix(head))
            if not major:
                continue
            values: dict[str, float] = {}
            for key, token in zip(columns, numbers):
                value = float(token.rstrip("%"))
                if key == "graduates":
                    if value <= 0:
                        break
                    values[key] = value
                else:
                    if not 0 <= value <= 100:
                        break
                    values[key] = round(value / 100, 6)
            else:
                # 内部一致性：深造率 ≈ 国内 + 出国（若三者都有）
                if {"further_study_rate", "domestic_study_rate", "overseas_study_rate"} <= values.keys():
                    expected = values["domestic_study_rate"] + values["overseas_study_rate"]
                    if abs(expected - values["further_study_rate"]) > 0.03:
                        continue
                rows.append(MajorRow(
                    school=school, year=year, major=major,
                    graduates=int(values.get("graduates") or 0),
                    further_study_rate=values.get("further_study_rate"),
                    signing_rate=values.get("signing_rate"),
                    placement_rate=values.get("placement_rate") or values.get("employment_rate"),
                    page=(line_pages[cursor - 1] if line_pages and cursor - 1 < len(line_pages) else None),
                    raw_text=raw[:300], source_document=source_document,
                    layout="header_driven", confidence=0.85,
                ))
            consumed += 1
        index = max(cursor, index + 1)
    return rows


def extract_many(items: Iterable[tuple[str, str, int | None, str, object]]) -> list[MajorRow]:
    out: list[MajorRow] = []
    for text, school, year, source, page_of in items:
        out.extend(extract_major_rows(text, school=school, year=year,
                                      source_document=source, page_of=page_of))
    return out

"""Rule-based extraction of education-supply facts from curated archive documents.

Input documents are the manually curated compilations found in the legacy
archive (``人工智能相关专业.docx`` / ``计算机相关专业.docx`` /
``和经济相关的专业.docx``). They are secondary sources: each fact records the
upstream report named in the text, and is tagged evidence level ``D`` because a
human/LLM curation step sits between the official PDF and this text. Facts that
quote an official table verbatim additionally keep the quoted line so the claim
can be re-checked by hand.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable

YEAR_HEADING = re.compile(r"^\s*[一二三四五六七八九十]+、\s*(20\d{2})\s*年?\s*$")
SUB_HEADING = re.compile(r"^\s*[（(]\s*[12]\s*[)）]\s*(就业质量报告|教学质量报告)\s*[:：]?\s*$")
SCHOOL_LINE = re.compile(
    r"^\s*(?:\d+\s*[.、]\s*)?([\u4e00-\u9fff（）()·]{3,25}?(?:大学|学院|学校))\s*[:：]?\s*$"
)
#: 策展文档里也会写 "高校：北京交通大学" / "学校名称：…"
SCHOOL_LABEL = re.compile(
    r"^\s*(?:高校|学校|学校名称|院校)\s*[:：]\s*([\u4e00-\u9fff（）()·]{3,25}?(?:大学|学院|学校))"
)
SOURCE_LINE = re.compile(r"(?:数据来源|文档来源|来源)\s*[:：]\s*(.+)$")

COLUMN_NAMES = {
    "学院": "college",
    "院系": "college",
    "系别": "college",
    "专业": "major",
    "总人数": "graduates",
    "毕业生人数": "graduates",
    "深造率": "further_study_rate",
    "签约率": "signing_rate",
    "毕业去向落实率": "placement_rate",
    "专业毕业去向落实率": "placement_rate",
    "单位就业": "employed_unit",
    "升学（境内境外合计）": "further_study_count",
    "升学": "further_study_count",
    "自主创业": "self_employed",
    "自由职业": "freelance",
}

PERCENT = r"([0-9]+(?:\.[0-9]+)?)\s*%"
NUMBER = r"([0-9]+(?:\.[0-9]+)?)"

# (fact_type, compiled regex, group, unit)
FACT_RULES: list[tuple[str, re.Pattern[str], int, str]] = [
    ("graduates", re.compile(rf"毕业生人数\s*[:：]\s*{NUMBER}\s*人?"), 1, "人"),
    ("graduates", re.compile(rf"毕业生\s*{NUMBER}\s*人"), 1, "人"),
    ("further_study_rate", re.compile(rf"深造率\s*[:：]\s*{PERCENT}"), 1, "ratio"),
    ("signing_rate", re.compile(rf"签约率\s*[:：]\s*{PERCENT}"), 1, "ratio"),
    ("placement_rate", re.compile(rf"毕业去向落实率\s*[:：]\s*{PERCENT}"), 1, "ratio"),
    ("employment_rate", re.compile(rf"就业率\s*[:：]?\s*{PERCENT}"), 1, "ratio"),
    ("employment_rate", re.compile(rf"就业率\s*{PERCENT}"), 1, "ratio"),
    ("practice_credit_ratio", re.compile(rf"实践(?:教学)?学分(?:占|比为|比例为)?\s*总?学分的?\s*{PERCENT}"), 1, "ratio"),
    ("practice_credit_ratio", re.compile(rf"实践学分占比为\s*{PERCENT}"), 1, "ratio"),
    ("practice_credit", re.compile(rf"实践教学学分为\s*{NUMBER}\s*学分"), 1, "学分"),
    ("lab_credit", re.compile(rf"实验教学学分为\s*{NUMBER}\s*学分"), 1, "学分"),
    ("faculty_total", re.compile(rf"专任教师(?:总数)?(?:为)?\s*{NUMBER}\s*人"), 1, "人"),
    ("senior_title_count", re.compile(rf"高级职称的?(?:教师|教师总数为)?\s*{NUMBER}\s*人"), 1, "人"),
    ("senior_title_ratio", re.compile(rf"(?:高级职称|具有高级职称).*?占?比\s*{PERCENT}"), 1, "ratio"),
    ("student_faculty_ratio", re.compile(rf"生师比(?:为)?\s*[:：]?\s*{NUMBER}"), 1, "ratio_value"),
    ("training_base_count", re.compile(rf"实习实训基地\s*{NUMBER}\s*个"), 1, "个"),
    ("total_hours", re.compile(rf"学时总数(?:为)?\s*{NUMBER}"), 1, "学时"),
    ("required_course_ratio", re.compile(rf"必修课占比\s*{PERCENT}"), 1, "ratio"),
    ("elective_course_ratio", re.compile(rf"选修课占比\s*{PERCENT}"), 1, "ratio"),
    ("physical_test_pass_rate", re.compile(rf"体质测试合格率\s*[:：]?\s*{PERCENT}"), 1, "ratio"),
    ("physical_test_pass_rate", re.compile(rf"合格率\s*{PERCENT}"), 1, "ratio"),
    ("industry_teacher_count", re.compile(rf"行业企业背景教师\s*{NUMBER}\s*人"), 1, "人"),
]

FAMILY_KEYWORDS = {
    "ai": ["人工智能", "智能", "机器学习", "智能科学与技术"],
    "cs": ["计算机", "软件", "信息安全", "网络空间", "物联网", "数据科学", "网络工程"],
    "econ": ["经济", "金融", "会计", "管理", "贸易", "财务"],
}


@dataclass
class EducationFact:
    fact_id: str
    family: str
    year: int | None
    school: str
    major: str | None
    section: str  # employment_quality_report | teaching_quality_report
    fact_type: str
    value: float | None
    unit: str
    raw_text: str
    source_document: str
    source_line: int
    upstream_source: str = ""
    evidence_level: str = "D"
    confidence: float = 0.5
    to_dict = asdict


def _parse_value(text: str, group: int, unit: str) -> float | None:
    m = re.search(NUMBER, text)
    if not m:
        return None
    value = float(m.group(1))
    return value if unit != "ratio" else value / 100.0


def _looks_like_school(line: str) -> str | None:
    if any(k in line for k in ("数据来源", "文档来源", "说明", "相关课程", "培养目标", "专业数据")):
        return None
    labelled = SCHOOL_LABEL.match(line)
    if labelled:
        return labelled.group(1).strip()
    m = SCHOOL_LINE.match(line)
    if not m:
        return None
    name = m.group(1).strip()
    if name in COLUMN_NAMES or len(name) < 4:
        return None
    return name


def _family_of_major(major: str | None, default: str) -> str:
    if not major:
        return default
    for family, keys in FAMILY_KEYWORDS.items():
        if any(k in major for k in keys):
            return family
    return default


def extract_file(path: Path, family: str) -> list[EducationFact]:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    facts: list[EducationFact] = []
    year: int | None = None
    section = "unknown"
    school = ""
    upstream = ""
    counter = 0
    i = 0

    while i < len(lines):
        raw = lines[i]
        line = raw.strip()
        if not line:
            i += 1
            continue

        m = YEAR_HEADING.match(line)
        if m:
            year = int(m.group(1))
            i += 1
            continue
        m = SUB_HEADING.match(line)
        if m:
            section = "employment_quality_report" if "就业" in m.group(1) else "teaching_quality_report"
            i += 1
            continue
        m = SOURCE_LINE.search(line)
        if m:
            upstream = m.group(1).strip()
            i += 1
            continue
        candidate = _looks_like_school(line)
        if candidate:
            school = candidate
            i += 1
            continue

        # table with a recognised header row
        if line in COLUMN_NAMES and i + 2 < len(lines):
            header: list[str] = []
            j = i
            while j < len(lines) and lines[j].strip() in COLUMN_NAMES:
                header.append(COLUMN_NAMES[lines[j].strip()])
                j += 1
            rows_start = j
            # skip a blank separator line
            while rows_start < len(lines) and not lines[rows_start].strip():
                rows_start += 1
            # Some tables omit the leading 学院 column from the header. Detect it
            # from the first data row: text, text, number => row is one column wider.
            width = len(header)
            probe = [lines[rows_start + c].strip() if rows_start + c < len(lines) else ""
                     for c in range(width + 1)]
            if (
                len(probe) > 2
                and "college" not in header
                and probe[0] and probe[1] and re.fullmatch(r"[0-9.]+", probe[2] or "")
                and not re.fullmatch(r"[0-9.]+", probe[0])
            ):
                width = width + 1
                header = ["college", *header]
            k = rows_start
            while k + width <= len(lines):
                chunk = [lines[k + c].strip() for c in range(width)]
                numeric_tail = sum(1 for c in chunk[1:] if re.fullmatch(r"[0-9.]+%?", c))
                if not chunk[0] or chunk[0].startswith(("说明", "（", "(", "注")):
                    break
                if _looks_like_school(chunk[0]) and numeric_tail < 2:
                    break
                if not any(chunk):
                    break
                row = dict(zip(header, chunk))
                major = row.get("major")
                if major and row.get("graduates"):
                    base = {
                        "family": _family_of_major(major, family),
                        "year": year,
                        "school": school,
                        "major": major,
                        "section": section,
                        "source_document": str(path),
                        "source_line": k + 1,
                        "upstream_source": upstream,
                    }
                    for col in ("graduates", "further_study_rate", "signing_rate", "placement_rate"):
                        if col not in row or not row[col]:
                            continue
                        counter += 1
                        value = row[col]
                        unit = "人" if col == "graduates" else "ratio"
                        if col != "graduates":
                            if any(ch in value for ch in ("未提供", "数据未")):
                                continue
                            value = value.rstrip("%")
                        try:
                            numeric = float(value)
                        except ValueError:
                            continue
                        if unit == "ratio":
                            if numeric > 100 or numeric < 0:
                                # guard against column misalignment
                                continue
                            numeric = numeric / 100.0
                        facts.append(
                            EducationFact(
                                fact_id=f"edu:{counter:05d}",
                                fact_type=col,
                                value=numeric,
                                unit=unit,
                                raw_text=" | ".join(chunk),
                                **base,
                            )
                        )
                k += width
            i = k
            continue

        hits: dict[str, re.Match[str]] = {}
        units: dict[str, str] = {}
        for fact_type, regex, group, unit in FACT_RULES:
            if fact_type in hits:
                continue
            m = regex.search(line)
            if m:
                hits[fact_type] = m
                units[fact_type] = unit
        for fact_type, m in hits.items():
            counter += 1
            facts.append(
                EducationFact(
                    fact_id=f"edu:{counter:05d}",
                    family=family,
                    year=year,
                    school=school,
                    major=None,
                    section=section,
                    fact_type=fact_type,
                    value=_parse_value(m.group(1), 1, units[fact_type]),
                    unit=units[fact_type],
                    raw_text=line,
                    source_document=str(path),
                    source_line=i + 1,
                    upstream_source=upstream,
                )
            )
        i += 1

    return facts


def extract_documents(paths: Iterable[tuple[Path, str]]) -> list[EducationFact]:
    out: list[EducationFact] = []
    for path, family in paths:
        if path.exists():
            out.extend(extract_file(path, family))
    return out

"""Extract education facts from PDF report text.

Chinese university reports phrase things in a small number of recurring ways
(``毕业去向落实率为 90.48%``、``本科生 3312 人``、``用人单位满意度 …``). The rules
below target those phrasings and always keep the source line and its page number,
so a fact can be re-checked against the PDF page it came from.

Evidence level: ``A`` (official primary document) when the text layer extracted
cleanly, ``E`` when the page has no text layer.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from .pdf_reader import PdfText

PERCENT = r"([0-9]+(?:\.[0-9]+)?)\s*%"
COUNT = r"([0-9][0-9,]*)"

#: 百分比的标签必须取"数值左侧最近的标签"，否则同一行里
#: "签约率…就业率为 99.75%" 会把就业率的数值记到签约率上。
PERCENT_LABELS: list[tuple[str, re.Pattern[str]]] = [
    ("placement_rate", re.compile(r"毕业去向落实率")),
    ("practice_credit_ratio", re.compile(r"实践(?:教学)?学分(?:占比为|占|比例为|占总学分的|占总学分)")),
    ("lab_credit_ratio", re.compile(r"实验(?:教学)?学分占比")),
    ("required_course_ratio", re.compile(r"必修课(?:学分)?占比")),
    ("elective_course_ratio", re.compile(r"选修课(?:学分)?占比")),
    ("senior_title_ratio", re.compile(r"高级职称(?:教师)?(?:占比|比例为|占)")),
    ("physical_test_pass_rate", re.compile(r"体质测试合格率")),
    ("domestic_study_rate", re.compile(r"国内深造率")),
    ("overseas_study_rate", re.compile(r"出国(?:（境）|\(境\))?深造率")),
    ("further_study_rate", re.compile(r"深造率")),
    ("beijing_employment_ratio", re.compile(r"在京就业")),
    ("employer_satisfaction", re.compile(r"满意度")),
    ("signing_rate", re.compile(r"签约率")),
    ("employment_rate", re.compile(r"就业率")),
]
PERCENT_VALUE = re.compile(r"([0-9]+(?:\.[0-9]+)?)\s*%")
LABEL_WINDOW = 18

EDU_LEVELS = ("博士", "硕士", "本科", "专科", "高职")

# (fact_type, regex, unit, group)
PDF_RULES: list[tuple[str, re.Pattern[str], str]] = [
    ("graduates_total", re.compile(rf"毕业生(?:共有|共计|总数为)\s*{COUNT}\s*人"), "人"),
    ("graduates_level", re.compile(rf"(?:{'|'.join(EDU_LEVELS)})毕业生\s*{COUNT}\s*人"), "人"),
    # ---- 教学质量报告常见量化表述（官方原文，A 级）----
    ("faculty_total", re.compile(rf"专任教师(?:总数)?(?:为|共)?\s*{COUNT}\s*人"), "人"),
    ("student_faculty_ratio", re.compile(rf"生师比(?:为|约)?\s*[:：]?\s*([0-9]+(?:\.[0-9]+)?)"), "ratio_value"),
    ("dual_teacher_count", re.compile(rf"双师型教师\s*{COUNT}\s*人"), "人"),
    ("senior_title_count", re.compile(rf"高级职称的?(?:教师)?\s*{COUNT}\s*人"), "人"),
    ("industry_teacher_count", re.compile(rf"(?:具有)?(?:行业|企业)背景教师\s*{COUNT}\s*人"), "人"),
    ("training_base_count", re.compile(rf"(?:实习实训基地|校外实践基地|实践基地)\s*{COUNT}\s*个"), "个"),
    ("total_hours", re.compile(rf"(?:总学时|学时总数)(?:为)?\s*{COUNT}"), "学时"),
    ("practice_credit", re.compile(rf"实践(?:教学)?学分为\s*{COUNT}\s*学分"), "学分"),
    ("lab_credit", re.compile(rf"实验(?:教学)?学分为\s*{COUNT}\s*学分"), "学分"),
]


@dataclass
class PdfFact:
    fact_id: str
    school: str
    year: int | None
    fact_type: str
    value: float
    unit: str
    raw_text: str
    page: int | None
    source_document: str
    evidence_level: str = "A"
    confidence: float = 0.9
    level_label: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def infer_school_year(pdf_path: Path) -> tuple[str, int | None]:
    """Best-effort school/year inference from the report file name."""
    name = pdf_path.stem
    school_match = re.match(r"([\u4e00-\u9fff]{2,12}?(?:大学|学院))", name)
    school = school_match.group(1) if school_match else ""
    years = [int(y) for y in re.findall(r"(20\d{2})", name)]
    year = None
    if years:
        year = max(years)
    return school, year


def extract_pdf_facts(pdf: PdfText, *, school: str, year: int | None,
                      max_facts: int = 400) -> list[PdfFact]:
    if pdf.text_status != "ok":
        return []
    facts: list[PdfFact] = []
    cursor = 0
    seen: set[tuple[str, float]] = set()

    def add(fact_type: str, value: float, unit: str, line: str, page: int | None) -> None:
        key = (fact_type, value)
        if key in seen:
            return
        seen.add(key)
        facts.append(PdfFact(
            fact_id=f"pdf:{pdf.sha1[:8]}:{len(facts):04d}",
            school=school, year=year, fact_type=fact_type, value=value, unit=unit,
            raw_text=line[:300], page=page, source_document=pdf.path,
            level_label="官方原始数据直接得到",
        ))

    for raw_line in pdf.text.splitlines():
        line = raw_line.strip()
        page = pdf.page_of(cursor)
        cursor += len(raw_line) + 1
        if len(line) < 4 or len(line) > 400:
            continue
        # 1) 计数类：关键词 + 数值
        for fact_type, regex, unit in PDF_RULES:
            match = regex.search(line)
            if not match:
                continue
            number = match.group(1).replace(",", "")
            try:
                value = float(number)
            except ValueError:
                continue
            if value <= 0:
                continue
            add(fact_type, value, unit, line, page)
            if len(facts) >= max_facts:
                return facts

        # 2) 百分比类：取数值左侧窗口内最近的标签
        for value_match in PERCENT_VALUE.finditer(line):
            raw_value = float(value_match.group(1))
            if raw_value > 100:
                continue
            window_start = max(0, value_match.start() - LABEL_WINDOW)
            window = line[window_start:value_match.start()]
            best_type, best_pos = None, -1
            for fact_type, label_re in PERCENT_LABELS:
                hits = list(label_re.finditer(window))
                if not hits:
                    continue
                pos = hits[-1].end()
                if pos > best_pos:
                    best_type, best_pos = fact_type, pos
            if best_type is None:
                continue
            add(best_type, round(raw_value / 100.0, 6), "ratio", line, page)
            if len(facts) >= max_facts:
                return facts
    return facts


def extract_pdf_facts_batch(items: Iterable[tuple[PdfText, str, int | None]]) -> list[PdfFact]:
    out: list[PdfFact] = []
    for pdf, school, year in items:
        out.extend(extract_pdf_facts(pdf, school=school, year=year))
    return out

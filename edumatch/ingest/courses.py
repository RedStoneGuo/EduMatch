"""Extract course entities from the curated education documents.

Course records keep the school/year context and the source line, so every
course→skill edge can be traced back to a sentence in a report. Credits are only
filled when the document states them; otherwise ``credits`` stays ``None`` and
the matrix falls back to a neutral weight of 1.0.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from ..ontology import load_ontology

QUOTED = re.compile(r"[《“\"]([^》”\"]{2,30})[》”\"]")
CREDIT = re.compile(r"([0-9]+(?:\.[0-9]+)?)\s*学分")
PRACTICE_HINT = re.compile(r"实践|实训|实习|项目制|课程设计|实验")
SPLIT = re.compile(r"[、,，;；]")
COURSE_HINT = re.compile(r"课|学|论|导论|基础|技术|设计|实验|实践|实训|工程|原理|方法|分析|建模|编程|系统|算法|应用|开发|案例|研讨|概论")
STRICT_NAME = re.compile(r"^[\u4e00-\u9fffA-Za-z0-9+·]{3,20}$")
TRAILING = re.compile(r"(等课程|等课|课程|课)$")
NOT_COURSE = re.compile(
    r"报告|表\d|届|学院|系别|专业|培养方案|计划|名单|附件|政策|通知|意见|规定|办法|"
    r"会议|活动|方案|简章|目录|说明|来源|数据|就业|师资|基地|学分|比例|人数"
)


@dataclass
class CourseRecord:
    course_id: str
    school: str
    year: int | None
    major: str | None
    name: str
    category: str
    credits: float | None
    practice_hours: float | None
    is_practice: bool
    description: str
    source_document: str
    evidence_level: str = "D"
    #: 课程所属专业族，由来源文件推导（majors_<family>.txt / 旧版教学.txt=ai）。
    #: 缺失时表示无法判定归属，不得据此推断成其他专业族的课程。
    family: str | None = None
    #: 必修/选修。None = 来源未可靠标注（供给侧按中性 1.0 处理，不猜）。
    is_required: bool | None = None
    to_dict = asdict


def _school_and_year(lines: list[str]) -> tuple[list[str], list[int | None]]:
    """Return per-line school name and year by scanning headings."""
    from .education_facts import SCHOOL_LINE, YEAR_HEADING

    schools: list[str] = []
    years: list[int | None] = []
    school, year = "", None
    for line in lines:
        m = YEAR_HEADING.match(line.strip())
        if m:
            year = int(m.group(1))
        m2 = SCHOOL_LINE.match(line.strip())
        if m2 and len(m2.group(1)) >= 4:
            school = m2.group(1)
        schools.append(school)
        years.append(year)
    return schools, years


def extract_courses(paths: Iterable[Path], max_per_doc: int = 400) -> list[CourseRecord]:
    texts: list[tuple[str, str, int | None, str]] = []
    for path in paths:
        if not path.exists():
            continue
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        schools, years = _school_and_year(lines)
        for i, line in enumerate(lines):
            texts.append((line, schools[i], years[i], str(path)))
    return extract_courses_from_texts(texts, max_per_doc=max_per_doc)


def extract_courses_from_texts(
    texts: Iterable[tuple[str, str, int | None, str]],
    *,
    max_per_doc: int = 400,
) -> list[CourseRecord]:
    """``texts`` items are (line, school, year, source_document)."""
    ontology = load_ontology()
    known = [s.name for s in ontology.all_skills()]
    out: list[CourseRecord] = []
    counter = 0
    seen: set[tuple[str, int | None, str]] = set()
    doc_count = 0
    for text, school, year, source in texts:
        text = (text or "").strip()
        if not text:
            continue
        names: list[str] = []

        def accept(candidate: str) -> str | None:
            candidate = re.sub(r"^[\d\.、\s（()）]+", "", candidate).strip("　 ，。：:；;、")
            candidate = TRAILING.sub("", candidate)
            if not STRICT_NAME.match(candidate):
                return None
            if NOT_COURSE.search(candidate) or not COURSE_HINT.search(candidate):
                return None
            if not any(skill in candidate for skill in known):
                return None
            return candidate

        for m in QUOTED.finditer(text):
            cleaned = accept(m.group(1))
            if cleaned:
                names.append(cleaned)
        if "课" in text or "教学" in text:
            for fragment in SPLIT.split(text):
                cleaned = accept(fragment)
                if cleaned:
                    names.append(cleaned)
        for name in dict.fromkeys(names):
            key = (school, year, name)
            if key in seen or doc_count >= max_per_doc:
                continue
            seen.add(key)
            doc_count += 1
            counter += 1
            credit_match = CREDIT.search(text)
            credits = float(credit_match.group(1)) if credit_match else None
            out.append(
                CourseRecord(
                    course_id=f"course:{counter:04d}",
                    school=school or "未识别",
                    year=year,
                    major=None,
                    name=name,
                    category="实践" if PRACTICE_HINT.search(name + text) else "理论",
                    credits=credits,
                    practice_hours=None,
                    is_practice=bool(PRACTICE_HINT.search(name)),
                    description=text[:200],
                    source_document=source,
                )
            )
    return out

"""Policy ingestion: 147 official documents from the local source tree.

`.docx` 与 `.pdf` 都是一手原文，解析出的政策事实按证据等级 A 记录；两种格式都走
真实文本抽取（docx_reader / pdf_reader）。只有既没有文本层、也拿不到正文的
``.doc``/``.xls`` 才记为 ``text_status='extractor_unavailable'``——如实登记，
不静默丢弃，也不用猜测内容填充。
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..ontology import load_ontology, normalize_text
from .docx_reader import read_docx_text

AGENCY_PATTERNS: list[tuple[str, str]] = [
    ("国务院办公厅", "国务院办公厅"),
    ("中共中央办公厅", "中共中央办公厅"),
    ("人力资源社会保障部", "人力资源社会保障部"),
    ("人力资源和社会保障部", "人力资源社会保障部"),
    ("教育部", "教育部"),
    ("财政部", "财政部"),
    ("工业和信息化部", "工业和信息化部"),
    ("工信部", "工业和信息化部"),
    ("国家发展改革委", "国家发展改革委"),
    ("北京市人力资源和社会保障局", "北京市人力资源和社会保障局"),
    ("北京市", "北京市人民政府"),
    ("科技部", "科技部"),
    ("中央组织部", "中央组织部"),
    ("中共中央组织部", "中央组织部"),
]

POLICY_TYPE_PATTERNS: list[tuple[str, str]] = [
    ("办法", "管理办法"),
    ("方案", "实施方案"),
    ("意见", "意见"),
    ("通知", "通知"),
    ("计划", "计划"),
    ("法律", "法律"),
    ("规定", "规定"),
    ("规划", "规划"),
    ("公告", "公告"),
    ("简章", "招考简章"),
    ("报告", "报告"),
]

INDUSTRY_TERMS = [
    "人工智能", "新一代信息技术", "数字经济", "集成电路", "智能装备", "机器人",
    "新能源", "医疗健康", "生物医药", "智能网联汽车", "低空经济", "量子",
    "大数据", "云计算", "工业互联网", "智能制造", "绿色低碳",
]

TALENT_TERMS = [
    "高校毕业生", "就业", "创业", "人才", "紧缺人才", "急需紧缺", "见习", "实习",
    "基层就业", "就业服务", "职业指导", "技能培训", "高技能人才", "产教融合",
    "校企合作", "订单班", "学徒制",
]

EDUCATION_TERMS = [
    "学科专业", "专业设置", "培养方案", "课程", "教学改革", "syllabus",
    "学位", "研究生", "本科教育", "职业教育", "双一流", "拔尖人才", "育人",
    "实践教学", "教材",
]

SKILL_HINT_TERMS = [
    "数字技能", "数据分析", "编程", "算法", "机器学习", "深度学习", "大模型",
    "Python", "RAG", "智能体", "算力", "数据要素",
]


@dataclass
class PolicyRecord:
    policy_id: str
    title: str
    file_name: str
    relative_path: str
    extension: str
    publish_date: str | None
    year: int | None
    agency: str
    region: str
    policy_type: str
    policy_goal: str
    key_terms: list[str] = field(default_factory=list)
    industry_direction: list[str] = field(default_factory=list)
    talent_direction: list[str] = field(default_factory=list)
    education_direction: list[str] = field(default_factory=list)
    skills_related: list[str] = field(default_factory=list)
    evidence_quote: str = ""
    text_status: str = "ok"
    char_count: int = 0
    source: str = "data/source/政策文件"
    url: str | None = None
    retrieval_time: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _agency_of(name: str) -> str:
    for pattern, agency in AGENCY_PATTERNS:
        if pattern in name:
            return agency
    return "未识别机构"


def _policy_type_of(name: str) -> str:
    for pattern, ptype in POLICY_TYPE_PATTERNS:
        if pattern in name:
            return ptype
    return "其他"


def _year_of(name: str, text: str) -> int | None:
    years = [int(y) for y in re.findall(r"(20[0-2]\d)", name)]
    if years:
        return max(years)
    head = text[:2000]
    years = [int(y) for y in re.findall(r"(20[0-2]\d)\s*年", head)]
    return max(years) if years else None


def _collect(text: str, terms: list[str]) -> list[str]:
    norm = normalize_text(text)
    return sorted({t for t in terms if normalize_text(t) in norm})


def _first_goal_sentence(text: str, title: str) -> str:
    for raw in text.splitlines():
        line = raw.strip()
        if len(line) < 15 or line.startswith(("附件", "目录")):
            continue
        if any(k in line for k in ("为", "为深入", "现将", "现将有关事项", "为贯彻落实", "为做好")):
            return line[:300]
    for raw in text.splitlines():
        line = raw.strip()
        if len(line) >= 20:
            return line[:300]
    return title


def _read_pdf_text(path: Path) -> str:
    """抽取政策 PDF 正文；没有文本层时返回空串（调用方据此记 extractor_unavailable）。"""
    try:
        from .pdf_reader import extract_pdf

        result = extract_pdf(path)
    except Exception:  # noqa: BLE001 - 缺依赖/加密/损坏都不应中断整批装载
        return ""
    return result.text if getattr(result, "text_status", "") == "ok" else ""


def ingest_policy_dir(policy_dir: Path, max_chars: int = 20000) -> list[PolicyRecord]:
    ontology = load_ontology()
    records: list[PolicyRecord] = []
    seen_titles: dict[str, str] = {}
    # 跳过目录说明文件：公开包里的占位 README.md 不是政策原文，不能被当成一条政策
    files = sorted(p for p in policy_dir.rglob("*")
                   if p.is_file() and p.name.lower() != "readme.md")
    for idx, path in enumerate(files, start=1):
        title = path.stem.strip()
        rel = str(path.relative_to(policy_dir))
        record = PolicyRecord(
            policy_id=f"pol:{idx:04d}",
            title=title,
            file_name=path.name,
            relative_path=rel,
            extension=path.suffix.lower(),
            publish_date=None,
            year=_year_of(title, ""),
            agency=_agency_of(title),
            region="北京" if "北京" in title or "本市" in title else "国家",
            policy_type=_policy_type_of(title),
            policy_goal="",
        )
        suffix = path.suffix.lower()
        if suffix == ".docx":
            text = read_docx_text(path)
        elif suffix == ".pdf":
            text = _read_pdf_text(path)
        elif suffix in {".txt", ".md"}:
            text = path.read_text(encoding="utf-8", errors="replace")
        else:
            text = ""
            record.text_status = "extractor_unavailable"
        if text:
            text = text[:max_chars]
            record.char_count = len(text)
            record.year = record.year or _year_of(title, text)
            record.policy_goal = _first_goal_sentence(text, title)
            record.evidence_quote = record.policy_goal[:300]
            record.industry_direction = _collect(text, INDUSTRY_TERMS)
            record.talent_direction = _collect(text, TALENT_TERMS)
            record.education_direction = _collect(text, EDUCATION_TERMS)
            record.skills_related = _collect(text, SKILL_HINT_TERMS)
            record.key_terms = sorted(
                set(record.industry_direction + record.talent_direction + record.education_direction)
            )
            for mention in ontology.extract(text[:6000]):
                skill = ontology.get(mention.skill_id)
                if skill and skill.name not in record.skills_related:
                    record.skills_related.append(skill.name)
        norm_title = re.sub(r"[\s　]+", "", title).replace("_", "")
        if norm_title in seen_titles:
            record.policy_goal = record.policy_goal or "(重复文件)"
        else:
            seen_titles[norm_title] = record.policy_id
        records.append(record)
    return records


def deduplicate(records: list[PolicyRecord]) -> tuple[list[PolicyRecord], list[dict[str, str]]]:
    """Collapse exact duplicate titles, keeping the richest record."""
    best: dict[str, PolicyRecord] = {}
    dupes: list[dict[str, str]] = []
    for rec in records:
        key = re.sub(r"[\s　]+", "", rec.title).replace("_", "").lower()
        current = best.get(key)
        if current is None or rec.char_count > current.char_count:
            if current is not None:
                dupes.append({"kept": rec.policy_id, "dropped": current.policy_id, "title": rec.title})
            best[key] = rec
        else:
            dupes.append({"kept": current.policy_id, "dropped": rec.policy_id, "title": rec.title})
    return list(best.values()), dupes

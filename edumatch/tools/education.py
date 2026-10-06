"""Education MCP group."""

from __future__ import annotations

from typing import Any

from edumatch.dataset import Dataset


def _obj(**props: Any) -> dict[str, Any]:
    return {"type": "object", "properties": props, "additionalProperties": False}


def search_school(ds: Dataset, args: dict[str, Any]) -> dict[str, Any]:
    family = args.get("family")
    schools = ds.schools(family)
    keyword = str(args.get("keyword") or "")
    hits = [s for s in schools if not keyword or keyword in s]
    return {
        "n": len(hits),
        "schools": [
            {
                "school": s,
                "n_facts": sum(1 for f in ds.facts if f.school == s),
                "years": sorted({f.year for f in ds.facts if f.school == s and f.year}),
            }
            for s in hits
        ],
        "evidence_level": "B",
    }


def search_major(ds: Dataset, args: dict[str, Any]) -> dict[str, Any]:
    major = str(args.get("major") or "人工智能")
    family = str(args.get("family") or "ai")
    return {
        "major": major,
        "family": family,
        "schools_covered": len(ds.schools(family)),
        "years": ds.years(family),
        "n_facts": sum(1 for f in ds.facts if f.family == family),
        "source_rule": "培养目标/课程/就业结果均来自归档报告抽取",
    }


def query_curriculum(ds: Dataset, args: dict[str, Any]) -> dict[str, Any]:
    school = args.get("school")
    include_template = bool(args.get("include_template", False))
    courses = ds.course_set(school=school, include_template=include_template)
    return {
        "n": len(courses),
        "scope": "school" if school else "cross_school_pool",
        "courses": courses,
        "template_used": any(c.get("template") for c in courses),
        "warning": "模板课程标记为 evidence_level=E，不是档案原始数据。",
    }


def query_employment(ds: Dataset, args: dict[str, Any]) -> dict[str, Any]:
    family = str(args.get("family") or "ai")
    school = args.get("school")
    major = args.get("major")
    out = {}
    for fact_type in ("placement_rate", "signing_rate", "further_study_rate", "employment_rate", "graduates"):
        out[fact_type] = ds.latest_facts(family, school, fact_type, major_preferred=major)
    out["source_rule"] = "就业结果只取自就业质量报告；招聘数据不得用于推算就业率。"
    return out


def find_report_evidence(ds: Dataset, args: dict[str, Any]) -> dict[str, Any]:
    fact_types = args.get("fact_types")
    school = args.get("school")
    hits = [
        f for f in ds.facts
        if (not school or f.school == school) and (not fact_types or f.fact_type in fact_types)
    ]
    return {"n": len(hits), "items": [f.__dict__ for f in hits[:200]]}


def get_report(ds: Dataset, args: dict[str, Any]) -> dict[str, Any]:
    path = ds.settings.processed_dir / "archive_documents.json"
    if not path.exists():
        return {"status": "insufficient_evidence", "reason": "先运行 scripts/archive_inventory_report.py"}
    import json

    records = json.loads(path.read_text(encoding="utf-8"))
    category = args.get("category")
    school = args.get("school")
    hits = [r for r in records if (not category or r["category"] == category) and (not school or r.get("school") == school)]
    return {"n": len(hits), "documents": hits[:200]}


def specs():
    from .registry import ToolSpec

    return [
        ToolSpec("search_school", "education", "检索归档覆盖的高校及其年份、事实数量",
                 _obj(keyword={"type": "string"}, family={"type": "string"}), search_school,
                 returns="school list with coverage"),
        ToolSpec("search_major", "education", "检索专业在归档中的覆盖情况",
                 _obj(major={"type": "string"}, family={"type": "string"}), search_major),
        ToolSpec("query_curriculum", "education", "查询课程清单（可含标记为 E 级的模板课程）",
                 _obj(school={"type": ["string", "null"]}, include_template={"type": "boolean"}),
                 query_curriculum),
        ToolSpec("query_employment", "education", "查询就业结果指标（就业率/签约率/深造率）",
                 _obj(family={"type": "string"}, school={"type": ["string", "null"]},
                      major={"type": ["string", "null"]}), query_employment,
                 returns="employment metrics with source metadata"),
        ToolSpec("find_report_evidence", "education", "按学校/指标类型召回原始证据行",
                 _obj(school={"type": ["string", "null"]}, fact_types={"type": "array", "items": {"type": "string"}}),
                 find_report_evidence),
        ToolSpec("get_report", "education", "查询归档文档清单与元数据",
                 _obj(category={"type": ["string", "null"]}, school={"type": ["string", "null"]}), get_report),
    ]

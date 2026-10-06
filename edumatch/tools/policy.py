"""Policy MCP group."""

from __future__ import annotations

from typing import Any

from edumatch.dataset import Dataset


def _obj(**props: Any) -> dict[str, Any]:
    return {"type": "object", "properties": props, "additionalProperties": False}


def search_policy(ds: Dataset, args: dict[str, Any]) -> dict[str, Any]:
    keyword = str(args.get("keyword") or "")
    year = args.get("year")
    agency = args.get("agency")
    hits = []
    for p in ds.policies:
        if keyword and keyword not in (p.title + " ".join(p.key_terms or [])):
            continue
        if year and p.year != year:
            continue
        if agency and agency not in p.agency:
            continue
        hits.append(p.to_dict())
    return {"n": len(hits), "policies": hits[:100], "total": len(ds.policies)}


def get_policy(ds: Dataset, args: dict[str, Any]) -> dict[str, Any]:
    pid = str(args.get("policy_id") or "")
    for p in ds.policies:
        if p.policy_id == pid or p.title == pid:
            return p.to_dict()
    return {"status": "insufficient_evidence", "reason": f"policy not found: {pid}"}


def find_policy_evidence(ds: Dataset, args: dict[str, Any]) -> dict[str, Any]:
    keyword = str(args.get("keyword") or "人工智能")
    hits = [
        {"policy_id": p.policy_id, "title": p.title, "quote": p.evidence_quote,
         "locator": p.relative_path, "evidence_level": "A" if p.text_status == "ok" else "E"}
        for p in ds.policies
        if keyword in p.title or keyword in " ".join(p.key_terms or []) or keyword in " ".join(p.skills_related or [])
    ]
    return {"n": len(hits), "evidence": hits[:100]}


def query_industry_direction(ds: Dataset, args: dict[str, Any]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for p in ds.policies:
        for i in p.industry_direction or []:
            counts[i] = counts.get(i, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: -kv[1])
    return {
        "n_documents": len(ds.policies),
        "directions": [{"industry": k, "mentions": v} for k, v in ranked],
        "evidence_level": "A",
        "note": "频次为政策文本提及次数，不代表政策强度或资金规模。",
    }


def query_talent_policy(ds: Dataset, args: dict[str, Any]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for p in ds.policies:
        for t in p.talent_direction or []:
            counts[t] = counts.get(t, 0) + 1
    return {
        "talents": [{"term": k, "mentions": v} for k, v in sorted(counts.items(), key=lambda kv: -kv[1])],
        "n_documents": len(ds.policies),
    }


def specs():
    from .registry import ToolSpec

    return [
        ToolSpec("search_policy", "policy", "按关键词/年份/机构检索政策",
                 _obj(keyword={"type": "string"}, year={"type": ["integer", "null"]},
                      agency={"type": "string"}), search_policy),
        ToolSpec("get_policy", "policy", "按 ID 或标题获取政策记录",
                 _obj(policy_id={"type": "string"}), get_policy),
        ToolSpec("find_policy_evidence", "policy", "召回政策原文证据片段",
                 _obj(keyword={"type": "string"}), find_policy_evidence),
        ToolSpec("query_industry_direction", "policy", "统计政策中的产业方向",
                 _obj(), query_industry_direction),
        ToolSpec("query_talent_policy", "policy", "统计政策中的人才相关表述",
                 _obj(), query_talent_policy),
    ]

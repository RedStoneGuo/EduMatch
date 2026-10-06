"""Evidence MCP group."""

from __future__ import annotations

from typing import Any

from edumatch.dataset import Dataset


def _obj(**props: Any) -> dict[str, Any]:
    return {"type": "object", "properties": props, "additionalProperties": False}


def _run(ds: Dataset, query: str = "证据检索"):
    from edumatch.engine import ResearchEngine

    return ResearchEngine(ds).run(query)


def search_evidence(ds: Dataset, args: dict[str, Any]) -> dict[str, Any]:
    keyword = str(args.get("keyword") or "")
    result = _run(ds, args.get("query") or keyword or "证据检索")
    items = result["evidence"]
    if keyword:
        items = [e for e in items if keyword in (e["title"] + e.get("quote", "") + e.get("locator", ""))]
    return {"n": len(items), "evidence": items[:100], "run_id": result["run_id"]}


def get_evidence(ds: Dataset, args: dict[str, Any]) -> dict[str, Any]:
    eid = str(args.get("evidence_id") or "")
    result = _run(ds, "证据获取")
    for item in result["evidence"]:
        if item["evidence_id"] == eid:
            return item
    return {"status": "insufficient_evidence", "reason": f"evidence not found: {eid}"}


def trace_claim(ds: Dataset, args: dict[str, Any]) -> dict[str, Any]:
    claim = str(args.get("claim") or "")
    result = _run(ds, "结论溯源")
    chain = []
    if "缺口" in claim or "gap" in claim.lower():
        gaps = result.get("skill_gaps") or {"rows": []}
        for row in gaps["rows"]:
            chain.append(
                {
                    "claim_component": row["skill"],
                    "metric": "Gap = Demand − Supply",
                    "calculation": {
                        "demand": row["demand"],
                        "supply": row["supply"],
                        "gap": row["gap"],
                    },
                    "evidence_chain": row["evidence_chain"],
                    "evidence_level": row["evidence_level"],
                    "confidence": row["confidence"],
                }
            )
    elif "TSI" in claim:
        dims = (result.get("tsi_v2") or {}).get("dimensions") or {}
        chain = [
            {"claim_component": name, "metric": "维度加权可用指标",
             "calculation": {"score": v["score"], "coverage": v["coverage"], "n_available": v["n_available"]},
             "evidence_level": "C", "confidence": v["confidence"]}
            for name, v in dims.items()
        ]
    else:
        chain = [
            {"claim_component": e["title"], "metric": "证据引用",
             "calculation": {"locator": e["locator"], "quote": e["quote"][:120]},
             "evidence_level": e["evidence_level"], "confidence": e["confidence"]}
            for e in result["evidence"][:10]
        ]
    return {
        "claim": claim,
        "trace": chain,
        "run_id": result["run_id"],
        "note": "所有数值均可由 analysis/ 下的纯函数复算，运行编号可回溯数据库记录。",
    }


def list_sources(ds: Dataset, args: dict[str, Any]) -> dict[str, Any]:
    result = _run(ds, "来源清单")
    sources = {}
    for item in result["evidence"]:
        key = item["locator"]
        sources.setdefault(key, {"locator": key, "n_evidence": 0, "levels": set()})
        sources[key]["n_evidence"] += 1
        sources[key]["levels"].add(item["evidence_level"])
    return {
        "n_sources": len(sources),
        "sources": [{**v, "levels": sorted(v["levels"])} for v in sources.values()],
        "archive_summary": ds.summary(),
    }


def specs():
    from .registry import ToolSpec

    return [
        ToolSpec("search_evidence", "evidence", "检索本轮分析的证据条目",
                 _obj(keyword={"type": "string"}, query={"type": "string"}), search_evidence),
        ToolSpec("get_evidence", "evidence", "按证据 ID 获取证据详情",
                 _obj(evidence_id={"type": "string"}), get_evidence),
        ToolSpec("trace_claim", "evidence", "把一个结论拆解到指标/计算/证据链",
                 _obj(claim={"type": "string"}), trace_claim),
        ToolSpec("list_sources", "evidence", "列出来源清单与证据等级分布",
                 _obj(), list_sources),
    ]

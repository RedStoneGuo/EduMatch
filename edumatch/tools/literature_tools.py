"""Academic retrieval tool group (fully automated, permission-checked)."""

from __future__ import annotations

import json
from typing import Any

from edumatch.dataset import Dataset


def _obj(**props: Any) -> dict[str, Any]:
    return {"type": "object", "properties": props, "additionalProperties": False}


def search_literature(ds: Dataset, args: dict[str, Any]) -> dict[str, Any]:
    path = ds.settings.processed_dir / "literature.json"
    offline: dict[str, Any] = {}
    if path.exists():
        offline = json.loads(path.read_text(encoding="utf-8"))

    if args.get("live"):
        from edumatch.literature import OpenAlexClient

        client = OpenAlexClient(ds.settings)
        works = client.search(str(args.get("query") or "talent supply demand higher education"),
                              limit=int(args.get("limit") or 20))
        return {
            "source": "openalex",
            "robots": "Allow: /",
            "live": True,
            "n_works": len(works),
            "works": [w.to_dict() for w in works],
            "audit": client.audit,
        }

    keyword = str(args.get("keyword") or "").lower()
    works = offline.get("works") or []
    if keyword:
        works = [w for w in works
                 if keyword in (w.get("title") or "").lower()
                 or keyword in (w.get("abstract") or "").lower()]
    if not works:
        return {
            "status": "insufficient_evidence",
            "reason": "本地没有文献缓存，请运行 python scripts/fetch_literature.py（OpenAlex，robots 允许）",
            "allowed_sources": ["api.openalex.org (Allow: /)", "api.crossref.org (no robots.txt)"],
            "blocked_sources": {"export.arxiv.org": "robots.txt: Disallow: /"},
        }
    return {
        "source": offline.get("source"),
        "retrieval_time": offline.get("retrieval_time"),
        "n_works": len(works),
        "works": works[: int(args.get("limit") or 20)],
    }


def trace_literature_support(ds: Dataset, args: dict[str, Any]) -> dict[str, Any]:
    """Map an indicator/claim to supporting literature records."""
    path = ds.settings.processed_dir / "literature.json"
    if not path.exists():
        return {"status": "insufficient_evidence",
                "reason": "先运行 scripts/fetch_literature.py"}
    works = json.loads(path.read_text(encoding="utf-8")).get("works") or []
    claim = str(args.get("claim") or "").lower()
    tokens = [t for t in claim.replace("，", " ").replace(",", " ").split() if len(t) > 1]
    scored = []
    for work in works:
        blob = f"{work.get('title','')} {work.get('abstract','')}".lower()
        score = sum(1 for t in tokens if t in blob)
        if score:
            scored.append((score, work))
    scored.sort(key=lambda kv: -kv[0])
    return {
        "claim": args.get("claim"),
        "n_supporting": len(scored),
        "support": [
            {"title": w["title"], "year": w["year"], "doi": w.get("doi"),
             "cited_by_count": w.get("cited_by_count"), "match_score": s}
            for s, w in scored[:8]
        ],
        "caveat": "文献支持用于方法论与机制假设的学术依据，不替代本项目的一手数据结论。",
    }


def specs():
    from .registry import ToolSpec

    return [
        ToolSpec("search_literature", "evidence",
                 "检索学术文献（OpenAlex，robots.txt 允许全自动访问；默认读本地缓存）",
                 _obj(query={"type": "string"}, keyword={"type": "string"},
                      limit={"type": "integer"}, live={"type": "boolean"}),
                 search_literature, returns="文献记录 + 抓取审计"),
        ToolSpec("trace_literature_support", "evidence", "为某个结论/指标找文献支撑",
                 _obj(claim={"type": "string"}), trace_literature_support),
    ]

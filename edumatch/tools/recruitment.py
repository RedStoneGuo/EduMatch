"""Recruitment MCP group (compliance-first)."""

from __future__ import annotations

from typing import Any

from edumatch.dataset import Dataset
from edumatch.jobs import crawler, dedup, normalize


def _obj(**props: Any) -> dict[str, Any]:
    return {"type": "object", "properties": props, "additionalProperties": False}


def crawl_jobs(ds: Dataset, args: dict[str, Any]) -> dict[str, Any]:
    urls = args.get("urls") or []
    from edumatch.jobs.adapters import list_adapters
    from edumatch.jobs.crawler import check_blocked_source

    blocked = [{"url": u, **check_blocked_source(u)} for u in urls if check_blocked_source(u)]
    if blocked:
        return {
            "status": "blocked_by_policy",
            "blocked": blocked,
            "adapters": list_adapters(),
            "alternative": [
                "浏览器正常检索并导出 HAR → 放入 data/raw/har/",
                "运行 python scripts/import_har_jobs.py 自动解析入库",
            ],
            "not_performed": ["复用会话凭据", "伪造请求头", "绕过验证码或频率限制"],
        }
    if not crawler.crawler_enabled():
        return {
            "status": "disabled",
            "reason": "合规默认关闭：需设置 EDUMATCH_ENABLE_CRAWLER=1，并已确认目标站点 robots.txt 与服务条款允许采集",
            "policy": {
                "respect_robots_txt": True,
                "request_interval_seconds": 3.0,
                "forbidden": ["登录抓取", "验证码绕过", "反爬绕过", "非公开数据"],
            },
            "urls_requested": urls,
            "adapters": list_adapters(),
        }
    policy = crawler.CrawlPolicy.from_settings(ds.settings)
    pages = crawler.crawl(urls, policy=policy)
    return {"status": "ok", "n_pages": len(pages), "note": "页面已缓存到 data/raw/cache"}


def normalize_job(ds: Dataset, args: dict[str, Any]) -> dict[str, Any]:
    norm = normalize.normalize_job(
        str(args.get("company") or ""), str(args.get("position") or ""),
        str(args.get("city") or ""), str(args.get("salary") or ""),
    )
    return {
        "company_norm": norm.company_norm,
        "position_norm": norm.position_norm,
        "city_norm": norm.city_norm,
        "salary": norm.salary,
        "fingerprint": norm.fingerprint,
        "content_key": norm.content_key,
    }


def deduplicate_samples(ds: Dataset, args: dict[str, Any]) -> dict[str, Any]:
    rows = args.get("rows") or []
    kept, report = dedup.deduplicate_jobs(rows)
    return {"kept": kept, "report": report.to_dict()}


def search_jobs(ds: Dataset, args: dict[str, Any]) -> dict[str, Any]:
    me = ds.market_evidence
    return {
        "dataset": me.get("dataset_id"),
        "source_document": me.get("source_document"),
        "counts": me.get("counts"),
        "positions": me.get("positions"),
        "evidence_level": me.get("evidence_level"),
        "note": "归档为聚合证据，不提供逐条岗位；raw/deduplicated/effective 均为 null。",
    }


def query_job_statistics(ds: Dataset, args: dict[str, Any]) -> dict[str, Any]:
    me = ds.market_evidence
    return {
        "city": args.get("city") or me.get("city"),
        "industry": args.get("industry") or me.get("industry"),
        "requirements": me.get("requirements"),
        "salary": me.get("salary"),
        "counts": me.get("counts"),
        "counts_status": "aggregate_only",
        "evidence_level": me.get("evidence_level"),
    }


def query_skill_frequency(ds: Dataset, args: dict[str, Any]) -> dict[str, Any]:
    demands = ds.demand_vector()
    return {
        "n_skills": len(demands),
        "items": [d.to_dict() for d in demands],
        "weights": "frequency .30 / position_coverage .25 / salary_premium .15 / policy .15 / industry .05 / trend .10（缺失项从分母剔除）",
    }


def query_salary(ds: Dataset, args: dict[str, Any]) -> dict[str, Any]:
    salary = ds.market_evidence.get("salary") or {}
    return {
        "raw": salary.get("raw"),
        "monthly_common_min": salary.get("monthly_common_min"),
        "monthly_common_max": salary.get("monthly_common_max"),
        "status": "ok" if salary else "insufficient_evidence",
        "caveat": "聚合区间，未按技能分组；技能薪资溢价（D5）因此为 null。",
    }


def query_job_trend(ds: Dataset, args: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "insufficient_evidence",
        "reason": "归档招聘证据只有一个时间截面，无法计算技能增长趋势；D4 因此记 null。",
        "required": "至少两个可比时间窗口的去重岗位数据",
    }


def specs():
    from .registry import ToolSpec

    return [
        ToolSpec("crawl_jobs", "recruitment", "合规抓取岗位（默认关闭，需显式开启并遵守 robots.txt）",
                 _obj(urls={"type": "array", "items": {"type": "string"}}), crawl_jobs, requires=["合规确认"]),
        ToolSpec("normalize_job", "recruitment", "岗位字段归一化与指纹生成",
                 _obj(company={"type": "string"}, position={"type": "string"}, city={"type": "string"},
                      salary={"type": "string"}), normalize_job),
        ToolSpec("deduplicate_jobs", "recruitment", "岗位去重：raw / deduplicated / effective 三口径",
                 _obj(rows={"type": "array", "items": {"type": "object"}}), deduplicate_samples),
        ToolSpec("search_jobs", "recruitment", "检索招聘证据集",
                 _obj(keyword={"type": "string"}), search_jobs),
        ToolSpec("query_job_statistics", "recruitment", "岗位统计（城市/行业/学历/经验/薪资）",
                 _obj(city={"type": "string"}, industry={"type": "string"}), query_job_statistics),
        ToolSpec("query_skill_frequency", "recruitment", "技能需求强度向量",
                 _obj(source={"type": "string"}), query_skill_frequency),
        ToolSpec("query_salary", "recruitment", "薪资统计",
                 _obj(city={"type": "string"}), query_salary),
        ToolSpec("query_job_trend", "recruitment", "岗位/技能时间趋势",
                 _obj(skill={"type": "string"}), query_job_trend),
    ]

"""University coverage state machine + Observed Job Posting Demand semantics.

Two upgrades from the raw counts:

1. **Coverage state machine (spec §11).**  A search hit is not coverage.  Each
   (school, major) target walks a fixed pipeline and is only counted as covered
   when it reaches ``READY_FOR_ANALYSIS``; earlier states are reported with
   their failure reason.

2. **Observed Job Posting Demand (spec §8).**  Posting counts describe what was
   observable in one data source / window / query - not the true labour-market
   demand.  :func:`observed_job_posting_demand` produces the canonical object so
   no report can present the number as "岗位总需求".
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Sequence

STATE_ORDER: tuple[str, ...] = (
    "DISCOVERED",
    "SOURCE_VERIFIED",
    "DOWNLOAD_ATTEMPTED",
    "FILE_VALIDATED",
    "ORIGINAL_FILE_SAVED",
    "TEXT_EXTRACTED",
    "READY_FOR_ANALYSIS",
)

STATE_LABEL: dict[str, str] = {
    "DISCOVERED": "已发现（仅搜索到线索，不等于覆盖）",
    "SOURCE_VERIFIED": "来源已核实",
    "DOWNLOAD_ATTEMPTED": "已尝试下载",
    "FILE_VALIDATED": "文件校验通过",
    "ORIGINAL_FILE_SAVED": "原件已入库",
    "TEXT_EXTRACTED": "正文已抽取",
    "READY_FOR_ANALYSIS": "可分析（只有到此状态才算覆盖）",
}

OBSERVED_DEMAND_LABEL = "Observed Job Posting Demand"
OBSERVED_DEMAND_CN = "可观察招聘岗位记录"

FORBIDDEN_DEMAND_TERMS: tuple[str, ...] = (
    "岗位总需求", "人才需求总量", "市场需求总人数", "社会岗位总需求",
    "就业人口", "企业招聘总量", "人才总供给",
)


@dataclass
class CoverageRecord:
    school: str
    major: str = ""
    state: str = "DISCOVERED"
    url: str = ""
    documents: list[str] = field(default_factory=list)
    reason: str = ""
    updated_at: str = ""

    def advance(self, state: str, *, reason: str = "") -> "CoverageRecord":
        if state not in STATE_ORDER:
            raise ValueError(f"unknown coverage state: {state}")
        current = STATE_ORDER.index(self.state) if self.state in STATE_ORDER else -1
        target = STATE_ORDER.index(state)
        if target < current:
            raise ValueError(
                f"不能从 {self.state} 回退到 {state}；如需重置请新建记录并写明原因")
        self.state = state
        self.reason = reason
        self.updated_at = datetime.now(timezone.utc).isoformat()
        return self

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "state_label": STATE_LABEL.get(self.state, self.state),
                "ready": self.state == "READY_FOR_ANALYSIS"}


def coverage_report(
    records: Sequence[CoverageRecord | Mapping[str, Any]],
    *,
    target_schools: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Aggregate coverage: covered / missing universities and failure reasons."""
    normalized: list[CoverageRecord] = []
    for record in records:
        if isinstance(record, CoverageRecord):
            normalized.append(record)
        else:
            normalized.append(CoverageRecord(
                school=str(record.get("school") or ""),
                major=str(record.get("major") or ""),
                state=str(record.get("state") or "DISCOVERED"),
                url=str(record.get("url") or ""),
                documents=list(record.get("documents") or []),
                reason=str(record.get("reason") or ""),
                updated_at=str(record.get("updated_at") or ""),
            ))
    covered = [r for r in normalized if r.state == "READY_FOR_ANALYSIS"]
    covered_schools = {r.school for r in covered if r.school}
    targets = set(target_schools) if target_schools is not None else {r.school for r in normalized if r.school}
    missing = sorted(s for s in targets if s not in covered_schools)
    failures: dict[str, int] = {}
    for record in normalized:
        if record.state != "READY_FOR_ANALYSIS" and record.reason:
            failures[record.reason] = failures.get(record.reason, 0) + 1
    n_targets = len(targets) if targets else len(normalized)
    return {
        "target_universities": sorted(targets),
        "covered_universities": sorted(covered_schools),
        "missing_universities": missing,
        "n_target": n_targets,
        "n_covered": len(covered_schools),
        "coverage_rate": round(len(covered_schools) / n_targets, 4) if n_targets else 0.0,
        "successful_documents": sum(len(r.documents) for r in covered),
        "failure_reasons": [{"reason": k, "n": v} for k, v in
                            sorted(failures.items(), key=lambda kv: -kv[1])],
        "records": [r.to_dict() for r in normalized],
        "note": ("只有到达 READY_FOR_ANALYSIS 的院校才计入覆盖；"
                 "搜索到 URL 不等于已覆盖。"),
    }


def observed_job_posting_demand(
    n_dedup: int,
    *,
    source: str = "本地招聘语料",
    window: str = "",
    city: str = "北京",
    n_raw: int | None = None,
    occupation: str = "",
    note: str = "",
) -> dict[str, Any]:
    """Canonical description of a posting count (spec §8)."""
    return {
        "label": OBSERVED_DEMAND_LABEL,
        "label_cn": OBSERVED_DEMAND_CN,
        "definition": ("当前数据源、当前时间窗口、当前检索规则下，"
                       "经清洗去重后可观察到的招聘岗位记录数。"),
        "not_meaning": ["社会岗位总需求", "就业人口", "岗位真实需求人数",
                        "企业招聘总量", "人才需求总量"],
        "n_dedup": int(n_dedup),
        "n_raw": None if n_raw is None else int(n_raw),
        "source": source,
        "window": window,
        "city": city,
        "occupation": occupation,
        "note": note or "这是市场活动样本，不是社会真实岗位总量。",
    }


def usage_caveat() -> str:
    return ("招聘记录只能作为 Observed Job Posting Demand（可观察市场活动样本）使用，"
            "不得表述为岗位总需求或人才需求总量；供给端也不得把覆盖院校课程池"
            "表述为北京市专业总供给。")

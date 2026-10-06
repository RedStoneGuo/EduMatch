"""Scenario slicing with dynamic selection (spec §15, §16, §25).

Scenario slicing must not explode into "4 layers × 5 slices × 3 scales".  This
module therefore selects the *valuable* slices for the user's goal first, then
slices the job corpus along the chosen dimensions, and hard-caps the number of
scenarios returned.

Supported (recommended) dimensions:

* ``job_type``              岗位类型
* ``industry``              行业
* ``experience_requirement`` 经验要求
* ``task_chain``            工作任务 / 技术链

The selection is deterministic keyword routing.  A slice that cannot be
extracted from the corpus is reported as ``insufficient_evidence`` - it is
never filled with a guess.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Mapping, Sequence

DIMENSIONS: tuple[str, ...] = (
    "job_type", "industry", "experience_requirement", "task_chain",
)

DIMENSION_LABEL: dict[str, str] = {
    "job_type": "岗位类型",
    "industry": "行业",
    "experience_requirement": "工作经验要求",
    "task_chain": "工作任务 / 技术链",
}

GOAL_HINTS: dict[str, tuple[str, ...]] = {
    "job_type": ("岗位", "工程师", "算法", "开发", "产品", "运营", "分析师"),
    "task_chain": ("技术链", "方向", "微调", "rag", "agent", "部署", "评测",
                   "数据工程", "多模态", "训练"),
    "industry": ("行业", "金融", "医疗", "制造", "教育", "政务", "互联网",
                 "能源", "汽车", "安防"),
    "experience_requirement": ("应届", "校招", "实习", "经验", "社招", "工作年限", "几年"),
}

DEFAULT_ORDER: tuple[str, ...] = (
    "job_type", "task_chain", "experience_requirement", "industry",
)

TASK_CHAIN_KEYWORDS: dict[str, tuple[str, ...]] = {
    "模型训练": ("训练", "预训练", "train"),
    "Fine-tuning": ("微调", "fine-tune", "finetune", "lora", "sft"),
    "RAG": ("rag", "检索增强", "向量检索", "知识库"),
    "Agent": ("agent", "智能体", "工具调用", "多智能体"),
    "Evaluation": ("评测", "评估", "benchmark", "ab test", "badcase"),
    "Deployment": ("部署", "推理", "上线", "vllm", "tensorrt", "服务化"),
    "Data Engineering": ("数据工程", "数据清洗", "etl", "数仓", "数据管道"),
    "AI Application": ("应用", "产品化", "落地", "业务"),
}

INDUSTRY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "金融": ("金融", "银行", "证券", "保险", "风控", "量化"),
    "医疗": ("医疗", "医学", "临床", "影像", "生物"),
    "制造": ("制造", "工业", "智能制造", "产线"),
    "教育": ("教育", "教学", "培训"),
    "政务": ("政务", "政府", "公共"),
    "互联网": ("互联网", "电商", "社交", "内容平台"),
    "能源": ("能源", "电力", "石油", "电网"),
    "汽车": ("汽车", "车联网", "自动驾驶", "座舱"),
}

EXPERIENCE_LEVELS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("不限经验", ("经验不限", "不限经验", "无经验要求")),
    ("应届生", ("应届", "校招", "毕业生")),
    ("1-3年", ("1-3年", "1至3年", "一年以上", "两年以上")),
    ("3-5年", ("3-5年", "3至5年", "三年以上", "五年")),
    ("5年以上", ("5年以上", "五年以上", "资深")),
)


def select_dimensions(goal_text: str | None, *, max_dimensions: int = 3) -> list[str]:
    """Pick the valuable scenario dimensions for a user goal (dynamic selection)."""
    text = (goal_text or "").lower()
    scored: list[tuple[int, int, str]] = []
    for order, dim in enumerate(DEFAULT_ORDER):
        hits = sum(1 for hint in GOAL_HINTS.get(dim, ()) if hint in text)
        scored.append((-hits, order, dim))
    scored.sort()
    selected = [dim for hits, _, dim in scored if -hits > 0]
    for _, _, dim in scored:
        if len(selected) >= max_dimensions:
            break
        if dim not in selected:
            selected.append(dim)
    return selected[:max_dimensions]


def _job_text(job: Mapping[str, Any]) -> str:
    return (str(job.get("position") or "") + " "
            + str(job.get("job_description") or "") + " "
            + str(job.get("industry") or "") + " "
            + str(job.get("experience") or "") + " "
            + str(job.get("description") or ""))


def _values_for(dim: str, text: str, job: Mapping[str, Any] | None = None) -> list[str]:
    if dim == "task_chain":
        return [name for name, kws in TASK_CHAIN_KEYWORDS.items()
                if any(k in text for k in kws)]
    if dim == "industry":
        return [name for name, kws in INDUSTRY_KEYWORDS.items()
                if any(k in text for k in kws)]
    if dim == "experience_requirement":
        return [name for name, kws in EXPERIENCE_LEVELS
                if any(k in text for k in kws)]
    if dim == "job_type":
        position = str((job or {}).get("position") or "").strip()
        return [position] if position else []
    return []


def plan_scenarios(
    goal_text: str | None,
    jobs: Sequence[Mapping[str, Any]],
    *,
    max_dimensions: int = 3,
    max_scenarios: int = 12,
) -> dict[str, Any]:
    """Select dimensions and count the feasible slices; never explode."""
    dims = select_dimensions(goal_text, max_dimensions=max_dimensions)
    scenarios: list[dict[str, Any]] = []
    for dim in dims:
        counter: Counter[str] = Counter()
        for job in jobs:
            for value in _values_for(dim, _job_text(job).lower(), job):
                counter[value] += 1
        for value, n in counter.most_common():
            scenarios.append({
                "dimension": dim, "dimension_label": DIMENSION_LABEL[dim],
                "value": value, "n_jobs": n, "status": "ok",
            })
    total_found = len(scenarios)
    capped = total_found > max_scenarios
    scenarios = sorted(scenarios, key=lambda s: -s["n_jobs"])[:max_scenarios]
    return {
        "goal": goal_text or "",
        "selected_dimensions": dims,
        "scenarios": scenarios,
        "n_total_before_cap": total_found,
        "max_scenarios": max_scenarios,
        "capped": capped,
        "strategy": "dynamic_scenario_selection",
        "note": ("按用户目标动态选切片；总数受 max_scenarios 限制，"
                 "未选维度不生成报告，避免指数爆炸。"),
    }


def slice_jobs(
    jobs: Sequence[Mapping[str, Any]],
    dimension: str,
    value: str,
) -> dict[str, Any]:
    """Deterministically slice the corpus along one dimension value."""
    if dimension not in DIMENSIONS:
        return {"status": "unsupported_dimension", "dimension": dimension,
                "value": value, "rows": [], "n_jobs": 0,
                "reason": f"不支持的场景维度：{dimension}"}
    rows = [job for job in jobs
            if value in _values_for(dimension, _job_text(job).lower(), job)]
    status = "ok" if rows else "insufficient_evidence"
    return {
        "status": status, "dimension": dimension, "dimension_label": DIMENSION_LABEL[dimension],
        "value": value, "rows": rows, "n_jobs": len(rows),
        "reason": "" if rows else f"语料中未观察到「{value}」切片，不输出该切片结论",
    }

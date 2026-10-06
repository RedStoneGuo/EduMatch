"""三尺度统一 Evaluation API：evaluate_macro / evaluate_middle / evaluate_micro。

这三个入口是"一个模型三个投影"的正式接口：输入各自尺度的对象，输出**同一套**
结果骨架（Primary TSI + TSI Tree + 四层画像 + Gap + Coverage/Confidence + run_id）。
它们只消费已经算好的确定性结果，不重新发明数字，因此可以安全地被 Agent、CLI、
演示页面和 MCP 复用。

    evaluate_macro  : 覆盖高校培养能力  × 岗位大类可观察招聘记录
    evaluate_middle : 某校某专业培养方案 × 目标岗位族
    evaluate_micro  : 个人证据画像      × 具体岗位需求
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from edumatch.profiles import (
    PersonalEvidenceProfile,
    SupplyProfile,
    apply_legacy_compat,
)
from edumatch.semantics import observed_demand_phrase

from . import micro as micro_mod
from . import tsi_tree as tsi_tree_mod

VERSION = "evaluation-1.0"


def _wrap(scale: str, primary: Mapping[str, Any] | None, *,
          tree: Mapping[str, Any] | None = None,
          profiles: Mapping[str, Any] | None = None,
          gaps: Any = None,
          coverage: Any = None,
          confidence: Any = None,
          run_id: str = "",
          extra: Mapping[str, Any] | None = None) -> dict[str, Any]:
    primary = primary or {}
    result = {
        "version": VERSION,
        "scale": scale,
        "run_id": run_id,
        "primary_tsi": primary.get("primary_tsi"),
        "band": primary.get("band"),
        "tsi_versions": primary.get("versions") or {},
        "dimensions": primary.get("dimensions") or {},
        "metrics": primary.get("metrics") or [],
        "missing_indicators": primary.get("missing_indicators") or [],
        "weighted_coverage": primary.get("weighted_coverage"),
        "confidence": primary.get("confidence"),
        "tsi_tree": tree or {},
        "profiles": dict(profiles or {}),
        "gaps": gaps,
        "coverage": coverage,
        "confidence_detail": confidence,
        "method_note": (
            "Primary TSI 是唯一正式总分；Match / Skill Fit 为子指标。"
            "缺失记 None，不记 0。"
        ),
    }
    result.update(extra or {})
    # 旧字段兼容：match → structural_fit 等（保留旧键）
    return apply_legacy_compat(result)


def evaluate_macro(
    primary: Mapping[str, Any],
    *,
    fit: Mapping[str, Any] | None = None,
    supply_vector: Any = None,
    demand: Mapping[str, float] | None = None,
    coverage: Mapping[str, Any] | None = None,
    scenario: Mapping[str, Any] | None = None,
    evidence_index: Mapping[str, Mapping[str, Any]] | None = None,
    occupation: Mapping[str, Any] | None = None,
    run_id: str = "",
) -> dict[str, Any]:
    """区域尺度：供给口径是"覆盖高校培养能力"，需求口径是 Observed Job Posting Demand。"""
    tree = tsi_tree_mod.build_tsi_tree(primary, fit=fit, evidence_index=evidence_index)
    profile = (SupplyProfile.from_supply_vector(supply_vector, scale="regional")
               .to_dict() if supply_vector is not None else {})
    observed = None
    if occupation:
        n = occupation.get("n_jobs")
        if isinstance(n, int):
            observed = {"label": "Observed Job Posting Demand",
                        "phrase": observed_demand_phrase(f"{n:,}"),
                        "occupation": occupation.get("occupation"),
                        "match_scope": occupation.get("match_scope")}
    return _wrap(
        "macro", primary, tree=tree,
        profiles={"supply": profile, "demand_requirements": dict(demand or {})},
        gaps=(fit or {}).get("per_skill"),
        coverage=coverage, confidence=None, run_id=run_id,
        extra={"observed_demand": observed, "scenario": scenario or {},
               "supply_scope_note": "覆盖高校样本，非全市全量；不得表述为区域总供给。"},
    )


def evaluate_middle(
    primary: Mapping[str, Any],
    *,
    fit: Mapping[str, Any] | None = None,
    supply_vector: Any = None,
    demand: Mapping[str, float] | None = None,
    occupation_match: Mapping[str, Any] | None = None,
    benchmark: Mapping[str, Any] | None = None,
    conflicts: Mapping[str, Any] | None = None,
    scenario: Mapping[str, Any] | None = None,
    evidence_index: Mapping[str, Mapping[str, Any]] | None = None,
    run_id: str = "",
) -> dict[str, Any]:
    """专业尺度：培养方案（Supply） × 目标岗位族（Demand）。"""
    tree = tsi_tree_mod.build_tsi_tree(primary, fit=fit, evidence_index=evidence_index)
    profile = (SupplyProfile.from_supply_vector(supply_vector, scale="major")
               .to_dict() if supply_vector is not None else {})
    sub = dict(occupation_match or {})
    return _wrap(
        "middle", primary, tree=tree,
        profiles={"supply": profile, "demand_requirements": dict(demand or {})},
        gaps=(fit or {}).get("per_skill"),
        coverage=(primary.get("dimensions") or {}), confidence=primary.get("confidence"),
        run_id=run_id,
        extra={
            "sub_indicators": {
                # Match 是子指标：对外统一读 primary_tsi
                "structural_fit_100": sub.get("match_100"),
                "skill_fit_100": (fit or {}).get("fit_100"),
            },
            "benchmark": dict(benchmark or {}),
            "conflict_resolution": dict(conflicts or {}),
            "scenario": scenario or {},
        },
    )


def evaluate_micro(
    profile: PersonalEvidenceProfile,
    demand: Mapping[str, float],
    *,
    demand_meta: Mapping[str, Any] | None = None,
    occupation: Mapping[str, Any] | None = None,
    major_baseline: Mapping[str, float] | None = None,
    scenario: Mapping[str, Any] | None = None,
    run_id: str = "",
) -> dict[str, Any]:
    """个人尺度：Personal Evidence Profile × 具体岗位需求。"""
    analyzed = micro_mod.analyze_micro(
        profile, demand, demand_meta=demand_meta, occupation=occupation,
        major_baseline=major_baseline,
    )
    analyzed["run_id"] = run_id
    analyzed["version"] = VERSION
    analyzed["priority_actions"] = micro_mod.priority_actions(analyzed)
    analyzed["tsi_tree"] = {}   # 个人尺度暂不产出 Primary TSI，按证据分层诊断
    analyzed["scenario"] = scenario or {}
    analyzed["method_note"] = (
        "微观按 L0–L4 证据分层诊断；不虚构 Primary TSI。"
        "Knowledge / Skill / Experience-Practice 三类缺口分别输出。"
    )
    return analyzed


def evaluate(
    scale: str,
    *args: Any,
    **kwargs: Any,
) -> dict[str, Any]:
    """按尺度名分派，便于 Agent/MCP 统一调用。"""
    if scale in {"macro", "regional", "区域", "宏观"}:
        return evaluate_macro(*args, **kwargs)
    if scale in {"middle", "meso", "major", "中观", "专业"}:
        return evaluate_middle(*args, **kwargs)
    if scale in {"micro", "personal", "微观", "个人"}:
        return evaluate_micro(*args, **kwargs)
    raise ValueError(f"unknown scale: {scale}")

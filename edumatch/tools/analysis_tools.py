"""Analysis MCP group: thin wrappers over the pure analysis engine."""

from __future__ import annotations

from typing import Any

from analysis import mechanism, simulation as simulation_mod, skill_gap, trend, tsi
from edumatch.dataset import Dataset


def _obj(**props: Any) -> dict[str, Any]:
    return {"type": "object", "properties": props, "additionalProperties": False}


def _engine(ds: Dataset):
    from edumatch.engine import ResearchEngine

    return ResearchEngine(ds)


def calculate_skill_gap(ds: Dataset, args: dict[str, Any]) -> dict[str, Any]:
    result = _engine(ds).run(str(args.get("query") or "技能缺口分析"))
    return {
        "skill_gap_index": result["skill_gaps"]["skill_gap_index"],
        "rows": result["skill_gaps"]["rows"],
        "crosscheck": result["skill_gaps"].get("reported_gap_crosscheck"),
        "run_id": result["run_id"],
    }


def calculate_matching(ds: Dataset, args: dict[str, Any]) -> dict[str, Any]:
    result = _engine(ds).run(
        str(args.get("query") or "匹配度分析"),
        include_template=bool(args.get("include_template", False)),
    )
    return {
        "matching": result["matching"],
        "course_scope": result["course_scope"],
        "matrix_summary": {
            "n_courses": len(result["course_skill_matrix"]["course_ids"]),
            "n_skills": len(result["course_skill_matrix"]["skills"]),
            "reference_credits": result["course_skill_matrix"]["reference_credits"],
        },
        "run_id": result["run_id"],
    }


def calculate_tsi(ds: Dataset, args: dict[str, Any]) -> dict[str, Any]:
    result = _engine(ds).run(
        str(args.get("query") or "TSI 计算"),
        include_template=bool(args.get("include_template", False)),
    )
    return {"tsi_v2": result["tsi_v2"], "metrics": result["metrics"], "run_id": result["run_id"]}


def calculate_skill_coverage(ds: Dataset, args: dict[str, Any]) -> dict[str, Any]:
    result = _engine(ds).run("技能覆盖", include_template=bool(args.get("include_template", True)))
    matrix = result["course_skill_matrix"]
    return {
        "supply": matrix["supply"],
        "supply_share": matrix["supply_share"],
        "credits_by_skill": matrix["credits_by_skill"],
        "unmapped_courses": matrix["unmapped_courses"],
        "reference_credits": matrix["reference_credits"],
    }


def run_trend_analysis(ds: Dataset, args: dict[str, Any]) -> dict[str, Any]:
    family = str(args.get("family") or "ai")
    school = args.get("school")
    fact_type = str(args.get("fact_type") or "placement_rate")
    series = ds.fact_series(family, fact_type, school)
    return trend.series_summary(series, label=f"{fact_type}@{school or 'all'}")


def run_regression(ds: Dataset, args: dict[str, Any]) -> dict[str, Any]:
    result = _engine(ds).run("机制回归")
    features = {
        "practice_credit_ratio": [r.get("practice_credit_ratio") for r in ds_school_records(ds)],
        "senior_title_ratio": [r.get("senior_title_ratio") for r in ds_school_records(ds)],
    }
    target = [r.get("placement_rate") for r in ds_school_records(ds)]
    out = mechanism.ols(features, target)
    out["engine_run"] = result["run_id"]
    return out


def ds_school_records(ds: Dataset) -> list[dict[str, Any]]:
    from edumatch.engine import ResearchEngine, build_plan

    plan = build_plan("横向比较", ds)
    return ResearchEngine(ds)._school_records(
        plan, ["placement_rate", "practice_credit_ratio", "senior_title_ratio", "student_faculty_ratio"]
    )


def run_shap_analysis(ds: Dataset, args: dict[str, Any]) -> dict[str, Any]:
    records = ds_school_records(ds)
    features = {k: [r.get(k) for r in records] for k in
                ("practice_credit_ratio", "senior_title_ratio", "student_faculty_ratio")}
    target = [r.get("placement_rate") for r in records]
    result = mechanism.permutation_importance(features, target)
    result["method"] = "permutation_importance（SHAP 依赖未安装时的等价可解释替代方案）"
    return result


def compare_schools(ds: Dataset, args: dict[str, Any]) -> dict[str, Any]:
    result = _engine(ds).run(str(args.get("query") or "高校横向比较"), include_template=False)
    return result["benchmark"]


def compare_majors(ds: Dataset, args: dict[str, Any]) -> dict[str, Any]:
    families = args.get("families") or ["ai", "cs"]
    out = {}
    for family in families:
        out[family] = {
            "n_facts": sum(1 for f in ds.facts if f.family == family),
            "schools": len(ds.schools(family)),
            "years": ds.years(family),
            "placement_rate_benchmark": ds.benchmark(family, "placement_rate"),
            "practice_credit_ratio_benchmark": ds.benchmark(family, "practice_credit_ratio"),
        }
    return out


def simulate_curriculum_change(ds: Dataset, args: dict[str, Any]) -> dict[str, Any]:
    result = _engine(ds).run(
        str(args.get("query") or "培养方案模拟"), include_template=True, simulation=True
    )
    sim = result["simulation"]
    return {
        "combined_scenario": sim["combined_scenario"],
        "single_scenarios": sim["single_scenarios"],
        "assumptions": sim["assumptions"],
        "disclaimer": sim["disclaimer"],
        "run_id": result["run_id"],
    }


def specs():
    from .registry import ToolSpec

    common = {"query": {"type": "string"}, "include_template": {"type": "boolean"}}
    return [
        ToolSpec("calculate_skill_gap", "analysis", "计算 Skill Gap Index 与逐技能缺口",
                 _obj(**common), calculate_skill_gap, returns="gap rows with evidence level"),
        ToolSpec("calculate_matching", "analysis", "计算需求加权匹配度（非 TF-IDF 余弦）",
                 _obj(**common), calculate_matching),
        ToolSpec("calculate_tsi", "analysis", "计算 TSI 2.0（缺失记 null，维度覆盖率不足则剔除）",
                 _obj(**common), calculate_tsi),
        ToolSpec("calculate_skill_coverage", "analysis", "计算课程对技能的加权供给",
                 _obj(include_template={"type": "boolean"}), calculate_skill_coverage),
        ToolSpec("run_trend_analysis", "analysis", "时间趋势分析（少于两期返回证据不足）",
                 _obj(family={"type": "string"}, school={"type": ["string", "null"]},
                      fact_type={"type": "string"}), run_trend_analysis),
        ToolSpec("run_regression", "analysis", "OLS 条件关联分析",
                 _obj(), run_regression),
        ToolSpec("run_shap_analysis", "analysis", "特征解释贡献（置换重要性）",
                 _obj(), run_shap_analysis),
        ToolSpec("compare_schools", "analysis", "同类专业高校横向比较",
                 _obj(query={"type": "string"}), compare_schools),
        ToolSpec("compare_majors", "analysis", "跨专业家族比较",
                 _obj(families={"type": "array", "items": {"type": "string"}}), compare_majors),
        ToolSpec("simulate_curriculum_change", "analysis", "培养方案 what-if 模拟",
                 _obj(query={"type": "string"}), simulate_curriculum_change),
    ]

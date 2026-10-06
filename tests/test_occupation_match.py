"""目标岗位输入：解析 → 岗位切片 → 岗位需求向量 → 岗位匹配度。"""

from __future__ import annotations

import pytest

from agent.report import render_markdown
from analysis import occupation_match
from edumatch.occupation import MIN_OCCUPATION_JOBS, resolve_occupation, slice_jobs


def test_occupation_resolution_is_deterministic():
    assert resolve_occupation("大模型算法工程师").id == "llm_algorithm"
    assert resolve_occupation("计算机视觉算法工程师").id == "cv_algorithm"
    assert resolve_occupation("大数据开发工程师").id == "data_engineering"
    assert resolve_occupation("AI产品经理").id == "ai_product"
    assert resolve_occupation("人工智能").id == "ai_all"
    assert resolve_occupation("人工智能相关岗位").id == "ai_all"
    assert resolve_occupation("航天器总体设计") is None
    assert resolve_occupation("") is None


def test_unknown_occupation_is_not_guessed():
    info = slice_jobs([{"position": "算法工程师"}], "航天器总体设计")
    assert info["status"] == "unresolved"
    assert info["rows"] == [] and info["n_jobs"] == 0


def test_occupation_slice_prefers_position_then_falls_back():
    jobs = [{"position": "大模型算法工程师"}, {"position": "Java开发"}]
    info = slice_jobs(jobs, "大模型算法工程师", min_jobs=1)
    assert info["status"] == "ok" and info["match_scope"] == "position"
    assert info["n_jobs"] == 1
    info2 = slice_jobs(jobs, "大模型算法工程师", min_jobs=5)
    assert info2["status"] == "insufficient_evidence"
    assert info2["n_jobs"] == 1


def test_occupation_demand_differs_from_the_whole_market(dataset):
    llm_demand, llm_info = dataset.occupation_demand("大模型算法工程师")
    all_demand, all_info = dataset.occupation_demand("人工智能相关岗位")
    assert llm_info["n_jobs"] >= MIN_OCCUPATION_JOBS
    assert llm_info["match_scope"] == "position"
    assert all_info["n_jobs"] > llm_info["n_jobs"]
    llm = {d.skill_name: d.demand for d in llm_demand}
    everything = {d.skill_name: d.demand for d in all_demand}
    # 目标岗位越具体，标志性技能的权重应越高
    assert llm["大模型"] > everything["大模型"]
    assert llm["深度学习"] > everything["深度学习"]


def test_occupation_match_is_the_same_demand_weighted_math():
    supply = {"a": 0.5, "b": 0.0}
    demand = {"a": 1.0, "b": 1.0}
    result = occupation_match.match_occupation(supply, demand)
    assert result["match_score"] == pytest.approx(0.25)
    assert result["match_100"] == 25.0
    assert result["band"] == "匹配不足"
    assert result["n_skills_covered"] == 1
    assert result["n_skills_missing"] == 1
    rows = {r["skill"]: r for r in result["per_skill"]}
    assert rows["b"]["gap"] == 1.0


def test_definitional_skills_enter_the_denominator():
    """岗位族定义性技能即使没被抽到，也要计入分母，否则匹配度会被高估。"""
    result = occupation_match.match_occupation(
        {"人工智能": 1.0}, {"人工智能": 1.0}, extra_demand=["大模型", "RAG"])
    assert set(result["definitional_skills"]) == {"大模型", "RAG"}
    assert result["definitional_covered"] == []
    assert set(result["definitional_missing"]) == {"大模型", "RAG"}
    assert result["match_score"] < 1.0


def test_bands():
    assert occupation_match.band_of(0.9) == "高度匹配"
    assert occupation_match.band_of(0.7) == "较匹配"
    assert occupation_match.band_of(0.5) == "部分匹配"
    assert occupation_match.band_of(0.2) == "匹配不足"
    assert occupation_match.band_of(None) is None


def test_missing_supply_yields_insufficient_not_zero():
    result = occupation_match.match_occupation(
        {}, {"a": 1.0}, supply_status="insufficient_evidence", supply_reason="该校无课程证据")
    assert result["match_score"] is None
    assert result["status"] == "insufficient_evidence"
    assert "课程" in result["reason"]


@pytest.fixture(scope="module")
def job_result(engine) -> dict:
    return engine.run(
        "分析北京工业大学人工智能专业与大模型算法工程师岗位的匹配度",
        include_template=True, target_occupation="大模型算法工程师",
    )


def test_engine_outputs_occupation_match(job_result):
    plan = job_result["plan"]
    assert plan["target_occupation"] == "大模型算法工程师"
    occ = job_result["occupation"]
    match = job_result["occupation_match"]
    assert occ["occupation"]["name"] == "大模型算法工程师"
    assert occ["n_jobs"] >= MIN_OCCUPATION_JOBS
    assert match["match_100"] is not None
    assert match["band"] and match["n_skills_compared"] > 0
    assert match["supply_provenance"] == "school_specific"
    # 岗位匹配度作为一等指标进入 metrics（与 TSI 主分并列展示）
    ids = {m["metric_id"]: m for m in job_result["metrics"]}
    assert ids["JOB1"]["value"] == match["match_100"]
    # 对照口径必须存在且标注为基准
    bench = occ.get("benchmark_match") or {}
    assert bench.get("supply_provenance") == "peer_benchmark"


def test_occupation_appears_in_the_report_headline(job_result):
    report = render_markdown(job_result)
    assert "目标岗位匹配度" in report
    assert "大模型算法工程师" in report
    assert all(f"## {i}." in report for i in range(1, 19))
    assert not any(p in report for p in ("导致", "证明了", "必然导致"))


def test_unresolvable_occupation_is_reported_honestly(engine):
    result = engine.run(
        "分析北京工业大学人工智能专业与航天器总体设计岗位的匹配度",
        include_template=True, target_occupation="航天器总体设计",
    )
    assert result["occupation_match"] is None
    assert result["occupation"]["status"] == "insufficient_evidence"
    report = render_markdown(result)
    assert "证据不足" in report

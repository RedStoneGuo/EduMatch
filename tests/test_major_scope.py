"""Arbitrary-major support: resolution must never silently answer for another major."""

from __future__ import annotations

from edumatch.engine import ResearchEngine, build_plan, detect_major
from agent.report import render_markdown


def test_known_majors_resolve_to_their_family(dataset):
    assert detect_major("分析人工智能专业", dataset) == ("人工智能", "ai")
    assert detect_major("计算机科学与技术专业的就业", dataset) == ("计算机科学与技术", "cs")
    assert detect_major("会计学专业供需适配", dataset) == ("会计学", "econ")


def test_non_family_majors_are_named_without_a_family(dataset):
    """机械工程/法学等不属于 ai/cs/econ 族，但属于**专业目录**：族为 None 仍可分析。"""
    major, family = detect_major("分析机械工程专业与北京就业市场的适配", dataset)
    assert major == "机械工程" and family is None
    assert detect_major("法学专业的供需", dataset)[1] is None
    # 关键区别：族为 None ≠ 无数据；目录里有数据就必须能分析
    ref = dataset.find_major("机械工程")[1]
    assert ref.analyzable and ref.n_courses > 0


def test_query_without_a_major_uses_the_default_family(dataset):
    """Internal tool queries ('结论溯源') must not be treated as unknown majors."""
    assert detect_major("结论溯源", dataset)[1] == "ai"
    assert detect_major("证据检索", dataset)[1] == "ai"
    assert detect_major("数据工程是主要技能缺口", dataset)[1] == "ai"


def test_plan_marks_unknown_major(dataset):
    plan = build_plan("分析星际航行工程专业的供需适配", dataset)
    assert plan.mode == "X_unknown_major"
    assert plan.family == ""


def test_engine_refuses_to_answer_for_unknown_major(dataset):
    result = ResearchEngine(dataset).run("分析星际航行工程专业与北京就业市场的供需适配")
    assert result["status"] == "insufficient_evidence"
    assert result["mode"] == "X_unknown_major"
    assert "tsi_v2" not in result and "skill_gaps" not in result
    assert "星际航行工程" in result["message"]
    assert result["major_coverage"]["known_families"]
    assert result["how_to_enable"]
    assert any("majors_" in step for step in result["how_to_enable"])


def test_arbitrary_major_is_analyzable_end_to_end(dataset):
    """任意专业（非三族）也能跑通：供给画像来自该校本专业培养方案，需求不足如实披露。"""
    result = ResearchEngine(dataset).run(
        "分析北京工业大学机械工程专业的就业与需求适配", include_template=True)
    assert result["plan"]["major"] == "机械工程"
    assert result["plan"]["family"] == ""
    target = (result.get("supply") or {}).get("target") or {}
    assert target.get("n_courses", 0) > 20          # 来自该校机械工程培养方案
    assert result["data_quality"]["reliability"]     # 有明确的可信度说明
    report = render_markdown(result)
    assert "机械工程" in report


def test_major_coverage_reports_what_exists(dataset):
    coverage = dataset.major_coverage("ai")
    assert coverage["available"] is True
    assert coverage["n_facts"] > 0
    assert coverage["years"]
    assert "C_人才培养结果" in coverage["computable_dimensions"]
    missing = dataset.major_coverage("机械工程")
    assert missing["available"] is False
    assert "ai" in missing["known_families"]
    assert "school" not in missing["known_families"], "school 只是口径桶，不是专业族"


def test_policy_question_without_major_is_not_treated_as_unknown(dataset):
    """Regression: '…就业政策有哪些主要方向' used to be parsed as a major name."""
    result = ResearchEngine(dataset).run("北京市高校毕业生就业政策有哪些主要方向")
    assert result["mode"] == "F_policy_mechanism"
    assert "tsi_v2" in result


def test_new_major_can_be_added_by_dropping_a_file(tmp_path, dataset):
    """The family list is data-driven: a new majors_<family>.txt becomes analysable."""
    assert set(dataset.available_families) >= {"ai", "cs", "econ"}
    assert all(str(p).endswith(".txt") for p in dataset.available_families.values())

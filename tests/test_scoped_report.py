"""按层级交付：scope 推断、单层级报告、单层级 HTML、追问解析。"""

from __future__ import annotations

from agent import scope as scope_mod
from agent.html_report import markdown_to_html, render_result_html
from agent.scoped_report import render_scoped


def _result() -> dict:
    return {
        "run_id": "run:test",
        "query": "分析北京工业大学人工智能专业与大模型算法工程师的匹配度",
        "mode": "A_major_analysis",
        "plan": {"school": "北京工业大学", "major": "人工智能", "mode": "A_major_analysis",
                 "target_occupation": "大模型算法工程师",
                 "steps": [{"skill": "01_evidence_retrieval"}]},
        "tsi_v2": {"tsi_v2": 55.0, "n_total": 24},
        "primary_tsi": {
            "primary_tsi": 64.12, "band": "基本适配", "weighted_coverage": 1.0,
            "missing_indicators": ["M3"],
            "dimensions": {"F_供需适配": {"name": "供需适配", "score": 71.26, "weight": 0.4,
                                           "coverage": 1.0, "missing_indicators": []}},
            "metrics": [],
        },
        "semantic": {"objective_job_alignment": {
            "similarity": None, "status": "insufficient_evidence",
            "notes": "未找到可信的培养目标文本"}},
        "occupation": {"occupation": {"name": "大模型算法工程师"}, "n_jobs": 611,
                       "match_scope": "position", "demand_status": "ok",
                       "demand_top": [{"skill": "Python", "demand": 0.47}],
                       "requirements": {"education_distribution": {"本科": 400}}},
        "occupation_match": {"match_100": 55.06, "band": "部分匹配",
                             "n_skills_covered": 12, "n_skills_compared": 20,
                             "n_skills_missing": 8, "definitional_missing": ["RAG"]},
        "skill_fit": {"target": {"fit_100": 56.82}, "primary": {"fit_100": 56.82}},
        "supply": {"target": {"n_courses": 61, "n_mapped_courses": 40, "reliability": "medium"}},
        "skill_gaps": {"rows": [{"skill": "Python", "demand": 0.47, "supply": 0.0,
                                 "gap": 0.47, "status": "gap", "supply_basis": "absent_in_scope"}],
                       "skill_gap_index": 0.21},
        "coverage": {"n_schools": 13, "school_audit": {"school": "北京工业大学",
                                                       "ready_materials": ["培养方案课程"],
                                                       "missing_materials": ["培养目标"],
                                                       "materials": {"培养目标": {"state": "TEXT_EXTRACTED"}}}},
        "mechanism": {"paths": [{"skill": "Python", "policy_mentioned": True,
                                 "market_demand": 0.47, "course_supply": 0.0,
                                 "path_status": "缺口"}]},
        "conflict_resolution": {"records": [], "changed_skills": [], "recalculation_scope": []},
        "findings": [
            {"id": "F-tsi", "title": "总体供需适配", "statement": "Primary TSI=64.12",
             "model": "0.40F+0.20S+0.25O+0.15M", "action": "按缺口排序", "simulation": ""},
            {"id": "F-gap-1", "title": "关键缺口：Python", "statement": "缺口 0.47",
             "model": "Gap=Demand−Supply", "action": "补 Python 实践",
             "simulation": "预计 Skill Fit 56.82 → 70.00"},
            {"id": "F-micro-skill", "title": "个人技能缺口", "statement": "缺口：模型部署",
             "model": "Personal Supply", "action": "补项目", "simulation": ""},
        ],
        "micro_result": {
            "sparse_level": 4, "baseline": False, "fit_100": 73.1,
            "supply_provenance": "personal_evidence",
            "evidence_summary": {"knowledge": 2, "skill": 4, "capability": 0, "practice": 2},
            "gaps": {
                "knowledge": {"status": "ok", "n_gap": 0, "top_gaps": [],
                              "not_evidenced": ["Transformer"]},
                "skill": {"status": "ok", "n_gap": 1,
                          "top_gaps": [{"item": "模型部署", "gap": 0.37}], "not_evidenced": []},
                "capability": {"status": "ok", "n_gap": 0, "top_gaps": [], "not_evidenced": []},
                "practice": {"status": "insufficient_evidence", "reason": "缺需求向量"},
            },
            "priority_actions": [{"layer": "skill", "item": "模型部署",
                                  "action": "补齐「模型部署」：课程/项目/实习三选一"}],
            "declared": {"absences": [{"item": "正式实习"}]},
        },
        "evidence": [{"evidence_id": "ev:1", "evidence_level": "A", "title": "就业质量报告",
                      "locator": "data/source/年度报告/x.pdf"}],
    }


def test_scope_inference_and_explicit_override():
    assert scope_mod.resolve_scope("我学过 Python，帮我看看还差什么").scale == "micro"
    assert scope_mod.resolve_scope("分析北京工业大学人工智能专业的匹配度").scale in {"meso", "macro"}
    assert scope_mod.resolve_scope("北京市人工智能产业供需").scale == "macro"
    assert scope_mod.resolve_scope("随便", explicit="micro").scale == "micro"
    assert scope_mod.resolve_scope("随便", explicit="宏观").scale == "macro"


def test_scope_choice_and_followup_parsing():
    assert scope_mod.parse_choice("3") == "micro"
    assert scope_mod.parse_choice("三视角") == "all"
    assert scope_mod.parse_choice("") is None
    assert scope_mod.parse_yes("y") and scope_mod.parse_yes("需要")
    assert not scope_mod.parse_yes("n")
    assert "三视角" in scope_mod.followup_text()


def test_micro_report_does_not_include_other_scales():
    result = _result()
    micro = render_scoped(result, "micro")
    assert "个人证据画像" in micro
    assert "四层缺口" in micro
    assert "区域供给口径" not in micro
    assert "同类院校对比" not in micro
    macro = render_scoped(result, "macro")
    assert "区域供给口径" in macro
    assert "四层缺口" not in macro


def test_scoped_html_contains_only_selected_scale():
    result = _result()
    html = render_result_html(result, "micro")
    assert "个人证据画像" in html
    assert "区域供给口径" not in html
    assert "<table" in html and "<style>" in html
    macro_html = render_result_html(result, "macro")
    assert "区域供给口径" in macro_html
    assert "个人证据画像" not in macro_html


def test_markdown_to_html_handles_tables_lists_and_bold():
    html = markdown_to_html("## 标题\n\n| a | b |\n| --- | --- |\n| 1 | 2 |\n\n- **粗**项\n")
    assert "<h2>标题</h2>" in html
    assert "<th>a</th>" in html and "<td>1</td>" in html
    assert "<b>粗</b>" in html and "<li>" in html


def test_scoped_reports_enumerate_sources_and_benchmarks():
    """Markdown 报告也要有"哪些高校的信息源 / 多校基准"，不能只有一句话。"""
    result = _result()
    result["supply"].update({
        "target_by_school": [{"school": "北京工业大学", "n_courses": 61}],
        "peer_by_school": [{"school": "同类院校甲", "n_courses": 200},
                           {"school": "同类院校乙", "n_courses": 90}],
        "peer_n_schools": 2,
    })
    result["market"] = {"industries": [["互联网", 900]], "n_target_jobs": 1000,
                        "median_salary_target": 20000.0, "median_salary_baseline": 9000.0}
    result["occupation"]["requirements"] = {"education_distribution": {"本科": 400, "硕士": 100}}
    result["benchmark"] = {
        "triangle": {"rows": [{"dimension": "可核查课程数", "target": 61, "peer": 290,
                               "market": None}], "findings": ["目标校课程少于同类基准"]},
        "skill_benchmark": {"rows": [{"skill": "Python", "market_demand": 0.47,
                                      "target_supply": 0.0, "peer_supply": 1.0,
                                      "target_gap": 0.47, "target_vs_peer": -1.0,
                                      "reading": "目标高校供给低于市场需求"}]},
        "education_background": {"entities": [{"entity": "同类院校甲", "placement_rate": 0.95}]},
    }
    result["course_skill_matrix"] = {
        "course_ids": ["c1"], "skills": ["Python"], "matrix": [[1]],
        "credits_by_skill": {"Python": 6.0}, "unmapped_courses": ["大学英语"]}
    result["courses"] = [{"course_id": "c1", "name": "程序设计", "credits": 3.0,
                          "is_required": True}]
    result["dataset_summary"] = {"n_documents": 100, "n_courses": 500, "n_policies": 10,
                                 "years": [2020, 2024], "n_education_facts": 50,
                                 "n_pdf_facts": 20}

    macro = render_scoped(result, "macro")
    for marker in ("宏观信息源 · 覆盖院校台账", "同类院校甲", "同类院校乙",
                   "需求侧画像", "目标校 × 同类校 × 市场基准", "同类高校就业结果对比",
                   "数据资产总览"):
        assert marker in macro, f"宏观 Markdown 缺少：{marker}"
    meso = render_scoped(result, "meso")
    for marker in ("课程 × 技能矩阵", "逐技能：本校 vs 同类校 vs 市场", "目标高校供给低于市场需求"):
        assert marker in meso, f"中观 Markdown 缺少：{marker}"
    result["micro_result"]["demand_layers"] = {"skill": {"模型部署": 0.37, "Python": 0.47}}
    result["micro_result"]["personal_supply"] = {"skill": {"Python": 0.4}}
    micro = render_scoped(result, "micro")
    for marker in ("个人缺口 · 岗位需求 vs 个人供给", "模型部署", "证据不足"):
        assert marker in micro, f"微观 Markdown 缺少：{marker}"

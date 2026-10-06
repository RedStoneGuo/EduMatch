"""S1 修复回归：培养目标—岗位能力一致性不得把"证据不足"记成 0。"""

from __future__ import annotations

from analysis import objective_alignment as oa
from analysis import tsi as tsi_mod
from analysis.embeddings import TfidfCosineScorer

BOILERPLATE = ("的不同，在每个专业基本培养方案基础上，学校设计了多种“拓展型” 四、其它类型的培养方案 "
               "学有余力的同学可根据自己的时间和精力，按照相关规定相应修读更高级别或更多学分的课 "
               "（3）课程修读要求中涉及的课程级别、修读学分等要求为正常毕业所需达到的最低要求")

OBJECTIVE = ("本专业培养德智体美劳全面发展，掌握人工智能基础理论、机器学习与深度学习原理，"
             "具备 Python 编程、数据分析与模型训练能力，能够在人工智能相关领域从事算法研发、"
             "模型应用与工程实践的高素质应用型人才。")

DEMAND = {"Python": 0.47, "机器学习": 0.34, "深度学习": 0.50,
          "模型部署": 0.37, "RAG": 0.10, "大模型": 0.60}


def test_boilerplate_fragment_is_rejected():
    valid, reason = oa.is_valid_objective(BOILERPLATE)
    assert valid is False
    assert reason
    assert oa.is_valid_objective(OBJECTIVE)[0] is True


def test_extract_prefers_real_objective_over_boilerplate():
    text = "前言 " + BOILERPLATE + " …… " + "一、培养目标 " + OBJECTIVE
    candidates = oa.extract_objective_candidates(text)
    assert candidates
    assert candidates[0].valid is True
    assert "掌握人工智能基础理论" in candidates[0].text


def test_below_floor_cosine_is_none_not_zero():
    scorer = TfidfCosineScorer()
    result = scorer.score(OBJECTIVE, "量子化学 有机合成 高分子材料 催化反应")
    assert result.status in {"weak_similarity", "insufficient_evidence"}
    assert result.similarity is None  # 关键：不能是 0.0


def test_objective_job_alignment_uses_demand_weighted_coverage():
    result = oa.objective_job_alignment([OBJECTIVE], DEMAND)
    assert result["status"] == "ok"
    assert result["similarity"] is not None and result["similarity"] > 0
    assert "objective" in result["basis"]
    assert "Python" in result["covered_skills"]
    assert "模型部署" in result["missing_skills"]
    assert result["real_zero"] is False
    assert result["method"] == "demand_weighted_objective_coverage"


def test_school_level_objective_is_marked_as_disclosed_proxy():
    school_wide = ("学校着力把本科生培养成为基础宽厚、理论扎实、勇于实践、"
                   "具备高度社会责任感和创新精神的高素质应用型创新人才。")
    result = oa.objective_job_alignment([school_wide], DEMAND)
    if result["similarity"] is not None:
        assert result["proxy_school_level"] is True
        assert result["basis"].startswith("school_level_objective")
        assert "校级" in result["scope_note"]


def test_major_scoped_objective_takes_priority_over_school_level():
    major_candidate = oa.ObjectiveCandidate(
        text=OBJECTIVE, anchor="bjut:人工智能", valid=True, scope="major",
        marker_hits=6, boilerplate_hits=0)
    school_candidate = oa.ObjectiveCandidate(
        text=("学校着力把本科生培养成为基础宽厚、理论扎实、德智体美劳全面发展，"
              "掌握扎实专业基础与创新能力的应用型人才。"),
        anchor="校级", valid=True, scope="school", marker_hits=6, boilerplate_hits=0)
    result = oa.objective_job_alignment([school_candidate, major_candidate], DEMAND)
    assert result["proxy_school_level"] is False
    assert result["basis"].startswith("major_objective")
    assert "Python" in result["covered_skills"]


def test_dict_candidates_preserve_scope_tag():
    """回归：台账里以 dict 形式传入时必须保留 scope，否则专业级目标会被降级成校级代理。"""
    major_dict = {"text": OBJECTIVE, "anchor": "a:人工智能", "valid": True,
                  "scope": "major", "marker_hits": 6, "boilerplate_hits": 0}
    school_dict = {"text": ("学校着力把本科生培养成为基础宽厚、理论扎实、"
                            "德智体美劳全面发展的应用型人才。"),
                   "anchor": "校级", "valid": True, "scope": "school",
                   "marker_hits": 6, "boilerplate_hits": 0}
    result = oa.objective_job_alignment([school_dict, major_dict], DEMAND)
    assert result["proxy_school_level"] is False
    assert result["basis"].startswith("major_objective")


def test_missing_objective_is_insufficient_evidence_not_zero():
    result = oa.objective_job_alignment([BOILERPLATE], DEMAND)
    assert result["similarity"] is None
    assert result["status"] == "insufficient_evidence"
    assert result["basis"] == "none"


def test_valid_objective_with_no_overlap_is_a_real_zero():
    unrelated = ("本专业培养德智体美劳全面发展，掌握量子化学、有机合成与高分子材料的基础理论，"
                 "具备化学实验设计能力，能够从事精细化工生产与研发工作。")
    result = oa.objective_job_alignment([unrelated], DEMAND)
    assert result["similarity"] == 0.0
    assert result["real_zero"] is True
    assert result["status"] == "ok"


def test_tsi_a1_treats_weak_alignment_as_missing():
    semantic = {"objective_job_alignment": {
        "similarity": 0.0, "status": "weak_similarity", "notes": "低于下限，记证据不足"}}
    metrics = tsi_mod.score_indicators({"semantic": semantic})
    a1 = next(m for m in metrics if m.metric_id == "A1")
    assert a1.value is None
    assert a1.status == "insufficient_evidence"


def test_tsi_a1_uses_valid_alignment_value():
    semantic = {"objective_job_alignment": {
        "similarity": 0.62, "status": "ok", "evidence_level": "D",
        "basis": "objective:培养目标", "covered_skills": ["Python"], "missing_skills": []}}
    metrics = tsi_mod.score_indicators({"semantic": semantic})
    a1 = next(m for m in metrics if m.metric_id == "A1")
    assert a1.value == 62.0


def test_tsi_a1_excludes_school_level_proxy_from_primary_tsi():
    semantic = {"objective_job_alignment": {
        "similarity": 0.15, "status": "ok", "evidence_level": "D", "confidence": 0.35,
        "proxy_school_level": True, "basis": "school_level_objective:2015报告",
        "covered_skills": ["基础"], "missing_skills": []}}
    metrics = tsi_mod.score_indicators({"semantic": semantic})
    a1 = next(m for m in metrics if m.metric_id == "A1")
    # 校级代理不计入 Primary TSI（value=None），但代理值仍可在 detail 中查到
    assert a1.value is None
    assert a1.status == "insufficient_evidence"
    assert a1.detail.get("proxy_value") == 15.0
    assert a1.detail.get("proxy_school_level") is True

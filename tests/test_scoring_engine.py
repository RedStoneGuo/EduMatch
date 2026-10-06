"""TSI V1 scoring: deterministic, evidence-carrying, vector-based semantics."""

from __future__ import annotations

from analysis import tsi_v1
from analysis.embeddings import TfidfCosineScorer, get_scorer, provider_status
from edumatch.dataset import major_family
from edumatch.engine import ResearchEngine, build_plan


def test_weights_match_the_source_document():
    """绝对权重必须等于 TSI指标搭建.docx 中各级权重的乘积，且总和为 1。"""
    total = sum(tsi_v1.WEIGHTS.values())
    assert abs(total - 1.0) < 1e-9
    assert abs(tsi_v1.WEIGHTS["A11"] - 0.25 * 0.32 * 0.25) < 1e-12
    assert abs(tsi_v1.WEIGHTS["C21"] - 0.45 * 0.34 * 0.30) < 1e-12
    assert len(tsi_v1.WEIGHTS) == 27
    assert set(tsi_v1.WEIGHTS) == set(tsi_v1.NAMES)


def test_continuous_rule_matches_the_document_formula():
    assert tsi_v1.score_continuous(1.0, 1.0) == 60.0          # 达到基准 → 60
    assert tsi_v1.score_continuous(1.5, 1.0) == 80.0          # 高 50% → 80
    assert tsi_v1.score_continuous(2.0, 1.0) == 100.0         # 高 100% → 100
    # 逆行指标：raw=2×基准时 ratio=0.5 → 60 + (0.5-1)×40 = 40
    assert tsi_v1.score_continuous(2.0, 1.0, higher_is_better=False) == 40.0
    assert tsi_v1.score_continuous(None, 1.0) is None


def test_missing_is_null_not_zero():
    metrics = tsi_v1.score_indicators_v1({"teaching": {}, "employment": {}, "matching": {}},
                                         {}, {})
    assert len(metrics) == 27
    assert all(m.value is None for m in metrics)
    assert all(m.evidence_level == "E" for m in metrics)
    result = tsi_v1.aggregate(metrics)
    assert result["tsi"] is None and result["n_available"] == 0


def test_no_llm_in_the_scoring_path():
    """打分模块不得引入任何 LLM 客户端或网络调用。"""
    text = open(tsi_v1.__file__, encoding="utf-8").read().lower()
    for forbidden in ("import openai", "import anthropic", "chat/completions",
                      "import httpx", "import requests", "api_key"):
        assert forbidden not in text, f"{forbidden} 出现在打分模块中"


def test_vector_scorer_reports_provider_and_calibration():
    scorer = TfidfCosineScorer(low=0.02, high=0.30)
    same = scorer.score("机器学习与深度学习课程", "机器学习与深度学习课程").to_dict()
    other = scorer.score("机器学习与深度学习课程", "古典音乐演奏与音乐史").to_dict()
    # 契约（2026-10-05 修正）：低于校准下限 = 证据不足（None），不得压成 0 分。
    # 旧实现把无关文本压成 0.0，导致 S1 恒为 0，这里显式锁定新契约。
    assert same["similarity"] is not None and same["similarity"] > 0
    assert other["similarity"] is None
    assert other["status"] == "weak_similarity"
    assert other["cosine"] is not None  # 原始余弦仍保留，供审计
    assert same["provider"] == "tfidf_char_cosine_v1"
    assert same["calibration"] == {"low": 0.02, "high": 0.30}
    assert same["cosine"] is not None
    assert same["top_terms"]
    assert "tfidf_char_cosine_v1" in provider_status()
    assert get_scorer("tfidf").provider == "tfidf_char_cosine_v1"


def test_vector_scorer_flags_short_text_as_insufficient():
    result = TfidfCosineScorer().score("人工智能", "")
    assert result.similarity is None and result.status == "insufficient_evidence"


def test_semantic_indicator_carries_its_basis():
    context = {
        "semantic": {
            "curriculum_market_alignment": {
                "similarity": 0.5, "cosine": 0.2, "provider": "tfidf_char_cosine_v1",
                "status": "ok", "calibration": {"low": 0.05, "high": 0.45},
                "top_terms": [("机器学习", 0.3)],
            }
        }
    }
    metrics = tsi_v1.score_indicators_v1(context, {}, {})
    b21 = next(m for m in metrics if m.metric_id == "B21")
    assert b21.value == 50.0
    basis = b21.detail["basis"]
    assert basis["type"] == "semantic_vector"
    assert basis["provider"] == "tfidf_char_cosine_v1"
    assert basis["cosine"] == 0.2


def test_indicator_basis_exposes_raw_benchmark_and_formula():
    context = {"employment": {"placement_rate": 0.9, "signing_rate": 0.85}}
    metrics = tsi_v1.score_indicators_v1(context, {"placement_rate": 0.9}, {})
    c21 = next(m for m in metrics if m.metric_id == "C21")
    basis = c21.detail["basis"]
    assert basis["raw"] == 0.9 and basis["benchmark"] == 0.9
    assert basis["score"] == 60.0
    assert "clamp" in basis["formula"]


def test_intelligent_manufacturing_is_not_ai_family():
    """误归类会让"某校人工智能"取到智能制造工程的数据。"""
    assert major_family("智能制造工程") != "ai"
    assert major_family("智能建造") != "ai"
    assert major_family("人工智能") == "ai"
    assert major_family("智能科学与技术") == "ai"


def test_named_school_never_falls_back_to_another_school(dataset):
    plan = build_plan("分析北京工业大学人工智能专业", dataset)
    assert plan.school == "北京工业大学"
    result = ResearchEngine(dataset).run("分析北京工业大学人工智能专业", include_template=True)
    meta = result["employment"].get("placement_rate_meta") or {}
    if meta.get("value") is not None:
        assert meta.get("school") == "北京工业大学"


def test_v1_and_v2_both_reported(dataset):
    result = ResearchEngine(dataset).run("分析人工智能专业与2025年北京AI招聘市场的人才供需适配",
                                         include_template=True)
    assert "tsi_v1" in result and "tsi_v2" in result
    assert result["tsi_v1"]["formula"] == "TSI = 0.25A + 0.30B + 0.45C"
    assert result["tsi_v1"]["n_indicators"] == 27 and result["tsi_v2"]["n_total"] == 24

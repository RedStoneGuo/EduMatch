"""通用检索与交付能力：岗位名泛化、词表清洗、宏观区域口径、分层新增文件。"""

from __future__ import annotations

import json
from pathlib import Path

from edumatch import occupation as occ
from edumatch.vocab import clean_vocabulary, is_generic
from reporting.render import render_result


def test_title_variants_generalize_suffixes():
    variants = occ.title_variants("高级数据分析师")
    assert variants[0] == "高级数据分析师"
    assert "数据分析" in variants          # 去掉"高级/分析师"后仍能检索
    assert occ.title_variants("算法分析师")[0] == "算法分析师"


def test_synonym_maps_algorithm_analyst_to_analysis_family():
    """用户写"算法分析师"时，不能因为语料里没有这四个字就判检索不到。"""
    fam = occ.resolve_occupation("算法分析师")
    assert fam is not None and fam.id == "data_analysis"
    assert occ.resolve_occupation("算法分析").id == "data_analysis"
    # 纯"算法工程师"仍归算法族，不能被同义词表误伤
    assert occ.resolve_occupation("算法工程师").id == "ml_algorithm"


def test_slice_jobs_records_expansion_but_keeps_scope_contract():
    jobs = [{"position": "数据分析师", "job_description": "SQL"},
            {"position": "高级数据分析", "job_description": "Python"}]
    info = occ.slice_jobs(jobs, "高级数据分析师", min_jobs=1)
    assert info["status"] == "ok"
    assert info["match_scope"] in {"position", "position+description"}   # 旧契约不变
    assert info["generalized"] in {True, False}
    assert info["query_variants"][0] == "高级数据分析师"
    assert info["matched_terms"]


def test_vocab_clean_drops_generic_and_merges_containment():
    assert is_generic("问题") and is_generic("场景") and not is_generic("Python")
    kept, audit = clean_vocabulary(["Python", "问题", "场景", "算法", "算法分析", "SQL", "sql"])
    assert "问题" not in kept and "场景" not in kept
    assert "算法分析" in kept and "算法" not in kept      # 保留更具体的
    assert sum(1 for k in kept if k.lower() == "sql") == 1  # 大小写去重
    assert audit["dropped_generic"] == 2 and audit["n_out"] == len(kept)


def _result_with_peer() -> dict:
    return {
        "run_id": "run:test", "query": "q",
        "plan": {"school": "某大学", "major": "某专业"},
        "primary_tsi": {"primary_tsi": 50.0, "weighted_coverage": 0.8,
                        "missing_indicators": [], "dimensions": {},
                        "metrics": []},
        "supply": {"target": {"n_courses": 20, "top_skills": [{"skill": "Python", "supply": 0.4}]},
                   "peer": {"n_courses": 220, "reliability": "high",
                            "top_skills": [{"skill": "Python", "supply": 0.9},
                                           {"skill": "问题", "supply": 1.0}]},
                   "used_for_legacy_fit": "target"},
        "demand_rows": [{"skill": "Python", "demand": 0.5}, {"skill": "场景", "demand": 0.7}],
        "skill_gaps": {"rows": []}, "occupation": {"occupation": {"name": "数据分析师"}, "n_jobs": 100},
        "evidence": [],
    }


def test_macro_uses_regional_peer_pool_not_target_school():
    html = render_result(_result_with_peer(), "macro")
    assert "区域同类专业课程池" in html and "220" in html      # 用 peer 的课程数
    assert "不是目标校一所学校" in html
    assert ">问题<" not in html and ">场景<" not in html        # 通用词被清洗掉
    meso = render_result(_result_with_peer(), "meso")
    assert "区域同类专业课程池" not in meso                      # 中观仍讲本校


def test_macro_lists_regional_pool_schools_and_ledger_has_context_columns():
    result = _result_with_peer()
    result["supply"]["peer_by_school"] = [{"school": "清华大学", "n_courses": 207},
                                          {"school": "北京理工大学", "n_courses": 6}]
    result["supply"]["peer_n_schools"] = 2
    result["retrieval_ledger"] = {"materials": {"培养目标": {"attempts": [
        {"kind": "pdf_text", "state": "hit", "reason": "",
         "school": "清华大学", "major": "信息管理与信息系统", "file": "2024_信息管理与信息系统.txt"}
    ]}}, "summary": {"n_attempts": 1, "n_hits": 1, "needs_online": {}}}
    html = render_result(result, "macro")
    assert "清华大学" in html and "北京理工大学" in html        # 区域池按校列出
    assert "<th>院校</th>" in html and "<th>专业</th>" in html and "<th>文件</th>" in html
    assert "2024_信息管理与信息系统.txt" in html


def test_out_dir_writes_per_scale_files_additively(tmp_path: Path):
    from reporting import render as render_mod

    result_file = tmp_path / "result.json"
    result_file.write_text(json.dumps(_result_with_peer(), ensure_ascii=False), encoding="utf-8")
    out_dir = tmp_path / "out"
    assert render_mod.main(["--result", str(result_file), "--scope", "micro",
                            "--out-dir", str(out_dir), "--prefix", "报告"]) == 0
    assert (out_dir / "报告_micro.html").exists()
    # 再补一个层级：只新增，不覆盖已有
    before = (out_dir / "报告_micro.html").read_text(encoding="utf-8")
    assert render_mod.main(["--result", str(result_file), "--scope", "meso",
                            "--out-dir", str(out_dir), "--prefix", "报告"]) == 0
    assert (out_dir / "报告_meso.html").exists()
    assert (out_dir / "报告_micro.html").read_text(encoding="utf-8") == before

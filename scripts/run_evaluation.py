"""Run the benchmark, the 12 standard cases and the legacy baseline comparison.

    python scripts/run_evaluation.py

Writes evaluation/reports/evaluation_report.json and .md
"""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent.core import TalentSupplyDemandAgent  # noqa: E402
from edumatch.config import load_settings  # noqa: E402
from edumatch.dataset import Dataset  # noqa: E402
from edumatch.engine import ResearchEngine  # noqa: E402
from edumatch.ontology import load_ontology  # noqa: E402

CAUSAL_PATTERNS = ["导致", "证明了", "必然导致", "决定了就业"]


def m1_extraction(dataset: Dataset, golden: list[dict]) -> dict:
    hits, misses = 0, []
    by_scope = {"major": {"hit": 0, "total": 0}, "school": {"hit": 0, "total": 0}}
    for item in golden:
        found = [
            f for f in dataset.facts
            if f.school == item["school"] and f.year == item["year"]
            and f.fact_type == item["fact_type"]
            and (item["major"] is None or f.major == item["major"])
        ]
        ok = any(abs((f.value or 0) - item["expected"]) < 1e-6 for f in found)
        scope = "major" if item["major"] else "school"
        by_scope[scope]["total"] += 1
        by_scope[scope]["hit"] += int(ok)
        hits += int(ok)
        if not ok:
            misses.append(item)
    return {
        "metric": "M1_extraction_accuracy",
        "value": round(hits / len(golden), 4),
        "n": len(golden),
        "by_scope": {
            k: {**v, "value": round(v["hit"] / v["total"], 4) if v["total"] else None}
            for k, v in by_scope.items()
        },
        "source_policy": "数据源为报告 PDF 的自动抽取；三份策展文档仅作金标准校验",
        "misses": misses,
    }


def m2_normalisation(golden: list[dict]) -> dict:
    onto = load_ontology()
    hits, misses = 0, []
    for item in golden:
        names = {onto.get(m.skill_id).name for m in onto.extract(item["text"])}
        ok = item["expected"] in names
        hits += int(ok)
        if not ok:
            misses.append({**item, "got": sorted(names)})
    return {"metric": "M2_normalisation_accuracy", "value": round(hits / len(golden), 4),
            "n": len(golden), "misses": misses}


def _citations_complete(evidence: list[dict]) -> tuple[int, int]:
    ok = sum(1 for e in evidence if e.get("locator") and e.get("evidence_level") in {"A", "B", "C", "D", "E"})
    return ok, len(evidence)


def run_cases(engine: ResearchEngine, cases: list[dict], agent: TalentSupplyDemandAgent) -> list[dict]:
    results = []
    for case in cases:
        started = time.time()
        data = engine.run(case["query"], include_template=case["id"] in {"TC02", "TC07", "TC08"},
                          simulation=case["id"] in {"TC07", "TC08"})
        report = agent_ish_report(agent, data)
        checks = evaluate_checks(case, data, report)
        results.append({
            "id": case["id"], "query": case["query"], "mode_expected": case["mode"],
            "mode_actual": data["mode"], "elapsed_s": round(time.time() - started, 2),
            "tsi_v2": data["tsi_v2"]["tsi_v2"], "matching": data["matching"]["matching_score"],
            "gap_index": data["skill_gaps"]["skill_gap_index"],
            "n_tools": len(data["tool_calls"]),
            "n_evidence": len(data["evidence"]),
            "missing_indicators": data["tsi_v2"]["missing_indicators"],
            "checks": checks,
            "passed": all(c["ok"] for c in checks.values()),
        })
    return results


def agent_ish_report(agent: TalentSupplyDemandAgent, data: dict) -> str:
    from agent.report import render_markdown

    return render_markdown(data)


def evaluate_checks(case: dict, data: dict, report: str) -> dict:
    checks: dict[str, dict] = {}
    missing = case.get("checks", [])

    def add(name: str, ok: bool, detail: str = "") -> None:
        checks[name] = {"ok": bool(ok), "detail": detail}

    add("tool_calls", all(t["status"] == "ok" for t in data["tool_calls"]),
        f"{len(data['tool_calls'])} calls")
    add("evidence", len(data["evidence"]) > 0, f"{len(data['evidence'])} items")
    if "missing_null" in missing:
        metric_values = {m["metric_id"]: m for m in data["metrics"]}
        ok = all(metric_values[m]["value"] is None for m in data["tsi_v2"]["missing_indicators"])
        add("missing_null", ok, f"{len(data['tsi_v2']['missing_indicators'])} null indicators")
    if "supply_demand_separated" in missing:
        ok = "招聘数据不参与该维度" in json.dumps(data["employment"], ensure_ascii=False) or \
             data["employment"].get("source_rule", "").startswith("就业结果")
        add("supply_demand_separated", ok)
    if "course_fallback_disclosed" in missing:
        ok = data["course_scope"].get("scope") in {"school_specific", "cross_school_pool"}
        add("course_fallback_disclosed", ok, str(data["course_scope"].get("reason", ""))[:80])
    if "benchmark_sample_note" in missing:
        add("benchmark_sample_note", bool(data["benchmark"].get("sample_note")))
    if "no_rank_without_sample" in missing:
        add("no_rank_without_sample", not data["benchmark"]["rankable"] or data["benchmark"]["min_n"] >= 1)
    if "trend_insufficient_when_single_point" in missing:
        ok = all(t["status"] in {"ok", "insufficient_evidence"} for t in data["trends"].values())
        add("trend_insufficient_when_single_point", ok)
    if "gap_rows" in missing:
        add("gap_rows", bool(data["skill_gaps"]["rows"]))
    if "gap_insufficient_not_zero" in missing:
        nulls = [r for r in data["skill_gaps"]["rows"] if r["gap"] is None]
        add("gap_insufficient_not_zero", all(r["status"] == "insufficient_evidence" for r in nulls),
            f"{len(nulls)} not comparable")
    if "no_causal_language" in missing:
        hits = [p for p in CAUSAL_PATTERNS if p in report]
        add("no_causal_language", not hits, ",".join(hits))
    if "policy_evidence_level_A" in missing:
        levels = {e["evidence_level"] for e in data["evidence"] if e["source_type"] == "policy"}
        add("policy_evidence_level_A", "A" in levels or not levels, str(sorted(levels)))
    if "simulation_disclaimer" in missing:
        sim = data.get("simulation") or {}
        add("simulation_disclaimer", "预测" in str(sim.get("disclaimer", ""))
            and "假设" in str(sim.get("disclaimer", "")) + "".join(sim.get("assumptions") or []))
    if "simulation_delta_present" in missing:
        sim = data.get("simulation") or {}
        c = sim.get("combined_scenario") or {}
        add("simulation_delta_present", c.get("matching_delta") is not None)
    if "report_sections_18" in missing:
        add("report_sections_18", all(f"## {i}." in report for i in range(1, 19)))
    if "faculty_facts" in missing:
        add("faculty_facts", data["teaching"].get("student_faculty_ratio") is not None)
    if "graceful_unknown_major" in missing:
        add("graceful_unknown_major", data["tsi_v2"]["tsi_v2"] is not None or
            data["tsi_v2"]["weighted_coverage"] == 0)
    if "policy_industry_direction" in missing:
        add("policy_industry_direction", bool(data["policy"]["industry_direction"]))
    return checks


def main() -> int:
    settings = load_settings()
    benchmark = json.loads((ROOT / "evaluation" / "benchmark.json").read_text(encoding="utf-8"))
    cases = json.loads((ROOT / "evaluation" / "test_cases" / "cases.json").read_text(encoding="utf-8"))
    dataset = Dataset.build(settings)
    engine = ResearchEngine(dataset, settings)
    agent = TalentSupplyDemandAgent(dataset, settings)

    metrics: list[dict] = [m1_extraction(dataset, benchmark["golden_extraction"]),
                           m2_normalisation(benchmark["golden_normalisation"])]
    case_results = run_cases(engine, cases["cases"], agent)

    # M3 evidence recall
    with_evidence = sum(1 for c in case_results if c["n_evidence"] > 0)
    metrics.append({"metric": "M3_evidence_recall", "value": round(with_evidence / len(case_results), 4),
                    "n": len(case_results)})

    # M4 numerical consistency: recompute matching from published formula
    demo = engine.run(cases["cases"][0]["query"], include_template=True)
    supply = demo["course_skill_matrix"]["supply"]
    demand = {r["skill"]: r["demand"] for r in demo["matching"]["per_skill"] if r["demand"]}
    manual_num = sum(demand[s] * min(supply.get(s, 0.0), 1.0) for s in demand)
    manual_den = sum(demand.values())
    manual = manual_num / manual_den if manual_den else None
    # 复算使用报告公布的 4 位小数中间值，因此允许 1e-3 级别误差
    metrics.append({"metric": "M4_numeric_consistency",
                    "value": 1.0 if manual and abs(manual - demo["matching"]["matching_score"]) < 1e-3 else 0.0,
                    "engine": demo["matching"]["matching_score"], "manual": round(manual, 6) if manual else None})

    # M5/M6 repeatability
    a = engine.run("重复性检查：人工智能技能缺口", include_template=True)
    b = engine.run("重复性检查：人工智能技能缺口", include_template=True)
    metrics.append({"metric": "M5_tsi_repeatability",
                    "value": 1.0 if a["tsi_v2"]["tsi_v2"] == b["tsi_v2"]["tsi_v2"] else 0.0,
                    "tsi": a["tsi_v2"]["tsi_v2"]})
    metrics.append({"metric": "M6_gap_repeatability",
                    "value": 1.0 if a["skill_gaps"]["skill_gap_index"] == b["skill_gaps"]["skill_gap_index"] else 0.0,
                    "gap_index": a["skill_gaps"]["skill_gap_index"]})

    # M7 citation completeness
    all_evidence = [e for c in case_results for e in []]
    total_ok = total = 0
    for case in cases["cases"]:
        data = engine.run(case["query"], include_template=False)
        ok, n = _citations_complete(data["evidence"])
        total_ok += ok
        total += n
        all_evidence.extend(data["evidence"])
    metrics.append({"metric": "M7_citation_completeness",
                    "value": round(total_ok / total, 4) if total else 1.0, "n_evidence": total})

    # M8 hallucination guard on rendered reports
    reports = [agent_ish_report(agent, engine.run(c["query"], include_template=False, simulation=False))
               for c in cases["cases"]]
    violations = sum(1 for r in reports if any(p in r for p in CAUSAL_PATTERNS))
    metrics.append({"metric": "M8_hallucination_rate", "value": round(violations / len(reports), 4),
                    "n_reports": len(reports), "patterns": CAUSAL_PATTERNS})

    # M9 missing handling
    bad = 0
    for case in cases["cases"]:
        data = engine.run(case["query"], include_template=False)
        values = {m["metric_id"]: m for m in data["metrics"]}
        if any(values[m]["value"] is not None for m in data["tsi_v2"]["missing_indicators"]):
            bad += 1
    metrics.append({"metric": "M9_missing_handling", "value": round(1 - bad / len(cases["cases"]), 4)})

    # M10 tool correctness
    calls = [t for c in case_results for t in []]
    all_calls = []
    for case in cases["cases"]:
        data = engine.run(case["query"], include_template=False)
        all_calls.extend(data["tool_calls"])
    ok_calls = sum(1 for t in all_calls if t["status"] == "ok")
    metrics.append({"metric": "M10_tool_call_success", "value": round(ok_calls / len(all_calls), 4),
                    "n_calls": len(all_calls)})

    # M11 job-market data integrity (three-tier counts + real market statistics)
    if dataset.jobs:
        stats = dataset.job_statistics()
        counts = stats["counts"]
        funnel_ok = counts["raw_count"] >= counts["deduplicated_count"] >= counts["effective_count"]
        stats_ok = stats["salary_premium"] is not None and stats["n_target_jobs"] > 0
        metrics.append({
            "metric": "M11_job_market_integrity",
            "value": 1.0 if (funnel_ok and stats_ok) else 0.0,
            "counts": counts,
            "n_target_jobs": stats["n_target_jobs"],
            "salary_premium": stats["salary_premium"],
            "master_plus_share": stats["master_plus_share"],
            "evidence_level": stats["evidence_level"],
        })
    else:
        metrics.append({"metric": "M11_job_market_integrity", "value": None,
                        "note": "未导入岗位数据"})

    # M12 literature retrieval availability
    lit_path = settings.processed_dir / "literature.json"
    if lit_path.exists():
        lit = json.loads(lit_path.read_text(encoding="utf-8"))
        works = lit.get("works") or []
        with_doi = sum(1 for w in works if w.get("doi"))
        metrics.append({
            "metric": "M12_literature_retrieval",
            "value": round(with_doi / len(works), 4) if works else 0.0,
            "n_works": len(works),
            "source": lit.get("source"),
            "robots": lit.get("robots"),
        })
    else:
        metrics.append({"metric": "M12_literature_retrieval", "value": None,
                        "note": "未运行 scripts/fetch_literature.py"})

    # legacy baseline comparison
    legacy = dataset.legacy
    baseline = {}
    if legacy and legacy.replay:
        baseline = {
            "tsi_v1_replayed": legacy.replay["tsi_v1"],
            "tsi_v1_stated_by_llm": legacy.stated_final_tsi,
            "gap_between_llm_and_formula": None if legacy.stated_final_tsi is None
            else round(legacy.stated_final_tsi - legacy.replay["tsi_v1"], 2),
            "n_indicators": legacy.replay["n_indicators"],
            "n_zero_scored": legacy.replay["n_zero_scores"],
            "zero_ratio": round(legacy.replay["n_zero_scores"] / legacy.replay["n_indicators"], 4),
            "zero_indicators": legacy.replay["zero_indicators"],
            "v2_equivalent": demo["tsi_v2"]["tsi_v2"],
            "v2_missing_indicators": demo["tsi_v2"]["missing_indicators"],
            "v2_coverage": demo["tsi_v2"]["weighted_coverage"],
        }

    thresholds = benchmark["thresholds"]
    by_name = {m["metric"]: m["value"] for m in metrics}
    passed = {
        "M1": by_name["M1_extraction_accuracy"] >= thresholds["extraction_accuracy"],
        "M2": by_name["M2_normalisation_accuracy"] >= thresholds["normalisation_accuracy"],
        "M4": by_name["M4_numeric_consistency"] == 1.0,
        "M7": by_name["M7_citation_completeness"] >= thresholds["citation_completeness"],
        "M8": by_name["M8_hallucination_rate"] <= thresholds["hallucination_rate_max"],
        "M9": by_name["M9_missing_handling"] >= thresholds["missing_handling_accuracy"],
        "M10": by_name["M10_tool_call_success"] >= thresholds["tool_call_success_rate"],
        "M11": by_name.get("M11_job_market_integrity") == 1.0,
        "M12": (by_name.get("M12_literature_retrieval") or 0) > 0.9,
    }
    report = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "dataset_summary": dataset.summary(),
        "metrics": metrics,
        "thresholds_met": passed,
        "case_results": case_results,
        "cases_passed": sum(1 for c in case_results if c["passed"]),
        "cases_total": len(case_results),
        "legacy_baseline": baseline,
    }
    out_dir = ROOT / "evaluation" / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "evaluation_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "evaluation_report.md").write_text(render_md(report), encoding="utf-8")
    print(json.dumps({
        "metrics": {m["metric"]: m["value"] for m in metrics},
        "cases_passed": f"{report['cases_passed']}/{report['cases_total']}",
        "thresholds_met": passed,
        "legacy": baseline,
    }, ensure_ascii=False, indent=2))
    return 0


def render_md(report: dict) -> str:
    lines = ["# EduMatch 评测报告", "",
             f"生成时间：{report['generated_at']}", "",
             "## 指标结果", "",
             "| 指标 | 数值 | 说明 |", "| --- | --- | --- |"]
    for m in report["metrics"]:
        extra = {k: v for k, v in m.items() if k not in {"metric", "value"}}
        lines.append(f"| {m['metric']} | {m['value']} | {json.dumps(extra, ensure_ascii=False)[:120]} |")
    lines += ["", "## 标准测试案例", "",
              f"通过 {report['cases_passed']}/{report['cases_total']}", "",
              "| 案例 | 期望模式 | 实际模式 | 通过 | TSI | 匹配度 | Gap | 工具数 | 缺失指标 |",
              "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for c in report["case_results"]:
        lines.append(
            f"| {c['id']} | {c['mode_expected']} | {c['mode_actual']} | {'✅' if c['passed'] else '❌'} | "
            f"{c['tsi_v2']} | {c['matching']} | {c['gap_index']} | {c['n_tools']} | "
            f"{len(c['missing_indicators'])} |")
    if report["legacy_baseline"]:
        b = report["legacy_baseline"]
        lines += ["", "## 旧版 baseline 对比", "",
                  f"- 旧版公式复算 TSI：{b['tsi_v1_replayed']}",
                  f"- 旧版报告（LLM）写出的 TSI：{b['tsi_v1_stated_by_llm']}",
                  f"- 二者差：{b['gap_between_llm_and_formula']}",
                  f"- 旧版 27 指标中记 0 分的数量：{b['n_zero_scored']}（{b['zero_ratio'] * 100:.1f}%）",
                  f"- 记 0 的指标：{', '.join(b['zero_indicators'])}",
                  f"- TSI 2.0：{b['v2_equivalent']}，缺失指标 {len(b['v2_missing_indicators'])} 个，覆盖率 {b['v2_coverage'] * 100:.1f}%"]
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())

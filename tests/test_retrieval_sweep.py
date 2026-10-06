"""全面检索台账：来源穷举、状态机、缺失原因与联网补采计划。"""

from __future__ import annotations

from pathlib import Path

from edumatch.retrieval_sweep import SOURCE_KINDS, render_ledger_markdown, sweep_sources

CORE = Path(__file__).resolve().parents[1]


def test_sweep_covers_all_source_kinds_and_records_reasons():
    ledger = sweep_sources(CORE, school="北京工业大学", major="人工智能",
                           materials=("培养目标",), extract_pdf=True,
                           max_files_per_kind=3)
    block = ledger["materials"]["培养目标"]
    kinds = {a["kind"] for a in block["attempts"]}
    # 本地正文缓存 / 规范源 / 归档 / 采集产物 四类来源都要出现（联网以 need_online 记录）
    assert {"pdf_text", "source", "archive", "harvest"} <= kinds
    assert ledger["summary"]["n_attempts"] >= 4
    # 每条未命中的检索都要写清原因，不能只留空
    for attempt in block["attempts"]:
        if attempt["state"] in {"miss", "error", "need_online"}:
            assert attempt["reason"]
    assert block["online_plan"]["entry_a"] and block["online_plan"]["entry_b"]


def test_sweep_reports_online_plan_with_verified_domain_only():
    ledger = sweep_sources(CORE, school="北京工业大学", major="人工智能",
                           materials=("培养目标",), max_files_per_kind=2)
    plan = ledger["materials"]["培养目标"]["online_plan"]
    # 域名要么来自核实台账，要么明确为 None；不允许猜测
    assert plan["domain"] is None or plan["domain_verified"] is True
    assert "禁止猜域名" in plan["note"]


def test_sweep_of_unknown_school_marks_everything_missing_or_online():
    ledger = sweep_sources(CORE, school="不存在的大学", major="人工智能",
                           materials=("培养目标",), max_files_per_kind=2)
    block = ledger["materials"]["培养目标"]
    assert block["n_hit"] == 0
    assert any(a["state"] == "need_online" for a in block["attempts"])
    assert ledger["summary"]["needs_online"]["培养目标"] is True


def test_render_ledger_markdown_lists_sources_and_online_plan():
    ledger = sweep_sources(CORE, school="北京工业大学", major="人工智能",
                           materials=("培养目标",), max_files_per_kind=2)
    lines = render_ledger_markdown(ledger, limit=6)
    text = "\n".join(lines)
    assert "全面检索台账" in text
    assert "pdf_text" in text

"""Evaluation dimensions 7 & 10: evidence completeness and tool correctness."""

from __future__ import annotations

import json

from edumatch.tools import TOOL_REGISTRY, call_tool, list_tools
from mcp_servers.server import MCPServer


def test_tool_registry_has_all_required_groups():
    groups = {t["group"] for t in list_tools()}
    assert groups == {"education", "recruitment", "policy", "analysis", "evidence",
                      "supply_source"}
    assert len(TOOL_REGISTRY) >= 30


def test_every_tool_has_valid_schema():
    for spec in TOOL_REGISTRY.values():
        assert spec.input_schema["type"] == "object"
        assert spec.description


def test_evidence_tools_return_traceable_chain():
    result = call_tool("trace_claim", {"claim": "数据工程是主要技能缺口"})
    assert result["trace"]
    for item in result["trace"]:
        assert "calculation" in item
        assert "evidence_level" in item


def test_mcp_initialize_and_tools_list():
    server = MCPServer("education")
    init = server.handle({"id": 1, "method": "initialize"})
    assert init["result"]["serverInfo"]["name"] == "edumatch-mcp-education"
    tools = server.handle({"id": 2, "method": "tools/list"})["result"]["tools"]
    assert {t["name"] for t in tools} == {
        "search_school", "search_major", "query_curriculum", "query_employment",
        "find_report_evidence", "get_report",
    }


def test_mcp_tools_call_returns_json_content():
    server = MCPServer("recruitment")
    response = server.handle({
        "id": 3, "method": "tools/call",
        "params": {"name": "normalize_job",
                   "arguments": {"company": "北京某某科技有限公司", "position": "AI算法工程师",
                                 "city": "北京市", "salary": "15-25K"}},
    })
    payload = json.loads(response["result"]["content"][0]["text"])
    assert payload["city_norm"] == "北京"
    assert payload["salary"]["min"] == 15000
    assert payload["salary"]["max"] == 25000


def test_mcp_rejects_unknown_method():
    server = MCPServer(None)
    response = server.handle({"id": 9, "method": "does/not/exist"})
    assert response["error"]["code"] == -32601


def test_evidence_ids_resolve_to_sources(run_result):
    evidence_ids = {e["evidence_id"] for e in run_result["evidence"]}
    assert evidence_ids
    for item in run_result["evidence"]:
        assert item["locator"], item
        assert item["evidence_level"] in {"A", "B", "C", "D", "E"}


def test_job_deduplication_three_tier_counts():
    """Funnel semantics: raw = deduplicated + duplicates + unpairable rows."""
    from edumatch.jobs.dedup import deduplicate_jobs

    rows = [
        {"job_id": "1", "company": "北京某科技有限公司", "position": "AI算法工程师",
         "city": "北京市", "salary": "15-25K", "job_description": "负责模型训练与部署"},
        # exact duplicate (different page, same fingerprint)
        {"job_id": "2", "company": "北京某科技有限公司", "position": "AI算法工程师（急聘）",
         "city": "北京", "salary": "15-25K", "job_description": "负责模型训练与部署"},
        # distinct role
        {"job_id": "3", "company": "另一家公司", "position": "数据工程师",
         "city": "北京市", "salary": "20-30K", "job_description": "数据管道与治理"},
        # unpairable row: no position -> cannot be fingerprinted
        {"job_id": "4", "company": "x", "position": "", "city": "北京", "salary": "面议"},
        # unique postings but no description/skills -> counted as deduplicated, not effective
        {"job_id": "5", "company": "第三家公司", "position": "前端开发工程师",
         "city": "北京市", "salary": "面议"},
    ]
    kept, report = deduplicate_jobs(rows)
    data = report.to_dict()
    assert data["raw_count"] == 5
    assert data["duplicate_fingerprints"] == 1        # job 2 collapsed into job 1
    assert data["deduplicated_count"] == 3            # jobs 1, 3, 5
    assert data["effective_count"] == 2               # job 5 has no usable content
    assert data["dropped_invalid"] == 2               # job 4 (no position) + job 5 (no content)
    # 口径自洽：raw = deduplicated + duplicates + unpairable
    assert data["raw_count"] == data["deduplicated_count"] + 1 + 1
    assert {r["job_id"] for r in kept} == {"1", "3"}

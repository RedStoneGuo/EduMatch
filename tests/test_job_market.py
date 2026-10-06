"""Job-market layer: HAR import, de-duplication, compliance guards, statistics."""

from __future__ import annotations

from pathlib import Path

import pytest

from edumatch.jobs import crawler
from edumatch.jobs.adapters import list_adapters
from edumatch.jobs.adapters.zhaopin import ZhaopinHarAdapter
from edumatch.jobs.har_import import find_har_files, import_har

ROOT = Path(__file__).resolve().parents[1]


def _har_by_keyword(name_part: str) -> Path | None:
    for path in find_har_files():
        if name_part in path.name:
            return path
    return None


HAR_AI = _har_by_keyword("搜索") or (ROOT.parent / "搜索.har")
HAR_GENERAL = _har_by_keyword("招聘信息获取") or (ROOT.parent / "招聘信息获取.har")


def test_har_import_extracts_jobs_and_keyword():
    if not HAR_AI.exists():
        pytest.skip("search HAR not available")
    jobset = import_har(HAR_AI, dataset_id="t")
    assert jobset.search_keyword == "人工智能"
    assert jobset.raw_rows >= len(jobset.records) > 0
    assert jobset.reported_count and jobset.reported_count > 0
    first = jobset.records[0]
    for key in ("job_id", "company", "position", "city", "education", "job_description", "crawl_time"):
        assert first.get(key) is not None, key
    assert len(first["job_description"]) > 20


def test_har_import_never_carries_session_credentials():
    if not HAR_AI.exists():
        pytest.skip("search HAR not available")
    jobset = import_har(HAR_AI, dataset_id="t")
    blob = str(jobset.records)
    for secret_key in ("\"at\"", "\"rt\"", "cookie", "authorization", "displayPhoneNumber", "alreadyCallPhone"):
        assert secret_key.lower() not in blob.lower(), secret_key


def test_raw_rows_exceed_unique_ids_across_pages():
    if not HAR_GENERAL.exists():
        pytest.skip("general HAR not available")
    jobset = import_har(HAR_GENERAL, dataset_id="t")
    assert jobset.page_responses >= 1
    assert jobset.raw_rows > len(jobset.records), "跨页重复应使原始行数大于唯一岗位数"


def test_blocked_source_and_robots_gate():
    url = "https://cgate.zhaopin.com/positionbusiness/searchrecommend/searchPositions?x-zp-client-id=abc"
    info = crawler.check_blocked_source(url)
    assert info is not None
    assert "robots.txt" in info["reason"]
    policy = crawler.CrawlPolicy(user_agent="EduMatchResearchBot/2.0")
    assert crawler.robots_allows(url, policy) is False


def test_credential_reuse_is_blocked():
    with pytest.raises(crawler.CredentialReuseBlocked):
        crawler.assert_no_credentials({"Cookie": "a=b"})
    with pytest.raises(crawler.CredentialReuseBlocked):
        crawler.assert_no_credentials({"Authorization": "Bearer x"})
    crawler.assert_no_credentials({"User-Agent": "EduMatchResearchBot/2.0"})


def test_adapter_declares_policy_and_refuses_automation():
    adapter = ZhaopinHarAdapter()
    assert adapter.blocked is True
    result = adapter.fetch()
    assert result["status"] == "blocked_by_policy"
    assert result["alternative"]
    assert list_adapters()[0]["automated_access_allowed"] is False


def test_job_statistics_from_imported_jobs(dataset):
    if not dataset.jobs:
        pytest.skip("jobs.json not built; run scripts/import_har_jobs.py")
    stats = dataset.job_statistics()
    assert stats["status"] == "ok"
    counts = stats["counts"]
    assert counts["raw_count"] >= counts["deduplicated_count"] >= counts["effective_count"]
    assert stats["n_target_jobs"] > 0
    assert 0 <= stats["bachelor_share"] <= 1
    assert 0 <= stats["target_city_share"] <= 1
    assert stats["median_salary_target"] and stats["median_salary_baseline"]
    assert stats["salary_premium"] is not None
    assert stats["evidence_level"] == "C"


def test_salary_is_monthly_only_and_reaches_the_occupation_slice(dataset):
    """招聘岗位的薪资必须真的被用上：月薪中位数/分位/分档都要有，且日薪不混入。"""
    if not dataset.jobs:
        pytest.skip("jobs.json not built; run scripts/import_har_jobs.py")
    stats = dataset.job_statistics()
    assert stats["median_salary_target"] and stats["median_salary_baseline"]
    assert stats["salary_p25_target"] and stats["salary_p75_target"]
    assert stats["salary_buckets"], "必须给出月薪分档分布"
    assert stats["n_salary_target"] > 0
    assert "n_daily_salary_excluded" in stats
    _, info = dataset.occupation_demand("数据分析师")
    req = info.get("requirements") or {}
    assert req.get("median_salary"), "目标岗位切片必须给出月薪中位数（此前恒为 null）"
    assert req.get("n_with_salary") and req.get("salary_buckets")
    assert req.get("salary_note") == ""


def test_demand_vector_uses_real_postings(dataset):
    if not dataset.jobs:
        pytest.skip("jobs.json not built")
    demands = dataset.demand_vector()
    assert demands
    top = demands[0]
    assert top.n_postings == len(dataset.target_jobs())
    assert top.evidence_level == "C"
    assert "trend" in top.missing_components, "单期数据不得给出趋势"
    assert "salary_premium" not in top.available_components or top.components["salary_premium"] is not None


# ---------------- permission-checked automated retrieval ----------------

class _FakeRobots:
    def __init__(self, allow: bool):
        self.allow = allow

    def can_fetch(self, user_agent: str, url: str) -> bool:
        return self.allow


def _reader(allow_map: dict[str, bool]):
    def reader(robots_url: str):
        host = robots_url.replace("https://", "").replace("/robots.txt", "")
        if host not in allow_map:
            return None, "unreachable:HTTPError"
        return _FakeRobots(allow_map[host]), "ok"

    return reader


def test_permission_checked_crawler_allows_permitted_site():
    from edumatch.jobs.permitted_crawler import check_permission

    decision = check_permission("https://jobs.example.org/list?page=1", "EduMatchResearchBot/2.0",
                                robots_reader=_reader({"jobs.example.org": True}))
    assert decision.allowed is True
    assert decision.robots_url.endswith("/robots.txt")


def test_permission_checked_crawler_blocks_disallowed_path():
    from edumatch.jobs.permitted_crawler import check_permission

    decision = check_permission("https://jobs.example.org/list?page=1", "EduMatchResearchBot/2.0",
                                robots_reader=_reader({"jobs.example.org": False}))
    assert decision.allowed is False
    assert "robots.txt" in decision.reason


def test_permission_checked_crawler_refuses_when_robots_unreachable():
    from edumatch.jobs.permitted_crawler import check_permission

    decision = check_permission("https://unknown.example.org/a", "EduMatchResearchBot/2.0",
                                robots_reader=_reader({}))
    assert decision.allowed is False
    assert "最保守" in decision.reason


def test_robots_is_per_origin_not_inherited_from_parent_domain():
    """RFC 9309: robots.txt applies per origin; the parent domain must not leak
    its rules onto an independent sub-host (regression for a real false denial
    on public-sector sites such as jw.beijing.gov.cn)."""
    from edumatch.jobs.permitted_crawler import check_permission

    decision = check_permission("https://api.example.org/jobs", "EduMatchResearchBot/2.0",
                                robots_reader=_reader({"api.example.org": True, "example.org": False}))
    assert decision.allowed is True


def test_fetch_refuses_without_explicit_enable(monkeypatch):
    from edumatch.jobs import permitted_crawler

    monkeypatch.delenv("EDUMATCH_ENABLE_CRAWLER", raising=False)
    policy = crawler.CrawlPolicy(user_agent="EduMatchResearchBot/2.0")
    result = permitted_crawler.fetch_allowed(
        "https://jobs.example.org/list", policy,
        robots_reader=_reader({"jobs.example.org": True}),
        fetcher=lambda url, ua: "<html>ok</html>",
    )
    assert result.status == "blocked"
    assert "EDUMATCH_ENABLE_CRAWLER" in result.error


def test_fetch_works_when_enabled_and_permitted(monkeypatch, tmp_path):
    from edumatch.jobs import permitted_crawler

    monkeypatch.setenv("EDUMATCH_ENABLE_CRAWLER", "1")
    policy = crawler.CrawlPolicy(user_agent="EduMatchResearchBot/2.0", interval_seconds=0.0,
                                 cache_dir=tmp_path)
    calls: list[str] = []

    def fake_fetcher(url: str, ua: str) -> str:
        calls.append(ua)
        return "<html>job list</html>"

    result = permitted_crawler.fetch_allowed(
        "https://jobs.example.org/list", policy,
        robots_reader=_reader({"jobs.example.org": True}), fetcher=fake_fetcher,
    )
    assert result.status == "ok"
    assert result.bytes > 0
    assert calls == ["EduMatchResearchBot/2.0"]      # 只发声明过的 UA，不带任何凭据

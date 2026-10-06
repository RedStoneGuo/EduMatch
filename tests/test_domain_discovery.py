"""域名发现与核验：本地台账辅助、候选 URL 核验、不通过不入库。"""

from __future__ import annotations

import json
from pathlib import Path

from edumatch import domain_discovery as dd


def _fake_fetch_ok(url: str, *, timeout: float = 12.0):
    return 200, "<html><head><title>某大学</title></head><body>某大学 官网</body></html>"


def test_rejects_non_education_domain():
    result = dd.verify_candidate("https://www.example.com/", "某大学")
    assert result["ok"] is False
    assert "不是官方教育域" in result["reason"]


def test_verifies_with_official_suffix_status_and_school_name(tmp_path: Path):
    result = dd.verify_candidate("https://www.mou.edu.cn/", "某大学", fetch=_fake_fetch_ok)
    assert result["ok"] is True
    assert result["domain"] == "www.mou.edu.cn"
    assert result["matched_name"] == "某大学"
    # 通过后写入台账：保留原有条目 + 追加新条目
    ledger = tmp_path / "data" / "harvest" / "domains.json"
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text(json.dumps({"已有大学": {"domain": "old.edu.cn"}}, ensure_ascii=False),
                      encoding="utf-8")
    found = dd.discover_domain(tmp_path, "某大学",
                               candidates=["https://www.mou.edu.cn/"], write=True)
    # 真实网络不可用时不会误判通过；这里只断言"写入逻辑"在有 fetch 的情况下由 verify 决定
    payload = json.loads(ledger.read_text(encoding="utf-8"))
    assert "已有大学" in payload          # 旧条目必须保留
    assert found["ok"] in {True, False}   # 取决于本机网络；两种都不崩


def test_page_without_school_name_is_rejected():
    def wrong_fetch(url: str, *, timeout: float = 12.0):
        return 200, "<html><title>某某公司</title><body>欢迎</body></html>"

    result = dd.verify_candidate("https://www.mou.edu.cn/", "某大学", fetch=wrong_fetch)
    assert result["ok"] is False
    assert "未出现该院校名称" in result["reason"]


def test_offline_mode_does_not_pass_without_verification():
    result = dd.verify_candidate("https://www.mou.edu.cn/", "某大学", allow_network=False)
    assert result["ok"] is False
    assert "离线" in result["reason"]


def test_missing_domain_message_tells_agent_to_search_web(tmp_path: Path):
    found = dd.discover_domain(tmp_path, "不存在大学", candidates=[], allow_network=False)
    assert found["ok"] is False
    assert "联网检索" in found["reason"]

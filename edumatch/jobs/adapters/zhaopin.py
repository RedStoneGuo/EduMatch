"""智联招聘数据接入适配器（合规版）。

设计结论：**不实现绕过访问控制的自动抓取**。

审计证据（本次实施时联网获取）：

* ``https://www.zhaopin.com/robots.txt``：``User-agent: *`` 段包含
  ``Disallow: /*?*``、``Disallow: */api/*``、``Disallow: /*.json*``、
  ``Disallow: /recommend*``、``Disallow: /resume*``；
* ``https://xiaoyuan.zhaopin.com/robots.txt``：``User-agent: *`` 允许 ``/``，
  但 ``Disallow: *?*``；
* ``https://cgate.zhaopin.com/robots.txt``：404（该主机未声明规则）。

接口 ``POST /positionbusiness/searchrecommend/searchPositions`` 必须携带查询串
（``x-zp-page-request-id`` / ``x-zp-client-id``），因此落在上述 ``/*?*`` 与
``*/api/*`` 的禁止范围内。HAR 中的 ``at`` / ``rt`` 属会话凭据，复用它们发请求
即构成"绕过访问控制"，本项目明确不做。

本适配器提供两条合规路径：

1. ``mode="har"``（推荐、已实现）：研究者在本机浏览器正常检索并导出 HAR，
   放入 ``data/raw/har/``，由 ``scripts/import_har_jobs.py`` 自动解析入库；
2. ``mode="official"``（预留）：若取得智联招聘官方授权、合作或开放接口，
   在 ``config`` 中登记凭证后启用，请求头由官方渠道下发，不复用个人会话。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..crawler import BLOCKED_SOURCES, check_blocked_source


@dataclass
class AdapterPolicy:
    site: str
    automated_access_allowed: bool
    blocked_reason: str
    allowed_modes: list[str]
    compliant_workflow: list[str]

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


class ZhaopinHarAdapter:
    """合规接入器：负责 HAR 导入与策略声明，不发起绕过性请求。"""

    site = "zhaopin.com"
    endpoint = "POST https://cgate.zhaopin.com/positionbusiness/searchrecommend/searchPositions"
    blocked = True

    def policy(self) -> AdapterPolicy:
        info = BLOCKED_SOURCES.get(self.site, {})
        return AdapterPolicy(
            site=self.site,
            automated_access_allowed=False,
            blocked_reason=info.get("reason", "robots.txt 禁止自动访问"),
            allowed_modes=["har", "official"],
            compliant_workflow=[
                "在浏览器中正常检索（关键词/城市/翻页），不使用脚本绕过任何限制",
                "导出 HAR：DevTools → Network → 右键 → Save all as HAR with content",
                "把 HAR 放入 data/raw/har/（可放多个，按关键词或城市分批）",
                "运行 python scripts/import_har_jobs.py 自动解析、去重、抽技能并入库",
                "重新运行分析：python -m agent.runner --simulate --template",
            ],
        )

    def fetch(self, *_: Any, **__: Any) -> dict[str, Any]:
        """任何自动抓取请求都会被拒绝，并返回合规替代方案。"""
        return {
            "status": "blocked_by_policy",
            "site": self.site,
            "endpoint": self.endpoint,
            "reason": self.policy().blocked_reason,
            "evidence": BLOCKED_SOURCES.get(self.site, {}).get("evidence"),
            "not_performed": [
                "复用 HAR 中的 at/rt/cookie 会话凭据",
                "伪造/轮换 User-Agent 以规避反爬",
                "绕过验证码、登录墙或频率限制",
            ],
            "alternative": self.policy().compliant_workflow,
        }

    def import_har(self, path: Path) -> dict[str, Any]:
        from ..har_import import import_har

        jobset = import_har(path)
        return jobset.to_dict()


ADAPTERS: dict[str, ZhaopinHarAdapter] = {ZhaopinHarAdapter.site: ZhaopinHarAdapter()}


def get_adapter(site: str) -> ZhaopinHarAdapter | None:
    for key, adapter in ADAPTERS.items():
        if key == site or key in site:
            return adapter
    return None


def list_adapters() -> list[dict[str, Any]]:
    out = []
    for adapter in ADAPTERS.values():
        policy = adapter.policy()
        out.append({
            "site": policy.site,
            "endpoint": adapter.endpoint,
            "automated_access_allowed": policy.automated_access_allowed,
            "blocked_reason": policy.blocked_reason,
            "allowed_modes": policy.allowed_modes,
        })
    return out


def check_url(url: str) -> dict[str, Any] | None:
    return check_blocked_source(url)

"""Compliance-first job crawler skeleton.

Design constraints (enforced in code, not only in documentation):

* disabled unless ``EDUMATCH_ENABLE_CRAWLER=1`` is set explicitly;
* ``robots.txt`` is fetched and obeyed before any page request;
* one request per ``request_interval_seconds`` with an on-disk cache;
* no login, no CAPTCHA bypass, no anti-bot circumvention, no private endpoints;
* every stored row keeps ``source`` / ``url`` / ``crawl_time``.

The module is intentionally a *framework*: site-specific selectors belong to
adapters that must be reviewed against the target site's terms of service.
"""

from __future__ import annotations

import os
import time
import urllib.robotparser
from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha1
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import urlparse

from ..config import Settings, load_settings


class CrawlNotPermitted(RuntimeError):
    """Raised when the crawler is disabled or robots.txt forbids the path."""


class CredentialReuseBlocked(CrawlNotPermitted):
    """Raised when a request would replay captured session credentials."""


FORBIDDEN_HEADERS = {
    "cookie", "set-cookie", "authorization", "x-authorization", "token",
    "x-auth-token", "x-xsrf-token", "x-csrf-token", "proxy-authorization",
}

# Hosts whose robots.txt / terms forbid the automated access this project would
# need. Kept as data (not a code branch) so the decision is auditable.
BLOCKED_SOURCES: dict[str, dict[str, str]] = {
    "zhaopin.com": {
        "reason": "robots.txt for User-agent:* contains 'Disallow: /*?*' and 'Disallow: */api/*'",
        "evidence": "https://www.zhaopin.com/robots.txt (fetched during audit)",
        "decision": "本地自动抓取被拒绝；改用用户本人浏览器抓包的 HAR 数据（scripts/import_har_jobs.py）",
    },
    "xiaoyuan.zhaopin.com": {
        "reason": "robots.txt for User-agent:* contains 'Disallow: *?*'",
        "evidence": "https://xiaoyuan.zhaopin.com/robots.txt (fetched during audit)",
        "decision": "同上",
    },
}


def registrable_domain(host: str) -> str:
    """Very small eTLD+1 helper for the domains this project touches."""
    parts = host.split(".")
    if len(parts) <= 2:
        return host
    two_level_tlds = {"com.cn", "net.cn", "org.cn", "gov.cn", "edu.cn", "co.uk", "com.hk"}
    if ".".join(parts[-2:]) in two_level_tlds and len(parts) >= 3:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def assert_no_credentials(headers: dict[str, str] | None) -> None:
    """Refuse to send captured session credentials - this is the anti-bypass guard."""
    for name in (headers or {}):
        if name.lower() in FORBIDDEN_HEADERS:
            raise CredentialReuseBlocked(
                f"refusing to send credential header {name!r}: replaying a captured session "
                "token to reach restricted endpoints is an access-control bypass and is out of scope"
            )


def check_blocked_source(url: str) -> dict[str, str] | None:
    host = urlparse(url).netloc.lower()
    for domain, info in BLOCKED_SOURCES.items():
        if host == domain or host.endswith("." + domain) or registrable_domain(host) == domain:
            return {"host": host, **info}
    return None


@dataclass
class CrawlPolicy:
    user_agent: str
    interval_seconds: float = 3.0
    respect_robots: bool = True
    cache_dir: Path | None = None
    last_request_at: float = 0.0
    robots_cache: dict[str, urllib.robotparser.RobotFileParser] = field(default_factory=dict)

    @classmethod
    def from_settings(cls, settings: Settings) -> "CrawlPolicy":
        cfg = settings.section("recruitment")
        cache = settings.resolve(cfg.get("cache_dir", "data/raw/cache"))
        cache.mkdir(parents=True, exist_ok=True)
        return cls(
            user_agent=str(cfg.get("user_agent", "EduMatchResearchBot/2.0")),
            interval_seconds=float(cfg.get("request_interval_seconds", 3.0)),
            respect_robots=bool(cfg.get("respect_robots_txt", True)),
            cache_dir=cache,
        )


def crawler_enabled() -> bool:
    return os.environ.get("EDUMATCH_ENABLE_CRAWLER", "").strip() in {"1", "true", "True", "yes"}


def robots_allows(url: str, policy: CrawlPolicy) -> bool:
    if not policy.respect_robots:
        return True
    parsed = urlparse(url)
    if check_blocked_source(url):
        return False
    root = f"{parsed.scheme}://{parsed.netloc}"
    parser = policy.robots_cache.get(root)
    if parser is None:
        parser = urllib.robotparser.RobotFileParser()
        parser.set_url(f"{root}/robots.txt")
        try:
            parser.read()
        except Exception:  # noqa: BLE001 - unreachable robots.txt => refuse
            return False
        policy.robots_cache[root] = parser
    if not parser.can_fetch(policy.user_agent, url):
        return False
    # Alse check the site family (e.g. www.zhaopin.com rules also inform the
    # operator's intent for sibling hosts that expose no robots.txt).
    family = registrable_domain(parsed.netloc)
    if family != parsed.netloc:
        family_parser = policy.robots_cache.get(family)
        if family_parser is None:
            family_parser = urllib.robotparser.RobotFileParser()
            family_parser.set_url(f"https://{family}/robots.txt")
            try:
                family_parser.read()
            except Exception:  # noqa: BLE001
                family_parser = None
            if family_parser is not None:
                policy.robots_cache[family] = family_parser
        if family_parser is not None and not family_parser.can_fetch(policy.user_agent, url):
            return False
    return True


def _cache_path(url: str, policy: CrawlPolicy) -> Path:
    assert policy.cache_dir is not None
    return policy.cache_dir / f"{sha1(url.encode('utf-8')).hexdigest()}.html"


def fetch(url: str, policy: CrawlPolicy, fetch_fn: Callable[[str, str], str] | None = None) -> str:
    """Rate-limited, robots-aware, cached GET. ``fetch_fn`` enables offline tests."""
    if not crawler_enabled():
        raise CrawlNotPermitted(
            "crawler disabled; set EDUMATCH_ENABLE_CRAWLER=1 only after confirming "
            "the target site's robots.txt and terms of service allow collection"
        )
    if not robots_allows(url, policy):
        raise CrawlNotPermitted(f"robots.txt forbids fetching {url}")
    cache_file = _cache_path(url, policy)
    if cache_file.exists():
        return cache_file.read_text(encoding="utf-8", errors="replace")
    wait = policy.interval_seconds - (time.monotonic() - policy.last_request_at)
    if wait > 0:
        time.sleep(wait)
    if fetch_fn is None:
        import httpx  # local import keeps the dependency optional

        response = httpx.get(url, headers={"User-Agent": policy.user_agent}, timeout=20.0)
        response.raise_for_status()
        html = response.text
    else:
        html = fetch_fn(url, policy.user_agent)
    policy.last_request_at = time.monotonic()
    cache_file.write_text(html, encoding="utf-8")
    return html


def stamp(job: dict[str, Any], source: str, url: str) -> dict[str, Any]:
    return {
        **job,
        "source": source,
        "url": url,
        "crawl_time": datetime.now(timezone.utc).isoformat(),
    }


def crawl(*urls: Iterable[str], policy: CrawlPolicy | None = None) -> list[str]:
    """Return fetched HTML for the given URLs, honouring the crawl policy."""
    policy = policy or CrawlPolicy.from_settings(load_settings())
    return [fetch(url, policy) for url in urls]

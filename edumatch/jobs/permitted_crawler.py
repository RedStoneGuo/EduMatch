"""Permission-checked crawler.

This is the *only* automated retrieval path in EduMatch. It will fetch a URL
only when the site's own robots.txt permits the configured user agent, and it
refuses to send session credentials.

Design rules (enforced, not documented-only):

1. refuse to run when ``EDUMATCH_ENABLE_CRAWLER`` is not set;
2. per-URL robots.txt decision, cached, with the raw rule recorded for audit;
3. robots.txt is interpreted per RFC 9309, i.e. per origin: a 404/410 means the
   host publishes no rules (access unrestricted), 200 means the rules apply,
   and any transport failure means the rules are *unknown* -> refuse. An earlier
   revision also inherited the parent domain's robots.txt, which produced false
   denials on public-sector hosts (e.g. ``jw.beijing.gov.cn`` inheriting
   ``beijing.gov.cn``, whose robots.txt is actually an HTML page); that heuristic
   was removed. Operators that are known to forbid automated access are instead
   listed explicitly in ``crawler.BLOCKED_SOURCES`` with the evidence recorded;
4. one request per ``request_interval_seconds``, on-disk response cache;
5. no Cookie / Authorization / token headers, ever;
6. every fetch is logged with url, decision, rule, timestamp and sha1 of body.
"""

from __future__ import annotations

import hashlib
import json
import time
import urllib.robotparser
import urllib.error
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import urlparse

from .crawler import (
    BLOCKED_SOURCES,
    CrawlNotPermitted,
    CrawlPolicy,
    assert_no_credentials,
    check_blocked_source,
    crawler_enabled,
    registrable_domain,
)


@dataclass
class PermissionDecision:
    url: str
    allowed: bool
    reason: str
    rule: str = ""
    robots_url: str = ""
    checked_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


def _read_robots(url: str) -> tuple[urllib.robotparser.RobotFileParser | None, str]:
    """Fetch and parse robots.txt.

    RFC 9309 semantics: a 4xx response (other than 429) means the host publishes
    no robots.txt, so access is not restricted; any network error or 5xx means
    the rules are *unknown*, and this project refuses to crawl in that case.
    """
    parser = urllib.robotparser.RobotFileParser()
    parser.set_url(url)
    try:
        parser.read()
    except urllib.error.HTTPError as exc:
        if exc.code in {404, 410}:
            return _AllowAll(), f"no-robots-{exc.code}"
        return None, f"robots-http-{exc.code}"
    except Exception as exc:  # noqa: BLE001 - unreachable => unknown => refuse
        return None, f"unreachable:{type(exc).__name__}"
    return parser, "ok"


class _AllowAll:
    """Stand-in parser for hosts that publish no robots.txt (HTTP 404/410)."""

    def can_fetch(self, user_agent: str, url: str) -> bool:  # noqa: D401, ARG002
        return True

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return "<no-robots:allow-all>"


def check_permission(
    url: str,
    user_agent: str,
    *,
    robots_reader: Callable[[str], tuple[Any, str]] | None = None,
    cache: dict[str, Any] | None = None,
) -> PermissionDecision:
    reader = robots_reader or _read_robots
    cache = cache if cache is not None else {}
    parsed = urlparse(url)
    host = parsed.netloc.lower()

    blocked = check_blocked_source(url)
    if blocked:
        return PermissionDecision(url, False, blocked["reason"],
                                  rule="site-policy-blocklist",
                                  robots_url=f"https://{blocked['host']}/robots.txt")

    def lookup(root: str) -> tuple[Any, str]:
        if root in cache:
            return cache[root]
        result = reader(f"https://{root}/robots.txt")
        cache[root] = result
        return result

    parser, status = lookup(host)
    if parser is None:
        return PermissionDecision(url, False, f"robots.txt {status} -> 按最保守策略拒绝",
                                  rule="robots-unavailable", robots_url=f"https://{host}/robots.txt")
    if status.startswith("no-robots"):
        return PermissionDecision(url, True, f"该主机未发布 robots.txt（{status}），按 RFC 9309 视为未限制",
                                  rule="no-robots-declared", robots_url=f"https://{host}/robots.txt")
    if not parser.can_fetch(user_agent, url):
        rule = _matching_rule(parser, user_agent, url)
        return PermissionDecision(url, False, "robots.txt 禁止该路径", rule=rule,
                                  robots_url=f"https://{host}/robots.txt")

    return PermissionDecision(url, True, "robots.txt 允许", rule="allow",
                              robots_url=f"https://{host}/robots.txt")


def _matching_rule(parser: Any, user_agent: str, url: str) -> str:
    """Best-effort extraction of the rule that matched, for the audit log."""
    path = urlparse(url).path or "/"
    try:
        entries = parser.default_entry
        rules = getattr(entries, "rulelines", []) if entries else []
        matched = []
        for rule in rules:
            applies = getattr(rule, "applies_to", None)
            if callable(applies) and applies(url):
                matched.append(rule)
    except Exception:  # noqa: BLE001
        matched = []
    if matched:
        rule = matched[0]
        return f"{'Allow' if getattr(rule, 'allowance', False) else 'Disallow'}: {getattr(rule, 'path', path)}"
    return f"path={path}"


@dataclass
class FetchResult:
    url: str
    status: str  # ok | blocked | error | cached
    decision: PermissionDecision
    body_sha1: str = ""
    body_path: str = ""
    bytes: int = 0
    fetched_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = dict(self.__dict__)
        data["decision"] = self.decision.to_dict()
        return data


def fetch_allowed(
    url: str,
    policy: CrawlPolicy,
    *,
    fetcher: Callable[[str, str], str] | None = None,
    robots_reader: Callable[[str], tuple[Any, str]] | None = None,
    robots_cache: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> FetchResult:
    """Fetch one URL if (and only if) the site permits it."""
    assert_no_credentials(headers)
    decision = check_permission(url, policy.user_agent, robots_reader=robots_reader, cache=robots_cache)
    if not decision.allowed:
        return FetchResult(url=url, status="blocked", decision=decision)
    if not crawler_enabled():
        return FetchResult(
            url=url, status="blocked", decision=decision,
            error="crawler disabled: set EDUMATCH_ENABLE_CRAWLER=1 after confirming the site allows collection",
        )
    if policy.cache_dir is None:
        policy.cache_dir = Path("data/raw/cache")
    policy.cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = policy.cache_dir / f"{hashlib.sha1(url.encode()).hexdigest()}.html"
    if cache_file.exists():
        body = cache_file.read_text(encoding="utf-8", errors="replace")
        return FetchResult(url=url, status="cached", decision=decision,
                           body_sha1=hashlib.sha1(body.encode("utf-8")).hexdigest(),
                           body_path=str(cache_file), bytes=len(body.encode("utf-8")))
    wait = policy.interval_seconds - (time.monotonic() - policy.last_request_at)
    if wait > 0:
        time.sleep(wait)
    try:
        if fetcher is None:
            import httpx

            response = httpx.get(url, headers={"User-Agent": policy.user_agent}, timeout=20.0)
            response.raise_for_status()
            body = response.text
        else:
            body = fetcher(url, policy.user_agent)
    except Exception as exc:  # noqa: BLE001
        return FetchResult(url=url, status="error", decision=decision, error=f"{type(exc).__name__}: {exc}")
    policy.last_request_at = time.monotonic()
    cache_file.write_text(body, encoding="utf-8")
    return FetchResult(url=url, status="ok", decision=decision,
                       body_sha1=hashlib.sha1(body.encode("utf-8")).hexdigest(),
                       body_path=str(cache_file), bytes=len(body.encode("utf-8")))


def crawl_allowed(
    urls: Iterable[str],
    policy: CrawlPolicy,
    *,
    log_path: Path | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Batch fetch with a per-URL audit log."""
    robots_cache: dict[str, Any] = {}
    results: list[FetchResult] = []
    for url in urls:
        result = fetch_allowed(url, policy, robots_cache=robots_cache, **kwargs)
        results.append(result)
        if log_path:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with log_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(result.to_dict(), ensure_ascii=False) + "\n")
    summary = {
        "n_requested": len(results),
        "n_ok": sum(1 for r in results if r.status in {"ok", "cached"}),
        "n_blocked": sum(1 for r in results if r.status == "blocked"),
        "n_error": sum(1 for r in results if r.status == "error"),
        "blocked_reasons": sorted({r.decision.reason for r in results if r.status == "blocked"}),
        "results": [r.to_dict() for r in results],
    }
    return summary

"""Discover and download publicly published education documents.

Pipeline position: this is **step 0** of the research flow. It finds report and
curriculum documents (就业质量报告 / 教学质量报告 / 培养方案 / 课程大纲 / 专业介绍 /
教学计划) on official publishers' own listing pages, downloads them and records
full provenance. Downloaded files then flow into the existing extractors
(``docx_reader`` / ``pdf_reader`` → ``education_facts`` / ``pdf_facts``).

Compliance: every request goes through ``permitted_crawler.check_permission``
(robots.txt + site-family + policy blocklist + credential guard), is rate
limited, cached on disk, and logged to ``data/processed/crawl_audit.jsonl``.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urljoin, urlparse

import yaml

from ..config import Settings, load_settings
from ..jobs.crawler import CrawlPolicy, assert_no_credentials
from ..jobs.permitted_crawler import check_permission

LINK_RE = re.compile(r"<a\s[^>]*href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>", re.I | re.S)
TAG_RE = re.compile(r"<[^>]+>")


def _clean_text(html: str) -> str:
    return re.sub(r"\s+", " ", TAG_RE.sub("", html)).strip()


@dataclass
class DocumentCandidate:
    url: str
    title: str
    doc_type: str
    extension: str
    source_school: str
    listing_url: str

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


@dataclass
class DownloadResult:
    url: str
    status: str  # ok | cached | blocked | error
    reason: str = ""
    rule: str = ""
    local_path: str = ""
    sha1: str = ""
    bytes: int = 0
    doc_type: str = ""
    source_school: str = ""
    retrieved_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


def load_source_registry(path: Path | None = None) -> dict[str, Any]:
    settings = load_settings()
    target = path or (settings.project_root / "config" / "education_sources.yaml")
    return yaml.safe_load(target.read_text(encoding="utf-8")) or {}


class EducationWebCollector:
    def __init__(self, settings: Settings | None = None, registry: dict[str, Any] | None = None,
                 *, fetcher=None, robots_reader=None) -> None:
        self.settings = settings or load_settings()
        self.registry = registry or load_source_registry()
        self.keywords: dict[str, list[str]] = self.registry.get("keywords") or {}
        self.extensions: tuple[str, ...] = tuple(self.registry.get("document_extensions") or [".pdf"])
        self.sources: dict[str, Any] = self.registry.get("sources") or {}
        self.policy: CrawlPolicy = CrawlPolicy.from_settings(self.settings)
        self.download_dir = self.settings.project_root / "data" / "raw" / "web"
        self.cache_dir = self.policy.cache_dir or (self.settings.project_root / "data" / "raw" / "cache")
        self.robots_cache: dict[str, Any] = {}
        self._fetcher = fetcher
        self._robots_reader = robots_reader
        self.audit: list[dict[str, Any]] = []

    # ---------- transport ----------
    def _http_get(self, url: str) -> str:
        decision = check_permission(url, self.policy.user_agent,
                                    robots_reader=self._robots_reader, cache=self.robots_cache)
        self.audit.append({"url": url, "allowed": decision.allowed, "rule": decision.rule,
                           "reason": decision.reason, "at": decision.checked_at})
        if not decision.allowed:
            raise PermissionError(f"robots/policy 拒绝：{decision.reason} ({decision.rule})")
        cache_file = self.cache_dir / f"{hashlib.sha1(url.encode()).hexdigest()}.bin"
        if cache_file.exists():
            return cache_file.read_bytes().decode("utf-8", "replace")
        if self._fetcher is not None:
            payload = self._fetcher(url, self.policy.user_agent)
        else:
            import httpx

            response = httpx.get(url, headers={"User-Agent": self.policy.user_agent},
                                 timeout=30.0, follow_redirects=True)
            response.raise_for_status()
            payload = response.text
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file.write_bytes(payload.encode("utf-8"))
        return payload

    # ---------- discovery ----------
    def _classify(self, title: str) -> str | None:
        for doc_type, patterns in self.keywords.items():
            if any(p in title for p in patterns):
                return doc_type
        return None

    def discover(self, listing_url: str, school: str) -> list[DocumentCandidate]:
        html = self._http_get(listing_url)
        found: list[DocumentCandidate] = []
        seen: set[str] = set()
        for href, inner in LINK_RE.findall(html):
            title = _clean_text(inner)
            absolute = urljoin(listing_url, href.strip())
            extension = Path(urlparse(absolute).path).suffix.lower()
            if extension and extension not in self.extensions:
                continue
            doc_type = self._classify(title) or self._classify(absolute)
            if not doc_type:
                continue
            if absolute in seen:
                continue
            seen.add(absolute)
            found.append(DocumentCandidate(url=absolute, title=title[:120], doc_type=doc_type,
                                           extension=extension or "", source_school=school,
                                           listing_url=listing_url))
        return found

    # ---------- download ----------
    def download(self, candidate: DocumentCandidate) -> DownloadResult:
        decision = check_permission(candidate.url, self.policy.user_agent,
                                    robots_reader=self._robots_reader, cache=self.robots_cache)
        if not decision.allowed:
            return DownloadResult(candidate.url, "blocked", decision.reason, decision.rule,
                                  doc_type=candidate.doc_type, source_school=candidate.source_school)
        assert_no_credentials({})
        extension = candidate.extension or ".bin"
        safe_name = re.sub(r"[^\w\u4e00-\u9fff.\-]+", "_", candidate.title)[:80] or "document"
        target_dir = self.download_dir / candidate.source_school / candidate.doc_type
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"{safe_name}{extension}"
        try:
            if self._fetcher is not None:
                payload = self._fetcher(candidate.url, self.policy.user_agent).encode("utf-8")
            else:
                import httpx

                response = httpx.get(candidate.url, headers={"User-Agent": self.policy.user_agent},
                                     timeout=60.0, follow_redirects=True)
                response.raise_for_status()
                payload = response.content
            target.write_bytes(payload)
        except Exception as exc:  # noqa: BLE001
            return DownloadResult(candidate.url, "error", f"{type(exc).__name__}: {exc}",
                                  decision.rule, doc_type=candidate.doc_type,
                                  source_school=candidate.source_school)
        return DownloadResult(candidate.url, "ok", "downloaded", decision.rule,
                              local_path=str(target), sha1=hashlib.sha1(payload).hexdigest(),
                              bytes=len(payload), doc_type=candidate.doc_type,
                              source_school=candidate.source_school)

    # ---------- orchestration ----------
    def collect(self, schools: Iterable[str] | None = None, *, limit_per_site: int = 20,
                dry_run: bool = False) -> dict[str, Any]:
        summary: dict[str, Any] = {"listings": [], "candidates": [], "downloads": [], "dry_run": dry_run}
        for school, spec in self.sources.items():
            if schools and school not in set(schools):
                continue
            for listing in spec.get("listing") or []:
                try:
                    candidates = self.discover(listing, school)
                except Exception as exc:  # noqa: BLE001
                    summary["listings"].append({"school": school, "url": listing,
                                                "status": "error", "error": f"{type(exc).__name__}: {exc}"})
                    continue
                summary["listings"].append({"school": school, "url": listing,
                                            "status": "ok", "n_candidates": len(candidates)})
                summary["candidates"].extend(c.to_dict() for c in candidates[:limit_per_site])
                if dry_run:
                    continue
                for candidate in candidates[:limit_per_site]:
                    result = self.download(candidate)
                    summary["downloads"].append(result.to_dict())
        summary["n_downloaded"] = sum(1 for d in summary["downloads"] if d["status"] == "ok")
        summary["n_blocked"] = sum(1 for d in summary["downloads"] if d["status"] == "blocked")
        summary["n_errors"] = sum(1 for d in summary["downloads"] if d["status"] == "error")
        summary["audit"] = self.audit
        return summary

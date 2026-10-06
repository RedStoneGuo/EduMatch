"""Fully automated academic retrieval via open scholarly APIs.

Source selection is permission-driven (verified at implementation time):

* ``api.openalex.org/robots.txt`` -> ``User-agent: * / Allow: /``  → used;
* ``api.crossref.org`` has no robots.txt and documents its public REST API for
  research use → available as a secondary source;
* ``export.arxiv.org/robots.txt`` -> ``Disallow: /`` → deliberately **not** used.

The client is polite by construction: declared user agent, a ``mailto`` contact
parameter (OpenAlex "polite pool"), on-disk caching, and a request interval.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from .config import Settings, load_settings
from .jobs.permitted_crawler import check_permission

OPENALEX_BASE = "https://api.openalex.org/works"
DEFAULT_UA = "EduMatchResearchBot/2.0 (mailto:edumatch-project@example.org)"


@dataclass
class LiteratureWork:
    work_id: str
    title: str
    year: int | None
    doi: str | None
    venue: str | None
    authors: list[str] = field(default_factory=list)
    cited_by_count: int = 0
    type: str | None = None
    open_access_url: str | None = None
    abstract: str = ""
    concepts: list[str] = field(default_factory=list)
    source: str = "openalex"
    url: str = ""
    retrieval_time: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    evidence_level: str = "A"
    query: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _reconstruct_abstract(inverted: dict[str, list[int]] | None) -> str:
    if not inverted:
        return ""
    positions: list[tuple[int, str]] = []
    for word, idxs in inverted.items():
        for idx in idxs:
            positions.append((idx, word))
    positions.sort()
    return " ".join(word for _, word in positions)[:2000]


class OpenAlexClient:
    def __init__(self, settings: Settings | None = None, *, user_agent: str = DEFAULT_UA,
                 contact_email: str = "edumatch-project@example.org",
                 interval_seconds: float = 1.0) -> None:
        self.settings = settings or load_settings()
        self.user_agent = user_agent
        self.contact_email = contact_email
        self.interval_seconds = interval_seconds
        self.cache_dir = self.settings.resolve("data/raw/cache/literature")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.last_request_at = 0.0
        self.robots_cache: dict[str, Any] = {}
        self.audit: list[dict[str, Any]] = []

    # ---------- transport ----------
    def _cache_path(self, url: str) -> Path:
        return self.cache_dir / f"{hashlib.sha1(url.encode()).hexdigest()}.json"

    def _get(self, url: str, *, timeout: float = 25.0, retries: int = 3) -> dict[str, Any]:
        decision = check_permission(url, self.user_agent, cache=self.robots_cache)
        self.audit.append({"url": url, "allowed": decision.allowed, "rule": decision.rule,
                           "robots_url": decision.robots_url, "at": decision.checked_at})
        if not decision.allowed:
            raise PermissionError(f"robots.txt disallows {url}: {decision.reason} ({decision.rule})")

        cache_file = self._cache_path(url)
        if cache_file.exists():
            return json.loads(cache_file.read_text(encoding="utf-8"))

        import httpx

        last_error: Exception | None = None
        for attempt in range(retries):
            wait = self.interval_seconds - (time.monotonic() - self.last_request_at)
            if wait > 0:
                time.sleep(wait)
            try:
                response = httpx.get(url, headers={"User-Agent": self.user_agent}, timeout=timeout)
                self.last_request_at = time.monotonic()
                if response.status_code == 429:
                    time.sleep(2.0 * (attempt + 1))
                    continue
                response.raise_for_status()
                payload = response.json()
                cache_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
                return payload
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                time.sleep(1.5 * (attempt + 1))
        raise RuntimeError(f"OpenAlex request failed after {retries} attempts: {last_error}")

    # ---------- queries ----------
    def search(self, query: str, *, limit: int = 25, year_from: int | None = None,
               language: str | None = None) -> list[LiteratureWork]:
        filters = []
        if year_from:
            filters.append(f"from_publication_date:{year_from}-01-01")
        if language:
            filters.append(f"language:{language}")
        params = {
            "search": query,
            "per-page": min(max(limit, 1), 200),
            "mailto": self.contact_email,
            "select": "id,doi,title,publication_year,primary_location,authorships,"
                      "cited_by_count,type,open_access,abstract_inverted_index,concepts",
        }
        if filters:
            params["filter"] = ",".join(filters)
        url = f"{OPENALEX_BASE}?{urlencode(params)}"
        payload = self._get(url)
        results: list[LiteratureWork] = []
        for item in payload.get("results") or []:
            venue = ((item.get("primary_location") or {}).get("source") or {}).get("display_name")
            authors = [
                ((a.get("author") or {}).get("display_name") or "")
                for a in (item.get("authorships") or [])[:8]
            ]
            results.append(LiteratureWork(
                work_id=str(item.get("id") or ""),
                title=str(item.get("title") or "").strip(),
                year=item.get("publication_year"),
                doi=item.get("doi"),
                venue=venue,
                authors=[a for a in authors if a],
                cited_by_count=int(item.get("cited_by_count") or 0),
                type=item.get("type"),
                open_access_url=((item.get("open_access") or {}).get("oa_url")),
                abstract=_reconstruct_abstract(item.get("abstract_inverted_index")),
                concepts=[(c or {}).get("display_name") for c in (item.get("concepts") or [])[:6]
                          if (c or {}).get("display_name")],
                url=url,
                query=query,
            ))
        return results

    def search_many(self, queries: list[str], *, limit_each: int = 20,
                    year_from: int | None = None) -> list[LiteratureWork]:
        seen: set[str] = set()
        out: list[LiteratureWork] = []
        for query in queries:
            for work in self.search(query, limit=limit_each, year_from=year_from):
                if work.work_id in seen or not work.title:
                    continue
                seen.add(work.work_id)
                out.append(work)
        out.sort(key=lambda w: (-w.cited_by_count, -(w.year or 0)))
        return out


DEFAULT_QUERIES = [
    "talent supply and demand matching higher education",
    "graduate employability skills gap curriculum",
    "artificial intelligence workforce skills demand",
    "labor market signaling university curriculum reform",
    "高校 人才 供需 适配",
]


def fetch_literature(queries: list[str] | None = None, *, limit_each: int = 20,
                     year_from: int = 2015, settings: Settings | None = None) -> dict[str, Any]:
    client = OpenAlexClient(settings)
    works = client.search_many(queries or DEFAULT_QUERIES, limit_each=limit_each, year_from=year_from)
    out_dir = (settings or load_settings()).processed_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "source": "openalex",
        "robots": {"api.openalex.org": "User-agent: * / Allow: /"},
        "retrieval_time": datetime.now(timezone.utc).isoformat(),
        "queries": queries or DEFAULT_QUERIES,
        "n_works": len(works),
        "works": [w.to_dict() for w in works],
        "audit": client.audit,
    }
    (out_dir / "literature.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                                             encoding="utf-8")
    return payload

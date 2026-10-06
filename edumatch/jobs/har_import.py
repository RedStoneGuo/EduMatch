"""Import job postings from user-captured HAR files.

Why HAR instead of a live crawler: the target site's robots.txt
(``www.zhaopin.com`` and ``xiaoyuan.zhaopin.com``) disallows ``/*?*`` and
``*/api/*`` for ``User-agent: *``, i.e. automated API access with query strings
is not permitted. The HAR files were captured by the user's own browser, so
re-using them needs no crawling and raises no access-control question.

Security: session tokens (``at`` / ``rt`` / cookies) present in the HAR are
**never** copied into the dataset or the database.

Run:  python scripts/import_har_jobs.py
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .normalize import normalize_job

SENSITIVE_KEYS = {"at", "rt", "token", "cookie", "authorization", "displayPhoneNumber", "alreadyCallPhone"}


@dataclass
class HarJobSet:
    dataset_id: str
    har_file: str
    search_keyword: str | None
    city_code: str | None
    reported_count: int | None
    page_responses: int
    raw_rows: int = 0
    records: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "har_file": self.har_file,
            "search_keyword": self.search_keyword,
            "city_code": self.city_code,
            "reported_count": self.reported_count,
            "page_responses": self.page_responses,
            "raw_rows": self.raw_rows,
            "n_records": len(self.records),
            "notes": self.notes,
        }


def _safe(value: Any) -> Any:
    return value


def _salary_range(job: dict[str, Any]) -> tuple[str, str]:
    base = ((job.get("jobDetailData") or {}).get("position") or {}).get("base") or {}
    raw = job.get("salaryReal") or job.get("salary60") or ""
    if not raw:
        lo, hi = base.get("minSalary") or "", base.get("maxSalary") or ""
        raw = f"{lo}-{hi}" if lo or hi else ""
    return str(raw), json.dumps(base, ensure_ascii=False) if base else ""


def _description(job: dict[str, Any]) -> str:
    position = (job.get("jobDetailData") or {}).get("position") or {}
    desc = position.get("desc") or {}
    text = desc.get("description") or ""
    if not text:
        text = job.get("jobSummary") or ""
    return str(text)


def _reference_url(job: dict[str, Any]) -> str | None:
    for key in ("positionUrl", "positionURL", "redirectUrl", "companyUrl"):
        value = job.get(key)
        if value:
            return str(value)
    return None


def job_to_record(job: dict[str, Any], *, dataset_id: str, har_file: str, keyword: str | None,
                  capture_time: str, captured_url: str | None, city_code: str | None) -> dict[str, Any]:
    salary_raw, salary_detail = _salary_range(job)
    norm = normalize_job(
        str(job.get("companyName") or ""),
        str(job.get("name") or ""),
        str(job.get("workCity") or ""),
        salary_raw,
    )
    return {
        "job_id": f"{dataset_id}:{job.get('jobId')}",
        "company": job.get("companyName"),
        "position": job.get("name"),
        "industry": job.get("industryName"),
        "city": job.get("workCity"),
        "salary_min": norm.salary["min"],
        "salary_max": norm.salary["max"],
        "education": job.get("education"),
        "experience": job.get("workingExp"),
        "job_description": _description(job),
        "publish_time": job.get("publishTime") or job.get("firstPublishTime"),
        "source": f"har:{har_file}",
        "url": _reference_url(job),
        "crawl_time": capture_time,
        # normalised fields produced by the shared dedup/normalise layer
        "company_norm": norm.company_norm,
        "position_norm": norm.position_norm,
        "city_norm": norm.city_norm,
        "salary_bucket": norm.salary["bucket"],
        "fingerprint": norm.fingerprint,
        "content_key": norm.content_key,
        "is_duplicate": 0,
        # provenance additions (schema extended for HAR imports)
        "dataset_id": dataset_id,
        "search_keyword": keyword or "",
        "city_code": city_code or "",
        "work_type": job.get("workType"),
        "company_size": job.get("companySize"),
        "salary_detail": salary_detail,
        "source_job_id": str(job.get("jobId") or ""),
    }


def import_har(path: Path, *, dataset_id: str | None = None) -> HarJobSet:
    payload = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    entries = payload["log"]["entries"]
    derived_id = dataset_id or path.stem.replace(" ", "_")
    result = HarJobSet(dataset_id=derived_id, har_file=path.name,
                       search_keyword=None, city_code=None, reported_count=None, page_responses=0)
    seen_ids: set[str] = set()

    for entry in entries:
        request = entry.get("request") or {}
        url = request.get("url") or ""
        if "searchPositions" not in url:
            continue
        body_text = ((request.get("postData") or {}).get("text") or "").strip()
        body: dict[str, Any] = {}
        if body_text:
            try:
                body = json.loads(body_text)
            except json.JSONDecodeError:
                body = {}
        response_text = ((entry.get("response") or {}).get("content") or {}).get("text") or ""
        if not response_text:
            continue
        try:
            data = (json.loads(response_text).get("data") or {})
        except json.JSONDecodeError:
            continue
        postings = data.get("list") or []
        if not postings:
            continue

        result.page_responses += 1
        if body.get("S_SOU_FULL_INDEX"):
            result.search_keyword = str(body["S_SOU_FULL_INDEX"])
        if body.get("S_SOU_WORK_CITY"):
            result.city_code = str(body["S_SOU_WORK_CITY"])
        if isinstance(data.get("count"), int):
            result.reported_count = max(result.reported_count or 0, data["count"])
        capture_time = entry.get("startedDateTime") or ""
        for job in postings:
            result.raw_rows += 1
            source_id = str(job.get("jobId") or "")
            if not source_id or source_id in seen_ids:
                continue
            seen_ids.add(source_id)
            result.records.append(
                job_to_record(job, dataset_id=result.dataset_id, har_file=path.name,
                              keyword=result.search_keyword, capture_time=capture_time,
                              captured_url=url, city_code=result.city_code)
            )
    if result.reported_count is None:
        result.notes.append("响应未提供 count 字段，reported_count 记 null")
    result.notes.append("HAR 中的 at/rt/cookie 等会话凭据未写入数据集")
    result.notes.append("数据为个人浏览器抓包所得，仅用于本项目研究，不再对外分发原始请求头")
    return result


def import_many(paths: Iterable[Path]) -> list[HarJobSet]:
    return [import_har(p) for p in paths if p.exists()]


# Where the project looks for user-captured HAR files, in priority order.
HAR_SEARCH_DIRS = ("data/raw/har", "招聘数据", ".")
# Skip these when scanning the workspace so we never touch unrelated captures.
HAR_EXCLUDE = ("__pycache__", "node_modules", ".git", "flutter_application")


def find_har_files(workspace_root: Path | None = None, max_depth: int = 2) -> list[Path]:
    """Discover HAR captures anywhere in the standard locations.

    Canonical drop folder is ``edumatch_agent/data/raw/har/``; the workspace root
    and a ``招聘数据/`` folder are also scanned so a capture can be dropped
    wherever the researcher finds convenient.
    """
    project_root = Path(__file__).resolve().parents[2]
    workspace = workspace_root or project_root.parent
    found: dict[str, Path] = {}
    for relative in HAR_SEARCH_DIRS:
        base = (project_root / relative).resolve() if relative != "." else workspace
        if not base.exists():
            continue
        for path in sorted(base.rglob("*.har")):
            if any(part in HAR_EXCLUDE for part in path.parts):
                continue
            try:
                depth = len(path.relative_to(base).parts)
            except ValueError:
                continue
            if depth > max_depth:
                continue
            found.setdefault(path.name, path)
    return list(found.values())

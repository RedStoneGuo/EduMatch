"""Three-tier job counting: raw_count / deduplicated_count / effective_count."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from .normalize import normalize_job


def jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    union = a | b
    return len(a & b) / len(union) if union else 0.0


@dataclass
class DedupReport:
    raw_count: int = 0
    deduplicated_count: int = 0
    effective_count: int = 0
    duplicate_fingerprints: int = 0
    near_duplicate_groups: int = 0
    dropped_invalid: int = 0
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = dict(self.__dict__)
        data["dedup_ratio"] = round(1 - self.deduplicated_count / self.raw_count, 4) if self.raw_count else None
        data["effective_ratio"] = round(self.effective_count / self.raw_count, 4) if self.raw_count else None
        return data


def deduplicate_jobs(rows: Iterable[dict[str, Any]], near_dup_threshold: float = 0.9) -> tuple[list[dict], DedupReport]:
    """Collapse duplicate postings and produce an auditable count funnel.

    effective_count additionally drops postings that cannot support demand
    estimation: a row needs either a usable description or explicit skill tags.
    The description threshold is deliberately short (4 chars) because Chinese
    job text is information-dense - a 7-character sentence like "数据管道与治理"
    is enough to extract skills, while a 10-char gate silently discarded valid
    rows in the first version of this function.
    """
    report = DedupReport()
    seen: dict[str, dict] = {}
    content: dict[str, str] = {}
    groups: dict[str, list[str]] = {}
    kept: list[dict] = []
    for row in rows:
        report.raw_count += 1
        position = str(row.get("position") or "")
        company = str(row.get("company") or "")
        if not position.strip():
            report.dropped_invalid += 1
            continue
        norm = normalize_job(company, position, str(row.get("city") or ""), str(row.get("salary") or ""))
        fp = norm.fingerprint
        row = {
            **row,
            "company_norm": norm.company_norm,
            "position_norm": norm.position_norm,
            "city_norm": norm.city_norm,
            "salary_bucket": norm.salary["bucket"],
            "salary_min_norm": norm.salary["min"],
            "salary_max_norm": norm.salary["max"],
            "fingerprint": fp,
            "content_key": norm.content_key,
        }
        if fp in seen:
            report.duplicate_fingerprints += 1
            groups.setdefault(fp, [seen[fp].get("job_id", "?")]).append(row.get("job_id", "?"))
            continue
        seen[fp] = row
        content.setdefault(norm.content_key, fp)
        description = str(row.get("job_description") or "").strip()
        if len(description) < 4 and not row.get("skills"):
            report.dropped_invalid += 1
            continue
        kept.append(row)
    report.deduplicated_count = len(seen)
    report.effective_count = len(kept)
    report.near_duplicate_groups = len(groups)
    if report.dropped_invalid:
        report.notes.append(f"dropped {report.dropped_invalid} rows without usable position/description")
    report.notes.append("effective_count excludes rows that cannot support demand estimation")
    return kept, report

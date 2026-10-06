"""把「按专业导出的岗位表」并入既有岗位库（需求侧扩容）。

    python scripts/import_job_exports.py --dry-run
    python scripts/import_job_exports.py

数据源：``data/source/招聘数据/招聘原始表/`` 下的 ``_全部专业合并.csv|xlsx``
（全国按专业导出，含「专业名称 / 学科门类 / 来源检索词」列）。这些行作为
**专业作用域语料**并入 ``data/processed/jobs.json``：

* 新增字段 ``major_scope``（该行是为哪个专业检索导出的）与 ``discipline``；
* ``corpus="major_export"``，与原有人工智能/计算机语料并存但**互不干扰**——
  ``target_jobs()`` / ``baseline_jobs()`` 只看原语料，AI/计算机的既有结论不变；
* 分析某专业时优先用它的 ``major_scope`` 行作为需求语料（覆盖率闸门不再误杀）。

既有的 ``jobs.json`` 只增不改：同指纹（公司+岗位+城市+薪资区间）的行会被跳过。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from edumatch.jobs.normalize import normalize_job, parse_salary  # noqa: E402

EXPORT_DIR = ROOT / "data" / "source" / "招聘数据" / "招聘原始表"
JOBS = ROOT / "data" / "processed" / "jobs.json"
META = ROOT / "data" / "processed" / "jobs_meta.json"
CORPUS = "major_export"
SOURCE_LABEL = "export:全国按专业岗位导出"


def _read_rows(path: Path) -> list[dict[str, Any]]:
    import pandas as pd

    if path.suffix.lower() == ".csv":
        for encoding in ("utf-8-sig", "gbk", "utf-8"):
            try:
                return pd.read_csv(path, encoding=encoding, dtype=str).fillna("").to_dict("records")
            except UnicodeDecodeError:
                continue
        raise RuntimeError(f"无法解码 {path}")
    return pd.read_excel(path, dtype=str).fillna("").to_dict("records")


def _record(row: dict[str, Any], crawl_time: str) -> dict[str, Any] | None:
    position = str(row.get("岗位") or "").strip()
    company = str(row.get("招聘公司") or "").strip()
    if not position:
        return None
    salary_raw = str(row.get("薪资") or "")
    city = str(row.get("工作地点（省市）") or "")
    norm = normalize_job(company, position, city, salary_raw)
    salary = norm.salary
    return {
        "job_id": f"{CORPUS}:{row.get('编号')}",
        "company": company,
        "position": position,
        "industry": str(row.get("所属行业") or ""),
        "city": city,
        "salary_min": salary["min"],
        "salary_max": salary["max"],
        "education": str(row.get("要求学历") or ""),
        "experience": str(row.get("要求经验") or ""),
        "job_description": str(row.get("岗位职责") or ""),
        "publish_time": "",
        "source": SOURCE_LABEL,
        "url": "",
        "crawl_time": crawl_time,
        "company_norm": norm.company_norm,
        "position_norm": norm.position_norm,
        "city_norm": norm.city_norm,
        "salary_bucket": salary["bucket"],
        "salary_min_norm": salary["min"],
        "salary_max_norm": salary["max"],
        "fingerprint": norm.fingerprint,
        "content_key": norm.content_key,
        "is_duplicate": 0,
        "dataset_id": CORPUS,
        "search_keyword": "",
        "city_code": "",
        "work_type": "",
        "company_size": str(row.get("企业规模") or ""),
        "salary_detail": salary_raw,
        "source_job_id": str(row.get("编号") or ""),
        "skills": [],
        # 专业作用域字段（本次新增）
        "corpus": CORPUS,
        "major_scope": str(row.get("专业名称") or "").strip(),
        "discipline": str(row.get("学科门类") or "").strip(),
        "position_mapped": str(row.get("岗位-映射后") or ""),
        "position_type": str(row.get("岗位类型-映射后") or ""),
        "district": str(row.get("工作地点（区）") or ""),
        "source_keywords": str(row.get("来源检索词") or ""),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="并入按专业导出的岗位表")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--source", default=None, help="指定导出文件（默认自动找 _全部专业合并.*）")
    args = ap.parse_args(argv)

    if args.source:
        src = Path(args.source)
    else:
        csv_path = EXPORT_DIR / "_全部专业合并.csv"
        xlsx_path = EXPORT_DIR / "_全部专业合并.xlsx"
        src = csv_path if csv_path.exists() else xlsx_path
    if not src.exists():
        print(f"[error] 未找到按专业导出的岗位表：{src}")
        return 1

    rows = _read_rows(src)
    stamp = datetime.fromtimestamp(src.stat().st_mtime, tz=timezone.utc).isoformat()
    existing: list[dict[str, Any]] = []
    if JOBS.exists():
        existing = json.loads(JOBS.read_text(encoding="utf-8"))
    existing = [r for r in existing if r.get("corpus") != CORPUS]
    # 只把"已入库的既有语料"当作去重基准；本批内部的重复走"同岗位合并专业列表"
    pre_fp = {str(r.get("fingerprint") or "") for r in existing if r.get("fingerprint")}
    pre_id = {str(r.get("job_id") or "") for r in existing}

    added: list[dict[str, Any]] = []
    by_fp: dict[str, dict[str, Any]] = {}
    n_invalid = n_dupe = n_merged_scope = 0
    for row in rows:
        record = _record(row, stamp)
        if record is None:
            n_invalid += 1
            continue
        if record["job_id"] in pre_id or record["fingerprint"] in pre_fp:
            n_dupe += 1
            continue
        scope = record["major_scope"]
        # 同一条岗位可能同时属于多个专业（如建筑学 / 建筑环境与能源应用工程）
        # → 合并到一个记录的专业列表里，而不是把后来的专业丢掉
        twin = by_fp.get(record["fingerprint"])
        if twin is not None:
            if scope and scope not in twin["major_scopes"]:
                twin["major_scopes"].append(scope)
                twin["major_scope"] = "、".join(twin["major_scopes"])
                twin["source_keywords"] = "；".join(
                    s for s in (twin["source_keywords"], record["source_keywords"]) if s)
                n_merged_scope += 1
            n_dupe += 1
            continue
        record["major_scopes"] = [scope] if scope else []
        by_fp[record["fingerprint"]] = record
        added.append(record)

    majors = sorted({m for r in added for m in r.get("major_scopes") or []})
    summary = {
        "source": src.relative_to(ROOT).as_posix(),
        "raw_rows": len(rows),
        "added": len(added),
        "skipped_duplicate": n_dupe,
        "merged_cross_major": n_merged_scope,
        "skipped_invalid": n_invalid,
        "n_majors": len(majors),
        "majors": majors,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=1)[:2000])
    if args.dry_run:
        return 0

    merged = existing + added
    JOBS.write_text(json.dumps(merged, ensure_ascii=False, indent=1), encoding="utf-8")

    meta = json.loads(META.read_text(encoding="utf-8")) if META.exists() else {}
    sources = [s for s in (meta.get("sources") or []) if s.get("file") != src.name]
    sources.append({
        "file": src.name,
        "columns": list(rows[0].keys()) if rows else [],
        "raw_count": len(rows),
        "deduplicated_count": len(added),
        "effective_count": sum(1 for r in added if str(r.get("job_description") or "").strip()),
        "corpus": CORPUS,
        "major_scope_rows": len(added),
        "note": "按专业导出的专业作用域语料；不计入 target_jobs/baseline_jobs，AI/计算机既有口径不变",
    })
    legacy = [r for r in merged if r.get("corpus") != CORPUS]
    scoped = [r for r in merged if r.get("corpus") == CORPUS]
    meta.update({
        "sources": sources,
        "total_jobs": len(merged),
        "target_jobs": sum(1 for r in legacy if (r.get("search_keyword") or "").strip()),
        "baseline_jobs": sum(1 for r in legacy if not (r.get("search_keyword") or "").strip()),
        "major_scoped_jobs": len(scoped),
        "major_scoped_majors": len(majors),
        "counts": {
            **(meta.get("counts") or {}),
            "raw_count": int((meta.get("counts") or {}).get("raw_count") or 0) + len(rows),
            "deduplicated_count": len(merged),
            "effective_count": sum(1 for r in merged
                                   if str(r.get("job_description") or "").strip() or r.get("skills")),
            "note": ("raw=全部来源原始行数；deduplicated=跨源指纹去重后；"
                     "effective=含描述或技能、可用于需求估算的岗位数；"
                     "major_scoped=按专业导出的专业作用域语料，单独用于非 AI/CS 专业"),
        },
    })
    META.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[ok] jobs.json {len(existing)} → {len(merged)}；major_scope 语料 {len(scoped)} 条 / {len(majors)} 个专业")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

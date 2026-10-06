"""把 ``data/source/招聘数据`` 下的**全部岗位表**合并成需求端岗位库。

    python scripts\\merge_job_exports.py --dry-run      # 只统计，不写盘
    python scripts\\merge_job_exports.py                # 合并并写盘

为什么需要：需求端原先只吃进了两份旧 xlsx，后来补的
``全部招聘数据汇总.csv``（7 万行）与 ``招聘岗位数据_v2总表.csv``（21.8 万行）
**一行都没进模型**——报告里的"岗位语料 3.5 万条"其实漏掉了绝大部分。

输出（拆两个文件，避免每次分析都背几十万行）：

* ``data/processed/jobs.json``              —— 通用语料（AI/计算机关键词 + 同城基线 + HAR）
* ``data/processed/jobs_major_export.json`` —— **专业作用域**语料（带 `专业名称` 的导出行），
  由 `Dataset.major_export_jobs()` 首次用到时才加载
* ``data/processed/jobs_meta.json``         —— 三级计数 + 逐表统计（可复现）

口径：同一（公司+岗位+城市+薪资区间）跨表按指纹去重；`专业名称` 非空的行归入专业作用域，
空的行归入通用语料（并按来源表/检索词回填 `search_keyword`）。
简历表（``北京人工智能简历数据.xlsx``）**不是岗位表**，单独跳过并在 meta 里说明。
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from edumatch.jobs.normalize import normalize_job  # noqa: E402

SOURCE_DIR = ROOT / "data" / "source" / "招聘数据"
PROCESSED = ROOT / "data" / "processed"

#: 列名别名（两套导出表 + 旧 xlsx 的写法都要认）
ALIASES: dict[str, tuple[str, ...]] = {
    "job_id": ("编号", "id", "job_id"),
    "position": ("岗位", "岗位名称", "position"),
    "company": ("招聘公司", "公司", "公司名称", "company"),
    "city": ("工作地点（省市）", "工作地点(省市)", "城市", "city"),
    "education": ("要求学历", "学历", "education"),
    "experience": ("要求经验", "经验", "experience"),
    "industry": ("所属行业", "行业", "industry"),
    "description": ("岗位职责", "职位描述", "岗位描述", "job_description"),
    "salary": ("薪资", "薪水", "salary"),
    "major": ("专业名称", "major_scope"),
    "discipline": ("学科门类", "discipline"),
    "keywords": ("来源检索词", "检索词", "关键词", "search_keyword"),
    "source_table": ("来源表", "source_table"),
    "position_mapped": ("岗位-映射后",),
    "position_type": ("岗位类型-映射后",),
    "district": ("工作地点（区）",),
    "company_size": ("企业规模",),
}

#: 来源表名 → 通用语料的检索词（search_keyword 为空时回填，保证进 target_jobs()）
TABLE_KEYWORD = {"北京人工智能招聘数据": "人工智能", "北京计算机领域招聘数据": "计算机领域"}


def pick(row: dict[str, Any], key: str) -> str:
    for name in ALIASES[key]:
        value = row.get(name)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def iter_csv(path: Path) -> Iterator[dict[str, Any]]:
    for encoding in ("utf-8-sig", "utf-8", "gbk"):
        try:
            with path.open("r", encoding=encoding, errors="ignore", newline="") as fh:
                yield from csv.DictReader(fh)
            return
        except UnicodeDecodeError:
            continue


def iter_rows(path: Path) -> Iterator[dict[str, Any]]:
    if path.suffix.lower() == ".csv":
        yield from iter_csv(path)
        return
    import pandas as pd  # noqa: PLC0415

    frame = pd.read_excel(path, dtype=str).fillna("")
    yield from frame.to_dict("records")


def to_record(row: dict[str, Any], *, source_file: str, table: str,
              crawl_time: str) -> dict[str, Any] | None:
    position = pick(row, "position")
    if not position:
        return None
    company = pick(row, "company")
    city = pick(row, "city")
    salary_raw = pick(row, "salary")
    norm = normalize_job(company, position, city, salary_raw)
    salary = norm.salary
    major = pick(row, "major")
    corpus = "major_export" if major else "ai_cs"
    # 通用语料的 `search_keyword` **只从来源表推**：汇总表里的「来源检索词」列
    # 经常填的是行业名（船舶/半导体…），拿它当检索词会把 target/baseline 划分搞错
    # （实测 target 掉到 1.2 万、baseline 涨到 4 千，薪资基线被污染）。
    source_table = pick(row, "source_table") or table
    if major:
        keyword = pick(row, "keywords")
    else:
        keyword = TABLE_KEYWORD.get(source_table, "")
    return {
        "job_id": f"{corpus}:{pick(row, 'job_id') or abs(hash(norm.fingerprint)) % (10 ** 12)}",
        "company": company,
        "position": position,
        "industry": pick(row, "industry"),
        "city": city,
        "salary_min": salary["min"],
        "salary_max": salary["max"],
        "education": pick(row, "education"),
        "experience": pick(row, "experience"),
        "job_description": pick(row, "description"),
        "publish_time": "",
        "source": f"export:{source_file}",
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
        "dataset_id": corpus,
        "search_keyword": keyword,
        "city_code": "",
        "work_type": "",
        "company_size": pick(row, "company_size"),
        "salary_detail": salary_raw,
        "source_job_id": pick(row, "job_id"),
        "skills": [],
        "corpus": corpus,
        "major_scopes": [major] if major else [],
        "discipline": pick(row, "discipline"),
        "position_mapped": pick(row, "position_mapped"),
        "position_type": pick(row, "position_type"),
        "district": pick(row, "district"),
        "source_keywords": keyword,
        "source_table": source_table,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="合并 data/source/招聘数据 下的全部岗位表")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    files = sorted(p for p in SOURCE_DIR.glob("*")
                   if p.is_file() and p.suffix.lower() in {".csv", ".xlsx"})
    if not files:
        print(f"[warn] {SOURCE_DIR} 下没有 csv/xlsx")
        return 1
    crawl_time = datetime.now(timezone.utc).isoformat()
    tmp_general = PROCESSED / "_jobs_general.jsonl"
    tmp_major_dir = PROCESSED / "_major_tmp"
    PROCESSED.mkdir(parents=True, exist_ok=True)
    tmp_major_dir.mkdir(parents=True, exist_ok=True)
    seen: set[str] = set()
    per_file: list[dict[str, Any]] = []
    n_general = n_major = n_dup = 0
    skipped: list[dict[str, str]] = []
    # 同城基线样本：通用语料里"不带检索词"的行在旧包里只有 53 条（HAR 导入），
    # 这次合并后为 0——从专业作用域语料里蓄水池抽样一份**非 AI 岗位**做薪资基线，
    # 规模大得多，且口径会在报告里披露。
    import random  # noqa: PLC0415

    rng = random.Random(20261006)
    baseline_sample: list[dict[str, Any]] = []
    BASELINE_LIMIT = 20000

    major_handles: dict[str, Any] = {}
    with tmp_general.open("w", encoding="utf-8") as fg:
        for path in files:
            if path.name.startswith("_"):
                skipped.append({"file": path.name, "reason": "辅助统计表，不是岗位行"})
                continue
            if "简历" in path.name:
                skipped.append({"file": path.name,
                                "reason": "简历表：属微观求职侧基线，不是岗位需求表"})
                continue
            n_rows = n_ok = n_file_dup = 0
            for row in iter_rows(path):
                n_rows += 1
                record = to_record(row, source_file=path.name, table=path.stem,
                                   crawl_time=crawl_time)
                if record is None:
                    continue
                # 去重键必须带公司（fingerprint），否则不同公司的同名同薪岗位会被合并；
                # 专业作用域行再叠加专业名——同一个岗位在不同专业下各留一条，
                # 否则"按专业检索"的作用域信息会被去重抹掉。
                key = record["fingerprint"]
                if record["corpus"] == "major_export":
                    key += "|" + "、".join(record.get("major_scopes") or [])
                if key in seen:
                    n_dup += 1
                    n_file_dup += 1
                    continue
                seen.add(key)
                if record["corpus"] == "major_export":
                    # 专业作用域语料**按专业分文件**：分析某专业时只加载该专业的行，
                    # 不必为一次分析把 25 万行全读进内存。
                    for scope in (record.get("major_scopes") or ["未标注专业"]):
                        safe = "".join(ch if ch not in '\\/:*?"<>|' else "_" for ch in scope)
                        handle = major_handles.get(safe)
                        if handle is None:
                            handle = (tmp_major_dir / f"{safe}.jsonl").open("w", encoding="utf-8")
                            major_handles[safe] = handle
                        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
                    n_major += 1
                    if record.get("salary_min") or record.get("salary_max"):
                        if len(baseline_sample) < BASELINE_LIMIT:
                            baseline_sample.append(record)
                        else:
                            idx = rng.randrange(n_major)
                            if idx < BASELINE_LIMIT:
                                baseline_sample[idx] = record
                else:
                    fg.write(json.dumps(record, ensure_ascii=False) + "\n")
                    n_general += 1
                n_ok += 1
            per_file.append({"file": path.name, "rows": n_rows, "kept": n_ok,
                             "dup_or_invalid": n_rows - n_ok, "dup": n_file_dup})
    for handle in major_handles.values():
        handle.close()

    if args.dry_run:
        import shutil  # noqa: PLC0415

        print(json.dumps({"files": per_file, "general": n_general,
                          "major_export": n_major, "duplicates": n_dup,
                          "skipped": skipped}, ensure_ascii=False, indent=1))
        tmp_general.unlink(missing_ok=True)
        shutil.rmtree(tmp_major_dir, ignore_errors=True)
        return 0

    def dump(src: Path, dst: Path) -> int:
        # 注意：不能用 splitlines()——岗位描述里可能有 U+2028/U+2029，
        # 它们会被当成换行把一条记录劈成两半（实测 JSONDecodeError）。
        rows = [json.loads(line) for line in src.read_text(encoding="utf-8").split("\n") if line]
        dst.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
        src.unlink(missing_ok=True)
        return len(rows)

    n_general = dump(tmp_general, PROCESSED / "jobs.json")
    major_dir = PROCESSED / "major_jobs"
    major_dir.mkdir(parents=True, exist_ok=True)
    index: dict[str, int] = {}
    for src in sorted(tmp_major_dir.glob("*.jsonl")):
        rows = [json.loads(line) for line in src.read_text(encoding="utf-8").split("\n") if line]
        (major_dir / f"{src.stem}.json").write_text(
            json.dumps(rows, ensure_ascii=False), encoding="utf-8")
        index[src.stem] = len(rows)
        src.unlink(missing_ok=True)
    tmp_major_dir.rmdir()
    (major_dir / "_index.json").write_text(json.dumps(index, ensure_ascii=False, indent=1),
                                           encoding="utf-8")
    (PROCESSED / "jobs_baseline_sample.json").write_text(
        json.dumps(baseline_sample, ensure_ascii=False), encoding="utf-8")
    n_major = sum(index.values())
    meta = {
        "generated_at": crawl_time,
        "sources": per_file,
        "skipped": skipped,
        "counts": {
            "raw_count": sum(f["rows"] for f in per_file),
            "deduplicated_count": n_general + n_major,
            "effective_count": n_general + n_major,
            "general_count": n_general,
            "major_export_count": n_major,
            "major_export_files": len(index),
            "baseline_sample": len(baseline_sample),
            "duplicates_dropped": n_dup,
            "note": ("raw=各表原始行数合计；deduplicated=跨表指纹去重后；"
                     "general=通用语料（AI/计算机关键词+基线）；"
                     "major_export=按专业导出的专业作用域语料（惰性加载，按专业分文件）；"
                     "baseline_sample=同城薪资基线样本（merged 后通用语料无'不带关键词'的行，"
                     "从全量招聘表抽样 2 万条非 AI 岗位重建，口径已在报告披露）"),
        },
    }
    (PROCESSED / "jobs_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1),
                                              encoding="utf-8")
    print(json.dumps(meta["counts"], ensure_ascii=False, indent=1))
    for item in per_file:
        print(f"  {item['file']}: {item['rows']:,} 行 → 保留 {item['kept']:,}")
    for item in skipped:
        print(f"  [skip] {item['file']}: {item['reason']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

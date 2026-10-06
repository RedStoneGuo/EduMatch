"""专业作用域需求（本地全量语料兜底）。

背景：`data/processed/jobs.json` 只含 AI/计算机目标语料 + 68 个专业的按专业导出语料，
因此像「信息管理与信息系统」这类**既非 AI/CS、又不在那 68 个专业里**的专业，
需求侧会直接落到 `insufficient_evidence`，报告随之变薄。

本模块把本地**全量招聘语料**（`data/source/招聘数据/全部招聘数据汇总.csv`，72k+ 行）
变成可按专业关键词切片的兜底来源，规则固定、可复现、可披露：

    keywords = edumatch.majors.job_keywords(major)      # 词表来源一并记录
    命中判定 = 岗位 / 映射后岗位 / 关键词 字段命中任一关键词（**不看长篇职责**，避免"数据"泛滥命中）
    share   = 命中行数 / 全量行数，必须 ≥ 阈值才使用

命中结果标记 ``corpus="full_corpus_keyword_scope"``，并在 ``demand_coverage`` 里
记录语料、关键词、命中率与阈值，绝不与其他专业的需求向量混用。
"""

from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

FULL_CORPUS_REL = ("data", "source", "招聘数据", "全部招聘数据汇总.csv")
INDEX_REL = ("data", "processed", "full_corpus_index.json")

#: 兜底来源的最低要求：**以绝对命中量为主**，命中率下限只防止退化为噪声。
#: （注意：全量语料是全体岗位，某专业的命中率天然只有百分之几到十几，
#:  不能用 AI/计算机语料那套 30% 覆盖阈值来卡。）
MIN_SHARE = 0.05
MIN_MATCHED = 200
#: 进入需求计算的行数上限（保证单次分析可复现且不过慢）。
MAX_SCOPED_ROWS = 3000

_SALARY = re.compile(r"(\d+(?:\.\d+)?)\s*[-~至]\s*(\d+(?:\.\d+)?)\s*[kK]")
_SALARY_ONE = re.compile(r"(\d+(?:\.\d+)?)\s*[kK]")


@dataclass
class ScopedDemand:
    rows: list[dict[str, Any]]
    n_total: int
    n_matched: int
    share: float
    keywords: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {"n_total": self.n_total, "n_matched": self.n_matched,
                "share": round(self.share, 4), "keywords": self.keywords,
                "n_used": len(self.rows)}


def parse_salary(text: str) -> tuple[float | None, float | None]:
    """把「25-35K·14薪」「20K以上」解析成月薪区间（元）。"""
    raw = str(text or "")
    match = _SALARY.search(raw)
    if match:
        return float(match.group(1)) * 1000, float(match.group(2)) * 1000
    single = _SALARY_ONE.search(raw)
    if single:
        value = float(single.group(1)) * 1000
        return value, value
    return None, None


def build_full_corpus_index(project_root: Path, *, rebuild: bool = False) -> list[dict[str, Any]]:
    """读取全量招聘 CSV 并缓存为紧凑索引（首次约数秒，之后直接复用）。"""
    root = Path(project_root).resolve()
    cache = root.joinpath(*INDEX_REL)
    source = root.joinpath(*FULL_CORPUS_REL)
    # 公开发布包里**不带**那份 112 MB 的全量 CSV（超 GitHub 单文件上限），
    # 只带紧凑索引。所以源 CSV 不存在时必须直接复用索引，而不是去 stat 它。
    if cache.exists() and not rebuild:
        if not source.exists() or cache.stat().st_mtime >= source.stat().st_mtime:
            return json.loads(cache.read_text(encoding="utf-8"))
    rows: list[dict[str, Any]] = []
    if not source.exists():
        return rows
    with source.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            salary_min, salary_max = parse_salary(row.get("薪资") or "")
            rows.append({
                "position": (row.get("岗位") or "").strip(),
                "position_mapped": (row.get("岗位-映射后") or "").strip(),
                "job_type": (row.get("岗位类型-映射后") or "").strip(),
                "keywords": (row.get("关键词") or "").strip(),
                "job_description": (row.get("岗位职责") or "")[:600],
                "industry": (row.get("所属行业") or "").strip(),
                "education": (row.get("要求学历") or "").strip(),
                "experience": (row.get("要求经验") or "").strip(),
                "city": (row.get("工作地点（省市）") or "").strip(),
                "salary_min_norm": salary_min,
                "salary_max_norm": salary_max,
                "source": (row.get("来源表") or "").strip(),
            })
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    return rows


def scope_by_keywords(
    rows: Iterable[dict[str, Any]],
    keywords: Sequence[str],
    *,
    city: str | None = None,
    cap: int = MAX_SCOPED_ROWS,
) -> ScopedDemand:
    """按关键词切出该专业的岗位行（只看岗位/映射岗位/关键词字段）。"""
    words = [w for w in keywords if w]
    pool = list(rows)
    total = len(pool)
    matched: list[dict[str, Any]] = []
    for row in pool:
        if city and city not in str(row.get("city") or ""):
            continue
        # 只看岗位名（原始 + 映射后）：不把「关键词」元数据算进来，避免"数据"等泛词滥命中
        haystack = " ".join(str(row.get(k) or "") for k in
                            ("position", "position_mapped"))
        if any(w in haystack for w in words):
            matched.append(row)
    share = (len(matched) / total) if total else 0.0
    return ScopedDemand(rows=matched[:cap], n_total=total, n_matched=len(matched),
                        share=share, keywords=list(words))


def major_scoped_demand(
    project_root: Path,
    major: str,
    keywords: Sequence[str],
    *,
    city: str | None = "北京",
    min_share: float = MIN_SHARE,
    min_matched: int = MIN_MATCHED,
) -> ScopedDemand | None:
    """返回可用的专业作用域需求；不达标返回 None（调用方仍记证据不足）。"""
    rows = build_full_corpus_index(project_root)
    if not rows:
        return None
    scoped = scope_by_keywords(rows, keywords, city=city)
    if scoped.n_matched < min_matched or scoped.share < min_share:
        return None
    return scoped

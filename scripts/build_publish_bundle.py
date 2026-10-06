"""把 EduMatch 打包成「可上传 GitHub、下载即用」的发布包。

    python scripts\\build_publish_bundle.py                 # 输出到 ../_publish/EduMatch
    python scripts\\build_publish_bundle.py --out <目录> --baseline-rows 10000

为什么需要单独打包：完整包 5.5 GB，其中 6 个文件超过 GitHub 的 100 MB 单文件硬上限，
直接 `git init && push` 一定失败。本脚本只挑"跑得起来的最小充分集"：

第 1 层（必传）：代码/文档/模板 + 全库课程库 + 通用招聘语料 + 就业事实派生物
第 2 层（建议传）：紧凑版全量语料索引（任意专业兜底）+ 同城基线样本 + 政策文件 + reference

不传：原始 PDF（4.5 GB）、正文缓存全量、major_jobs 全量（577 MB）、简历表（隐私）。
被裁掉的部分写进 `DATA_MANIFEST.md`，并给出恢复全量的命令。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

CORE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CORE))

#: 顶层代码/文档：整目录复制
CODE_DIRS = ("agent", "analysis", "config", "demo", "docs", "edumatch", "evaluation",
             "mcp_servers", "ontology", "reference", "reporting", "scripts", "skills",
             "tests", "vendor")
CODE_FILES = ("analyze.ps1", "AGENTS.md", "README.md", "PROMPT.md", "交接文档.md",
              "requirements.txt", "LICENSE", "数据补采需求清单.csv", "数据补采需求清单.md",
              "数据补采需求清单_v2.csv", "数据补采需求清单_v2.md")

#: 根目录只留"运行入口 + Agent 规程 + 数据说明"，其余说明性/派生物归档到 docs/
ROOT_KEEP = ("README.md", "DATA_MANIFEST.md", "requirements.txt", "analyze.ps1",
             "AGENTS.md", "PROMPT.md", "LICENSE")
DOC_ARCHIVE = {
    "交接文档.md": "docs/HANDOVER.md",
    "README_dev.md": "docs/README_internal.md",
}

#: 明确剔除：与 data/source/政策文件 逐字节重复，且运行时不读取
PRUNE_AFTER_COPY = ("reference/archive/竞赛_知识库_学校资料",)

#: 运行残留：本机补采进度台账（会让新克隆误以为"已采过"而跳过补采）、向量缓存
RUNTIME_RESIDUE = ("data/harvest", "data/processed/semantic_cache")

#: 第 1 层数据：缺一就跑不出分析
LAYER1_DATA = (
    "data/raw/supplementary_courses.json",
    "data/raw/curriculum_template_ai.json",
    "data/raw/jobs_market_evidence.json",
    "data/raw/local_supply_index.json",
    "data/raw/majors_ai.txt",
    "data/raw/majors_cs.txt",
    "data/raw/majors_econ.txt",
    "data/processed/jobs.json",
    "data/processed/jobs_meta.json",
    "data/processed/pdf_facts.json",
    "data/processed/pdf_major_rows.json",
    "data/processed/literature.json",
    "data/processed/policies.json",
    # 注：crawl_request_v2.json 是补采清单的机读版（运行时不读），发布包已不再携带
)

#: 第 2 层：任意专业兜底 + 薪资基线 + 政策
LAYER2_TREES = ("data/source/采集台账",)

SKIP_NAMES = {"__pycache__", ".pytest_cache", ".git", "分析产物", ".mypy_cache", ".ruff_cache"}
DESC_MAX = 200          # 紧凑索引里岗位职责的截断长度（技能抽取够用，体积降到 ~1/3）


def copy_tree(src: Path, dst: Path) -> int:
    copied = 0
    for path in src.rglob("*"):
        rel = path.relative_to(src)
        if any(part in SKIP_NAMES for part in rel.parts):
            continue
        target = dst / rel
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        copied += 1
    return copied


def force_remove(path: Path) -> None:
    """删除目录，顺带处理只读文件（Windows 上 git 对象是只读的，否则删不掉）。"""
    import os
    import stat

    def _onexc(func, target, _exc):
        try:
            os.chmod(target, stat.S_IWRITE)
            func(target)
        except OSError:
            pass

    shutil.rmtree(path, onexc=_onexc)


def compact_index(src: Path, dst: Path) -> dict[str, int]:
    """把 101 MB 的全量语料索引压到可上传体积（截断职责文本）。"""
    rows = json.loads(src.read_text(encoding="utf-8"))
    out = []
    for row in rows:
        item = dict(row)
        desc = str(item.get("job_description") or "")
        if len(desc) > DESC_MAX:
            item["job_description"] = desc[:DESC_MAX]
        out.append(item)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    return {"rows": len(out), "mb": round(dst.stat().st_size / 1024 / 1024, 1)}


def sample_baseline(src: Path, dst: Path, rows: int) -> dict[str, int]:
    data = json.loads(src.read_text(encoding="utf-8"))
    kept = data[:rows] if len(data) > rows else data
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps(kept, ensure_ascii=False), encoding="utf-8")
    return {"rows": len(kept), "mb": round(dst.stat().st_size / 1024 / 1024, 1)}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


#: 发布版自称替换：`EduMatch` → `EduMatch`。只作用于文本文档与脚本，
#: **不碰 data/（数据里的路径/字段）与 vendor/（第三方插件）**。
RENAME_SUFFIXES = {".md", ".py", ".ps1", ".yaml", ".yml", ".txt", ".cfg"}
RENAME_SKIP_DIRS = {"data", "vendor", ".git"}


def rename_brand(out: Path) -> int:
    changed = 0
    for path in out.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in RENAME_SUFFIXES:
            continue
        rel = path.relative_to(out)
        if rel.parts and rel.parts[0] in RENAME_SKIP_DIRS:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if "EduMatch" not in text:
            continue
        path.write_text(text.replace("EduMatch", "EduMatch"), encoding="utf-8")
        changed += 1
    return changed


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="打包可上传的 EduMatch 发布包")
    ap.add_argument("--out", type=Path, default=CORE.parent / "_publish" / "EduMatch")
    ap.add_argument("--baseline-rows", type=int, default=10000)
    args = ap.parse_args(argv)
    out: Path = args.out
    if out.exists():
        force_remove(out)
    out.mkdir(parents=True)

    stats: dict[str, object] = {}
    # ① 代码 / 文档 / 模板
    for name in CODE_DIRS:
        src = CORE / name
        if src.exists():
            copy_tree(src, out / name)
    for name in CODE_FILES:
        src = CORE / name
        if src.exists():
            (out / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, out / name)
    # ② 第 1 层数据
    for rel in LAYER1_DATA:
        src = CORE / rel
        if src.exists():
            dst = out / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
    # ③ 第 2 层：紧凑索引 + 基线样本 + 政策
    idx_src = CORE / "data/processed/full_corpus_index.json"
    if idx_src.exists():
        stats["full_corpus_index"] = compact_index(
            idx_src, out / "data/processed/full_corpus_index.json")
    base_src = CORE / "data/processed/jobs_baseline_sample.json"
    if base_src.exists():
        stats["jobs_baseline_sample"] = sample_baseline(
            base_src, out / "data/processed/jobs_baseline_sample.json", args.baseline_rows)
    for tree in LAYER2_TREES:
        src = CORE / tree
        if src.exists():
            copy_tree(src, out / tree)
    # ④ 空目录占位（让"数据放回来"这条路径有明确落点）
    for rel in ("data/source/培养方案", "data/source/年度报告", "data/source/课程大纲",
                "data/source/专业介绍", "data/source/招聘数据", "data/source/政策文件",
                "data/processed/major_jobs"):
        keep = out / rel / "README.md"
        keep.parent.mkdir(parents=True, exist_ok=True)
        if not keep.exists():
            keep.write_text(
                "# 该目录在公开包中为空\n\n"
                "原始材料体积过大（合计约 4.5 GB）且含单文件 >100 MB，不适合放进 Git。\n"
                "把数据放回本目录后，按 `DATA_MANIFEST.md` 里的命令重建派生物即可恢复完整能力。\n",
                encoding="utf-8")
    # ⑤ 剔除逐字节重复、且运行时不读取的目录（政策文件在 data/source 已有一份）
    for rel in PRUNE_AFTER_COPY + RUNTIME_RESIDUE:
        stale = out / rel
        if stale.exists():
            force_remove(stale)
    # ⑥ 根目录只留运行入口 + 规程 + 数据说明；说明性/派生物归档到 docs/
    out_docs = out / "docs"
    out_docs.mkdir(parents=True, exist_ok=True)
    for src_name, dst_rel in DOC_ARCHIVE.items():
        src_path = CORE / src_name
        if not src_path.exists():
            src_path = CORE.parent / src_name          # v2 清单在包外一层
        if src_path.exists():
            dst = out / dst_rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_path, dst)
    for name in list(CODE_FILES):
        if name in ROOT_KEEP:
            continue
        stale = out / name
        if stale.exists() and stale.is_file():
            stale.unlink()
    # ⑦ 公开版 README 放仓库根；内部版改名保留在 docs/
    public_readme = CORE / "docs" / "PUBLIC_README.md"
    if public_readme.exists():
        internal = out / "README.md"
        if internal.exists():
            internal.rename(out_docs / "README_internal.md")
        shutil.copy2(public_readme, out / "README.md")
    (out / ".gitignore").write_text(GITIGNORE, encoding="utf-8")
    (out / "DATA_MANIFEST.md").write_text(manifest_text(stats), encoding="utf-8")
    # ⑧ 发布版名称去掉 "-Core" 后缀（放在最后，确保连自动生成的文档也覆盖到）：
    #    只改文本文档与脚本里的自称，**不碰 data/ 与 vendor/**
    renamed = rename_brand(out)
    checks = []
    for path in sorted(out.rglob("*")):
        if path.is_file() and path.name not in {"checksums.sha256"}:
            checks.append(f"{sha256(path)}  {path.relative_to(out).as_posix()}")
    (out_docs / "checksums.sha256").write_text("\n".join(checks) + "\n", encoding="utf-8")

    total = sum(p.stat().st_size for p in out.rglob("*") if p.is_file())
    biggest = max((p.stat().st_size for p in out.rglob("*") if p.is_file()), default=0)
    print(json.dumps({
        "out": str(out),
        "files": sum(1 for p in out.rglob("*") if p.is_file()),
        "total_mb": round(total / 1024 / 1024, 1),
        "largest_file_mb": round(biggest / 1024 / 1024, 1),
        "renamed_files": renamed,
        **stats,
    }, ensure_ascii=False, indent=1))
    return 0


GITIGNORE = """# 数据与产物：公开包只带"跑得起来的最小充分集"，其余见 DATA_MANIFEST.md
# 注意：必须写 data/source/*（只排除直接子项）。若写成 data/source/**，
# 父目录被排除后 `!.../**` 的否定规则不会生效，政策文件会被静默漏掉（实测踩过）。
data/source/*
# 只放行"数据占位说明"目录（各目录里只有 1 个 README.md，告诉使用者怎么把数据放回来）
!data/source/培养方案/
!data/source/年度报告/
!data/source/课程大纲/
!data/source/专业介绍/
!data/source/招聘数据/
!data/source/政策文件/
!data/source/采集台账/
data/raw/pdf_text/
data/harvest/收割/
data/harvest/
data/processed/semantic_cache/
data/processed/major_jobs/*.json
data/processed/_*.jsonl
data/processed/result.json

# 本地产物 / 缓存
分析产物/
__pycache__/
*.py[cod]
.pytest_cache/
.mypy_cache/
.ruff_cache/
.ipynb_checkpoints/
*.log

# 敏感与个人数据（绝不入库）
*.har
*.env
.env*
**/简历数据.xlsx
data/processed/case_reports/
"""


def manifest_text(stats: dict[str, object]) -> str:
    idx = stats.get("full_corpus_index") or {}
    base = stats.get("jobs_baseline_sample") or {}
    return f"""# 数据清单与恢复方式

本仓库是 **EduMatch** 的公开发布包：**代码、提示词、模板、以及"跑得起来的最小数据充分集"**。
原始材料（合计约 4.5 GB，其中 6 个文件超过 GitHub 的 100 MB 单文件上限）不在仓库内，
按下面说明放回即可恢复完整能力。

## 这个包里带了什么

| 内容 | 路径 | 说明 |
| --- | --- | --- |
| 全库课程库 | `data/raw/supplementary_courses.json` | 22 所院校 · 42,401 门可核查课程（培养方案解析结果） |
| 通用招聘语料 | `data/processed/jobs.json` | AI/计算机关键词岗位 16,387 条（需求主口径） |
| 就业事实 | `data/processed/pdf_facts.json` | 26 所院校的就业率/签约率/师资/实践学分等（来自就业与教学质量报告） |
| 分专业就业行 | `data/processed/pdf_major_rows.json` | 18 所院校 · 320 个专业的落实率/签约率/深造率 |
| 全量语料紧凑索引 | `data/processed/full_corpus_index.json` | {idx.get('rows', '—')} 行（{idx.get('mb', '—')} MB）——**任意专业**需求侧兜底 |
| 同城薪资基线样本 | `data/processed/jobs_baseline_sample.json` | {base.get('rows', '—')} 行（{base.get('mb', '—')} MB）——薪资溢价基线 |
| 政策库（预解析缓存） | `data/processed/policies.json` | 145 条政策记录（由 147 份政策原文预解析；政策—产业维度） |
| 采集台账 | `data/source/采集台账/` | 材料索引与采集记录 |

## 这个包里**没有**什么（以及为什么）

| 未包含 | 体积 | 原因 |
| --- | --- | --- |
| `data/source/培养方案|课程大纲|专业介绍|年度报告|政策文件`（原始文件） | 约 4.5 GB | 超仓库建议上限；含 6 个 >100 MB 的单文件（最大 443 MB），GitHub 直接拒绝。政策原文已预解析成 `policies.json`（147 个文件 → 1 个文件，运行时等价） |
| `data/raw/pdf_text/`（正文缓存） | 约 1.1 GB | 可由 PDF 重新抽取 |
| `data/processed/major_jobs/`（专业作用域岗位语料全量） | 577 MB | 已用紧凑索引覆盖"任意专业兜底"；如需精确专业语料可按命令重建 |
| `data/source/招聘数据/招聘岗位数据_v2总表.csv` 等原始表 | 436 MB | 超单文件上限 |
| `北京人工智能简历数据.xlsx` | 31 MB | **含真实个人履历，隐私原因不入公开仓库** |

## 恢复全量能力（把数据放回后按序执行）

```powershell
# 0) 把原始材料放回对应目录
#    data/source/培养方案/<院校>/、data/source/年度报告/<院校>/{{就业质量报告,教学质量报告}}/
#    data/source/招聘数据/*.csv|xlsx

python scripts\\import_extra_text.py                                # PDF/docx → 正文缓存
python scripts\\import_supplementary.py --all --force --max-mb 80   # 培养方案 → 课程库
python scripts\\reextract_pdf_facts.py                              # 正文 → 就业/教学事实
python scripts\\extract_pdf_major_rows.py                           # 就业报告 → 分专业就业行
python scripts\\merge_job_exports.py                                # 全部岗位表 → 需求端语料
python scripts\\relativize_paths.py                                 # 派生件路径改回相对路径
python scripts\\audit_data_coverage.py                              # 复核材料利用率
```

## 数据来源与口径

* 教育侧：各校官方《本科培养方案》《毕业生就业质量报告》《本科教学质量报告》《课程大纲》《专业介绍》；
* 需求侧：公开招聘平台岗位导出表（含岗位名、公司、城市、学历、经验、薪资、职责、行业）；
* 缺失一律记 `null` 并在报告中标注「未获取」，**不补位、不估算、不用其它专业/院校的数据顶替**。
"""


if __name__ == "__main__":
    raise SystemExit(main())

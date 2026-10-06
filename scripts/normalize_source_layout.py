"""把 ``data/source`` 重新梳理成「数据类型 → 院校」的规范结构（幂等、可回滚）。

    python scripts/normalize_source_layout.py --dry-run   # 只打印迁移计划
    python scripts/normalize_source_layout.py             # 执行迁移
    python scripts/normalize_source_layout.py --check     # 校验是否已规范（0=已规范）

迁移只动 ``data/source`` 内部文件；同盘移动走 rename（不复制）；与既有文件重名的
移入 ``非分析归档/_重复件/`` 而不是丢弃。迁移结果写成两份可追溯产物：

* ``data/processed/source_layout_map.json``    旧路径 → 新路径（逐条，可据此回滚）
* ``data/processed/source_layout_report.json`` 统计与告警

随后同步重写结构化产物里的来源路径（``pdf_facts.json`` / ``pdf_major_rows.json`` /
``pdf_index.json``），保证"结论 → 证据 → 原始文件"的链条在迁移后仍然可解析。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data" / "source"
PROCESSED = ROOT / "data" / "processed"
MAP_PATH = PROCESSED / "source_layout_map.json"
REPORT_PATH = PROCESSED / "source_layout_report.json"
DUPLICATE_DIR = SOURCE / "非分析归档" / "_重复件"

#: 半角括号 / 简写 → 全角括号的院校规范名（覆盖归档里出现过的写法）
SCHOOL_ALIASES = {
    "中国地质大学(北京)": "中国地质大学（北京）",
    "中国矿业大学(北京)": "中国矿业大学（北京）",
    "中国石油大学(北京)": "中国石油大学（北京）",
}

#: 报告类材料判型规则（关键词按先后顺序匹配）
REPORT_KINDS = [
    ("就业质量", "就业质量报告"),
    ("毕业生就业", "就业质量报告"),
    ("就业创业", "就业质量报告"),
    ("研究生教育发展质量", "教学质量报告"),
    ("教学质量", "教学质量报告"),
    ("本科教学", "教学质量报告"),
]


def canonical_school(name: str) -> str:
    return SCHOOL_ALIASES.get((name or "").strip(), (name or "").strip())


def classify_report(filename: str) -> str:
    for keyword, kind in REPORT_KINDS:
        if keyword in filename:
            return kind
    return "其他报告"


def sha1_of(path: Path) -> str:
    digest = hashlib.sha1()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _rel(path: Path) -> str:
    return path.relative_to(SOURCE).as_posix()


def plan_moves() -> list[tuple[Path, Path]]:
    """返回 (源文件, 目标文件) 列表；只规划，不动盘。"""
    moves: list[tuple[Path, Path]] = []

    def add(src: Path, dst: Path) -> None:
        if src.is_file():
            moves.append((src, dst))

    def add_tree(src: Path, dst: Path, *, strip: int = 0) -> None:
        if not src.exists():
            return
        for p in src.rglob("*"):
            if p.is_file():
                rel = p.relative_to(src)
                add(p, dst.joinpath(*rel.parts[strip:]))

    # ---- 1) 招聘原始表 → 招聘数据 ----
    add_tree(SOURCE / "招聘原始表", SOURCE / "招聘数据")

    # ---- 2) 文献：检索缓存 / TSI 指标构建文献 ----
    add_tree(SOURCE / "文献缓存", SOURCE / "文献" / "检索缓存")
    add_tree(SOURCE / "TSI指标构建文献", SOURCE / "文献" / "TSI指标构建文献")

    archive = SOURCE / "归档原文"
    knowledge = archive / "竞赛_知识库_学校资料"
    # ---- 3) 归档原文：就业质量报告 → 年度报告/<校>/就业质量报告 ----
    emp_city = knowledge / "就业质量报告" / "北京市27所211院校"
    if emp_city.exists():
        for p in emp_city.rglob("*"):
            if p.is_file():
                rel = p.relative_to(emp_city)
                add(p, SOURCE / "年度报告" / canonical_school(rel.parts[0]) /
                    "就业质量报告" / Path(*rel.parts[1:]))
    emp = knowledge / "就业质量报告"
    if emp.exists():
        for p in emp.rglob("*"):
            if not p.is_file():
                continue
            rel = p.relative_to(emp)
            if rel.parts[0] == "北京市27所211院校":
                continue
            if rel.parts[0] == "2025年中国本科生就业报告":
                add(p, SOURCE / "年度报告" / "行业与全国报告" / Path(*rel.parts))
            elif rel.parts[0] == "北京地区高校毕业生就业质量年度报告":
                add(p, SOURCE / "年度报告" / "区域报告" / Path(*rel.parts))
            else:
                add(p, SOURCE / "年度报告" / "其他" / "就业质量报告" / Path(*rel.parts))

    # ---- 4) 归档原文：教学质量报告 → 年度报告/<校>/教学质量报告 ----
    qual_city = knowledge / "教学质量报告" / "本科教学质量报告" / "北京211院校"
    if qual_city.exists():
        for p in qual_city.rglob("*"):
            if p.is_file():
                rel = p.relative_to(qual_city)
                add(p, SOURCE / "年度报告" / canonical_school(rel.parts[0]) /
                    "教学质量报告" / Path(*rel.parts[1:]))
    qual = knowledge / "教学质量报告"
    if qual.exists():
        for p in qual.rglob("*"):
            if not p.is_file():
                continue
            rel = p.relative_to(qual)
            if len(rel.parts) >= 3 and rel.parts[0] == "本科教学质量报告" and rel.parts[1] == "北京211院校":
                continue
            add(p, SOURCE / "年度报告" / "其他" / "教学质量报告" / Path(*rel.parts))

    # ---- 5) 政策文件 / 改进建议文献 / 归档内 TSI 文献 ----
    add_tree(knowledge / "政策文件", SOURCE / "政策文件")
    add_tree(knowledge / "改进建议文献", SOURCE / "文献" / "改进建议文献")
    add_tree(archive / "TSI指标构建文献", SOURCE / "文献" / "TSI指标构建文献")

    # ---- 6) 非分析材料：过程记录 / 校赛 / 历史数据 / 赛题与提示词 ----
    add_tree(archive / "输出过程记录", SOURCE / "非分析归档" / "输出过程记录")
    for name in ("校赛", "Agent竞赛_历史数据"):
        add_tree(archive / name, SOURCE / "非分析归档" / name)
    if archive.exists():
        for p in archive.iterdir():
            if p.is_file():
                add(p, SOURCE / "非分析归档" / "赛题与提示词" / p.name)

    # ---- 7) 补采根目录：院校级报告按其类型归入年度报告 ----
    supplement = SOURCE / "补采根目录"
    if supplement.exists():
        for school_dir in supplement.iterdir():
            if not school_dir.is_dir():
                continue
            for p in school_dir.rglob("*"):
                if p.is_file():
                    add(p, SOURCE / "年度报告" / canonical_school(school_dir.name) /
                        classify_report(p.name) / p.name)
    return moves


def _unique_target(dst: Path, taken: set[str]) -> Path:
    if str(dst).lower() not in taken:
        return dst
    for i in range(2, 1000):
        cand = dst.with_name(f"{dst.stem}_dup{i}{dst.suffix}")
        if str(cand).lower() not in taken:
            return cand
    raise RuntimeError(f"无法为 {dst} 生成唯一文件名")


def apply_moves(moves: list[tuple[Path, Path]], *, dry_run: bool) -> list[dict[str, str]]:
    mapping: list[dict[str, str]] = []
    taken = {str(p.resolve()).lower() for p in SOURCE.rglob("*") if p.is_file()}
    for src, dst in moves:
        if not src.exists():
            continue
        if src.resolve() == dst.resolve():
            taken.discard(str(src.resolve()).lower())
            continue
        target = _unique_target(dst, taken)
        if dry_run:
            mapping.append({"from": _rel(src), "to": _rel(target), "status": "dry_run"})
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(target))
        taken.discard(str(src.resolve()).lower())
        taken.add(str(target.resolve()).lower())
        mapping.append({"from": _rel(src), "to": _rel(target), "status": "moved"})
    return mapping


def dedup_by_sha1(*, dry_run: bool) -> list[dict[str, str]]:
    """同盘逐字节去重：内容重复的文件移入 非分析归档/_重复件/，保留首次出现。"""
    referenced = collect_referenced_source_paths()
    seen: dict[str, Path] = {}
    moved: list[dict[str, str]] = []
    roots = [SOURCE / name for name in ("培养方案", "课程大纲", "专业介绍", "年度报告",
                                        "政策文件", "文献", "招聘数据", "补采说明")]
    for root in roots:
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            digest = sha1_of(path)
            first = seen.get(digest)
            if first is None:
                seen[digest] = path
                continue
            rel_first = f"data/source/{_rel(first)}"
            rel_now = f"data/source/{_rel(path)}"
            # 被结构化产物引用的那份必须留下，否则证据链会断
            if rel_first in referenced and rel_now in referenced:
                continue
            if rel_now in referenced and rel_first not in referenced:
                seen[digest] = path
                first, path = path, first
                rel_first, rel_now = rel_now, rel_first
            target = DUPLICATE_DIR / digest[:10] / path.name
            if target.exists():
                target = target.with_name(f"{digest[:10]}_{path.name}")
            if not dry_run:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(path), str(target))
            moved.append({"duplicate": _rel(path), "kept": _rel(first), "moved_to": _rel(target)})
    return moved


def collect_referenced_source_paths() -> set[str]:
    """结构化产物里出现过的 ``data/source/...`` 路径（去重前用于保护证据链）。"""
    referenced: set[str] = set()
    for filename, fields in (("pdf_facts.json", ("source_document",)),
                             ("pdf_major_rows.json", ("source_document",)),
                             ("pdf_index.json", ("path",))):
        path = PROCESSED / filename
        if not path.exists():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))

        def walk(obj) -> None:
            if isinstance(obj, dict):
                for key, value in obj.items():
                    if key in fields and isinstance(value, str) and value.startswith("data/source/"):
                        referenced.add(value)
                    else:
                        walk(value)
            elif isinstance(obj, list):
                for item in obj:
                    walk(item)

        walk(payload)
    return referenced


def rewrite_references(mapping: list[dict[str, str]]) -> dict[str, int]:
    """把结构化产物里的 ``data/source/...`` 来源路径改写成迁移后的新路径。"""
    table = {f"data/source/{m['from']}": f"data/source/{m['to']}" for m in mapping
             if m.get("status") == "moved"}
    touched: Counter[str] = Counter()
    targets = {
        "pdf_facts.json": ("source_document",),
        "pdf_major_rows.json": ("source_document",),
        "pdf_index.json": ("path",),
    }

    def walk(obj, fields: tuple[str, ...], filename: str) -> None:
        if isinstance(obj, dict):
            for key, value in list(obj.items()):
                if key in fields and isinstance(value, str):
                    for old, new in table.items():
                        if old in value:
                            obj[key] = value.replace(old, new)
                            touched[filename] += 1
                            break
                else:
                    walk(value, fields, filename)
        elif isinstance(obj, list):
            for item in obj:
                walk(item, fields, filename)

    for filename, fields in targets.items():
        path = PROCESSED / filename
        if not path.exists():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        walk(payload, fields, filename)
        if touched[filename]:
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    stale = PROCESSED / "archive_documents.json"
    if stale.exists():
        stale.rename(PROCESSED / "archive_documents.legacy.json")
    return dict(touched)


def is_normalized() -> bool:
    legacy = ("归档原文", "招聘原始表", "TSI指标构建文献", "文献缓存", "补采根目录")
    if any((SOURCE / name).exists() for name in legacy):
        return False
    return all((SOURCE / name).exists() for name in ("培养方案", "年度报告", "政策文件", "文献"))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="规范化 data/source 目录结构")
    ap.add_argument("--dry-run", action="store_true", help="只打印计划")
    ap.add_argument("--check", action="store_true", help="只校验是否已规范")
    ap.add_argument("--no-dedup", action="store_true", help="跳过逐字节去重")
    args = ap.parse_args(argv)

    if args.check:
        ok = is_normalized()
        print("已规范" if ok else "未规范：仍存在 归档原文/招聘原始表/TSI指标构建文献 等旧目录根")
        return 0 if ok else 1

    moves = plan_moves()
    mapping = apply_moves(moves, dry_run=args.dry_run)
    # 先重写引用，再按 sha1 去重，这样"被引用的那一份必须保留"判定才生效
    rewrites = {} if args.dry_run else rewrite_references(mapping)
    duplicates = [] if (args.no_dedup or args.dry_run) else dedup_by_sha1(dry_run=args.dry_run)

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dry_run": args.dry_run,
        "n_planned": len(moves),
        "n_moved": sum(1 for m in mapping if m["status"] == "moved"),
        "n_duplicates_relocated": len(duplicates),
        "reference_rewrites": rewrites,
        "by_target_top": dict(Counter(m["to"].split("/")[0] for m in mapping)),
    }
    if not args.dry_run:
        PROCESSED.mkdir(parents=True, exist_ok=True)
        MAP_PATH.write_text(json.dumps(mapping, ensure_ascii=False, indent=1), encoding="utf-8")
        REPORT_PATH.write_text(
            json.dumps({**summary, "duplicates": duplicates}, ensure_ascii=False, indent=1),
            encoding="utf-8",
        )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if not args.dry_run and duplicates:
        print(f"[note] {len(duplicates)} 份重复件已移入 "
              f"{DUPLICATE_DIR.relative_to(ROOT).as_posix()}（未删除，可人工复核）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

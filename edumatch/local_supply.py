"""本地教育供给数据层：把 ``data/source`` 的全部材料登记成可检索、可追溯的索引。

``data/source`` 的规范结构是「数据类型 → 院校」：

* ``培养方案/<院校>/*.pdf``          —— 课程体系/学分/学时（A 级，已解析成课程库）
* ``课程大纲/<院校>/**/*.pdf``       —— 单课/院系大纲（A 级，正文可检索）
* ``专业介绍/<院校>/*.pdf``          —— 专业目录与介绍（A 级，正文可检索）
* ``年度报告/<院校>/就业质量报告``   —— 就业结果事实（A 级，见 pdf_facts/pdf_major_rows）
* ``年度报告/<院校>/教学质量报告``   —— 师资/条件/教学事实（A 级）
* ``政策文件/*.pdf``                 —— 政策原文（A 级，见 policies）
* ``招聘数据/*.xlsx``                —— 需求侧一手表（见 jobs.json）
* ``文献/**``                        —— 方法论文献与检索缓存（D 级）
* ``采集台账/**``                    —— 采集清单与链接台账（人工核对）
* ``归档文本缓存/**``                —— 归档 PDF 的逐页正文缓存（按 sha1 命名）
* ``非分析归档/**``                  —— 竞赛/历史/重复件等，明确不进分析

模块提供两件事：

1. **清洗**：把结构化产物里的院校名归一（半角括号、"中国矿业大学"→
   "中国矿业大学（北京）"），并从来源路径回填缺失的 ``school`` 字段；
2. **索引**：扫描 ``data/source``，逐份文件登记「材料类型 / 院校 / 专业 / 年份 /
   关联的结构化产物或正文缓存」，写 ``data/processed/source_inventory.json`` 与
   ``data/raw/local_supply_index.json``，供模型按院校/专业/材料类型定点调用。
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[1]

#: 规范的材料类型目录（一级目录名）
MATERIAL_TYPES: tuple[str, ...] = (
    "培养方案", "课程大纲", "专业介绍", "年度报告", "政策文件",
    "招聘数据", "文献", "采集台账",
)

#: 派生/辅助目录（不是一手材料，但仍在 data/source 内）
DERIVED_TYPES: tuple[str, ...] = ("归档文本缓存", "非分析归档")

#: 年度报告的三个子类型
REPORT_KINDS: tuple[str, ...] = ("就业质量报告", "教学质量报告")

#: 院校名别名 → 规范名
SCHOOL_ALIASES: dict[str, str] = {
    "中国地质大学(北京)": "中国地质大学（北京）",
    "中国矿业大学(北京)": "中国矿业大学（北京）",
    "中国石油大学(北京)": "中国石油大学（北京）",
    # 报告里被截断的写法（PDF 抽取丢失括号内容）
    "中国地质大学": "中国地质大学（北京）",
    "中国矿业大学": "中国矿业大学（北京）",
    "中国石油大学": "中国石油大学（北京）",
}

#: 无院校归属的年度报告子目录（区域/全国/其他）
NON_SCHOOL_REPORT_DIRS: tuple[str, ...] = ("区域报告", "行业与全国报告", "其他")

#: 报告文件名里的"非专业"片段（防止把报告名当成专业）
_REPORT_NAME_HINTS = ("就业质量", "教学质量", "毕业生", "就业创业", "本科教学", "研究生教育发展质量")


def canonical_school(name: str | None) -> str:
    """院校名归一：去空白、半角括号转全角、补全被截断的"（北京）"。"""
    text = str(name or "").strip()
    if not text:
        return ""
    if text in SCHOOL_ALIASES:
        return SCHOOL_ALIASES[text]
    return text


def known_schools(source_root: Path) -> list[str]:
    """从 ``data/source`` 的实际目录结构发现规范院校名单（年度报告 + 培养方案）。"""
    names: set[str] = set()
    for top in ("年度报告", "培养方案", "课程大纲", "专业介绍"):
        base = source_root / top
        if not base.exists():
            continue
        for child in base.iterdir():
            if child.is_dir() and child.name not in NON_SCHOOL_REPORT_DIRS:
                names.add(canonical_school(child.name))
    return sorted(n for n in names if n)


def infer_school_from_path(rel_path: str | Path, schools: Iterable[str]) -> str:
    """从相对路径的任一层目录名/文件名里识别院校；识别不到返回空串。"""
    text = str(rel_path).replace("\\", "/")
    for school in sorted(schools, key=len, reverse=True):
        if school and (school in text or school.replace("（", "(").replace("）", ")") in text):
            return school
    return ""


_YEAR_RE = re.compile(r"(19|20)\d{2}")


def parse_year(text: str) -> int | None:
    """从文件名里取第一个 4 位年份（1900–2099）；取不到返回 None。"""
    for match in _YEAR_RE.finditer(str(text or "")):
        year = int(match.group(0))
        if 1900 <= year <= 2099:
            return year
    return None


def parse_major(stem: str) -> str:
    """从 ``<年份>_<专业>.pdf`` 形态的文件名里取专业名；不匹配返回空串。"""
    parts = str(stem or "").split("_", 1)
    if len(parts) == 2 and parts[0].strip().isdigit():
        return parts[1].strip()
    return ""


def classify(rel_path: str | Path) -> tuple[str, str]:
    """返回 (材料类型, 子类型)；无法归类返回 ("未分类", "")。"""
    parts = Path(str(rel_path).replace("\\", "/")).parts
    if not parts:
        return "未分类", ""
    top = parts[0]
    if top == "年度报告":
        kind = ""
        for part in parts[1:]:
            if part in REPORT_KINDS:
                kind = part
                break
            if part in NON_SCHOOL_REPORT_DIRS:
                kind = "区域与全国报告"
                break
        return "年度报告", kind or "其他报告"
    if top == "文献":
        return "文献", parts[1] if len(parts) > 1 else ""
    if top in MATERIAL_TYPES or top in DERIVED_TYPES:
        return top, ""
    return "未分类", ""

@dataclass
class Material:
    """data/source 里的一份材料（或一份派生缓存）。"""

    rel_path: str
    material_type: str
    subtype: str
    school: str
    major: str
    year: int | None
    file_name: str
    suffix: str
    size_kb: float
    in_analysis: bool                      # 是否进入分析口径
    derived: list[str] = field(default_factory=list)   # 关联的结构化产物/正文缓存
    unparsed_reason: str = ""              # 进了分析口径但没抓到结构化数据时的如实说明

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_text_map(project_root: Path) -> tuple[dict[tuple[str, str], list[str]], dict[str, list[str]]]:
    """扫描 ``data/raw/pdf_text``，建 (院校, 文件主名) 与 文件主名 两级正文缓存索引。"""
    root = project_root / "data" / "raw" / "pdf_text"
    by_school: dict[tuple[str, str], list[str]] = defaultdict(list)
    by_stem: dict[str, list[str]] = defaultdict(list)
    if not root.exists():
        return {}, {}
    for path in root.rglob("*.txt"):
        rel = path.relative_to(project_root).as_posix()
        parts = Path(rel).relative_to("data/raw/pdf_text").parts
        school = canonical_school(parts[0]) if parts else ""
        by_school[(school, path.stem)].append(rel)
        by_stem[path.stem].append(rel)
    return dict(by_school), dict(by_stem)


def _text_cache_candidates(text_map: dict[tuple[str, str], list[str]], school: str, stem: str) -> list[str]:
    """该材料在 ``data/raw/pdf_text`` 下的正文缓存路径（存在才返回）。"""
    if not school:
        return []
    return list(text_map.get((canonical_school(school), stem), []))


def build_inventory(project_root: Path | None = None) -> list[Material]:
    """扫描 ``data/source`` 生成逐份材料清单（唯一入口，幂等）。"""
    root = (project_root or PROJECT_ROOT).resolve()
    source = root / "data" / "source"
    schools = known_schools(source) if source.exists() else []
    text_map, stem_map = build_text_map(root)
    records: list[Material] = []
    if not source.exists():
        return records
    for path in sorted(source.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(source).as_posix()
        if rel.startswith("README"):
            continue
        material_type, subtype = classify(rel)
        parts = Path(rel).parts
        school = ""
        if material_type == "年度报告":
            school = canonical_school(parts[1]) if len(parts) > 1 and parts[1] not in NON_SCHOOL_REPORT_DIRS else ""
            if not school:
                school = infer_school_from_path(rel, schools)
        elif material_type in {"培养方案", "课程大纲", "专业介绍"}:
            school = canonical_school(parts[1]) if len(parts) > 1 else ""
        else:
            school = infer_school_from_path(rel, schools)
        major = parse_major(path.stem) if material_type in {"培养方案", "专业介绍"} else ""
        year = parse_year(path.stem)
        in_analysis = material_type not in {"非分析归档", "未分类", "归档文本缓存", "采集台账"}
        derived = _text_cache_candidates(text_map, school, path.stem)
        # 文献/政策不属于某一所高校，按文件主名全局匹配正文缓存
        if not derived and material_type in {"文献", "政策文件"}:
            derived = list(stem_map.get(path.stem, []))
        records.append(Material(
            rel_path=f"data/source/{rel}",
            material_type=material_type,
            subtype=subtype,
            school=school,
            major=major,
            year=year,
            file_name=path.name,
            suffix=path.suffix.lower(),
            size_kb=round(path.stat().st_size / 1024, 1),
            in_analysis=in_analysis,
            derived=derived,
        ))
    return records


@dataclass
class LocalSupplyIndex:
    """本地供给数据索引：材料清单 + 每条材料挂到的结构化产物/正文缓存。"""

    project_root: Path
    records: list[Material] = field(default_factory=list)
    structured_links: dict[str, list[str]] = field(default_factory=dict)
    _by_school: dict[str, list[Material]] = field(default_factory=dict, repr=False)

    INDEX_PATH = "data/raw/local_supply_index.json"
    INVENTORY_PATH = "data/processed/source_inventory.json"

    def __post_init__(self) -> None:
        if not self._by_school:
            self._reindex()

    # ---------- construction ----------
    @classmethod
    def build(cls, project_root: Path | None = None) -> "LocalSupplyIndex":
        root = (project_root or PROJECT_ROOT).resolve()
        index = cls(project_root=root, records=build_inventory(root))
        index.structured_links = _collect_structured_links(root)
        index._annotate_unparsed()
        index._reindex()
        return index

    @classmethod
    def load(cls, project_root: Path | None = None) -> "LocalSupplyIndex":
        """优先读落盘索引；不存在或已过期（data/source 有增删改）时现场重建。"""
        root = (project_root or PROJECT_ROOT).resolve()
        path = root / cls.INDEX_PATH
        if not path.exists():
            return cls.build(root)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return cls.build(root)
        if payload.get("source_fingerprint") != _source_fingerprint(root):
            return cls.build(root)
        records = [Material(**row) for row in payload.get("materials", [])]
        return cls(project_root=root, records=records,
                   structured_links=payload.get("structured_links", {}))

    def _reindex(self) -> None:
        self._by_school = defaultdict(list)
        for record in self.records:
            self._by_school[record.school or "（无院校归属）"].append(record)

    def _annotate_unparsed(self) -> None:
        """给"进了分析口径却没抓到数据"的材料贴上如实原因（便于补采与排障）。"""
        for record in self.records:
            if not record.in_analysis:
                continue
            if record.derived or self.links_for(record.rel_path):
                record.unparsed_reason = ""
                continue
            if record.suffix not in {".pdf", ".docx", ".doc", ".txt"}:
                record.unparsed_reason = "非文本可解析格式"
            elif record.size_kb > 8192:
                record.unparsed_reason = "体积超解析阈值（多为扫描合集，未抽取）"
            else:
                record.unparsed_reason = "无文本层或版式未适配（未产出结构化数据）"

    # ---------- queries ----------
    def schools(self) -> list[str]:
        return sorted(self._by_school)

    def for_school(self, school: str) -> list[Material]:
        return list(self._by_school.get(canonical_school(school), []))

    def materials(self, *, school: str | None = None, material_type: str | None = None,
                  major: str | None = None, in_analysis_only: bool = True) -> list[Material]:
        out: list[Material] = []
        for record in (self.for_school(school) if school else self.records):
            if in_analysis_only and not record.in_analysis:
                continue
            if material_type and record.material_type != material_type:
                continue
            if major and major not in record.major and major not in record.file_name:
                continue
            out.append(record)
        return out

    def links_for(self, rel_path: str) -> list[str]:
        return self.structured_links.get(rel_path, [])

    def coverage(self) -> dict[str, Any]:
        """利用率审计：每份分析材料是否都能追到结构化产物或正文缓存。"""
        analysis = [r for r in self.records if r.in_analysis]
        linked = [r for r in analysis if r.derived or self.links_for(r.rel_path)]
        uncovered = [r.rel_path for r in analysis if not (r.derived or self.links_for(r.rel_path))]
        by_type = Counter(r.material_type for r in self.records)
        by_school = Counter(r.school or "（无院校归属）" for r in analysis)
        unparsed_by_type = Counter(r.material_type for r in analysis if r.unparsed_reason)
        return {
            "n_files_total": len(self.records),
            "n_files_analysis": len(analysis),
            "n_files_linked": len(linked),
            "n_files_unlinked": len(uncovered),
            "link_rate": round(len(linked) / len(analysis), 4) if analysis else 0.0,
            "unparsed_by_type": dict(sorted(unparsed_by_type.items(), key=lambda kv: -kv[1])),
            "unparsed_samples": [
                {"path": r.rel_path, "reason": r.unparsed_reason}
                for r in analysis if r.unparsed_reason
            ][:20],
            "by_material_type": dict(sorted(by_type.items(), key=lambda kv: -kv[1])),
            "n_schools": len(by_school),
            "schools": sorted(k for k in by_school if k != "（无院校归属）"),
        }

    def school_profile(self, school: str) -> dict[str, Any]:
        """某校有什么材料、覆盖哪些专业——给模型"这家学校本地有什么"的定点答案。"""
        school = canonical_school(school)
        rows = self.for_school(school)
        by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
        majors: set[str] = set()
        years: set[int] = set()
        for record in rows:
            if not record.in_analysis:
                continue
            by_type[record.material_type].append({
                "file": record.file_name, "major": record.major, "year": record.year,
                "subtype": record.subtype, "size_kb": record.size_kb,
                "linked": bool(record.derived or self.links_for(record.rel_path)),
            })
            if record.major:
                majors.add(record.major)
            if record.year:
                years.add(record.year)
        return {
            "school": school,
            "n_files": sum(len(v) for v in by_type.values()),
            "material_counts": {k: len(v) for k, v in sorted(by_type.items())},
            "majors": sorted(majors),
            "years": sorted(years),
            "materials": {k: v[:200] for k, v in sorted(by_type.items())},
        }

    # ---------- persistence ----------
    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": _now(),
            "root": "data/source",
            "source_fingerprint": _source_fingerprint(self.project_root),
            "coverage": self.coverage(),
            "structured_links": self.structured_links,
            "materials": [r.to_dict() for r in self.records],
        }

    def save(self) -> dict[str, Path]:
        inventory = self.project_root / self.INVENTORY_PATH
        index_path = self.project_root / self.INDEX_PATH
        documents_path = self.project_root / "data" / "processed" / "archive_documents.json"
        inventory.parent.mkdir(parents=True, exist_ok=True)
        index_path.parent.mkdir(parents=True, exist_ok=True)
        payload = self.to_dict()
        inventory.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        index_path.write_text(json.dumps({
            "generated_at": payload["generated_at"],
            "source_fingerprint": payload["source_fingerprint"],
            "coverage": payload["coverage"],
            "structured_links": payload["structured_links"],
            "materials": payload["materials"],
        }, ensure_ascii=False, indent=1), encoding="utf-8")
        documents_path.write_text(json.dumps(self.archive_documents(), ensure_ascii=False, indent=1),
                                  encoding="utf-8")
        return {"inventory": inventory, "index": index_path, "documents": documents_path}

    def archive_documents(self) -> list[dict[str, Any]]:
        """重生成归档文档清单（与旧 ``archive_documents.json`` 同字段，路径改为 data/source 规范结构）。"""
        rows: list[dict[str, Any]] = []
        for record in self.records:
            if not record.in_analysis:
                continue
            rows.append({
                "relative_path": record.rel_path.removeprefix("data/source/"),
                "source_path": record.rel_path,
                "file_name": record.file_name,
                "extension": record.suffix,
                "size_kb": record.size_kb,
                "category": record.material_type,
                "subtype": record.subtype,
                "school": record.school or None,
                "major": record.major or None,
                "years": [record.year] if record.year else [],
                "is_pdf": record.suffix == ".pdf",
                "is_text_extractable": bool(record.derived or self.links_for(record.rel_path)),
            })
        return rows


def _now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def _source_fingerprint(project_root: Path) -> str:
    """data/source 的廉价指纹（文件数 + 最新修改时间），用于判断落盘索引是否过期。"""
    base = Path(project_root).resolve() / "data" / "source"
    count = 0
    latest = 0.0
    if base.exists():
        for path in base.rglob("*"):
            if path.is_file():
                count += 1
                latest = max(latest, path.stat().st_mtime)
    return f"{count}:{int(latest)}"


def _collect_structured_links(project_root: Path) -> dict[str, list[str]]:
    """把课程库 / 事实库的 ``source_document`` 反查到具体文件，形成"文件 → 产物"映射。"""
    links: dict[str, list[str]] = defaultdict(list)

    def add(path_value: str, note: str) -> None:
        key = str(path_value or "").replace("\\", "/")
        if not key.startswith("data/source/"):
            return
        if note not in links[key]:
            links[key].append(note)

    courses = project_root / "data" / "raw" / "supplementary_courses.json"
    if courses.exists():
        counts = Counter()
        for row in json.loads(courses.read_text(encoding="utf-8")):
            counts[str(row.get("source_document") or "")] += 1
        for source, n in counts.items():
            add(source, f"课程库：{n} 门课程")

    # 插件收割库里的课程也指回 data/source 的原始件
    harvest_root = project_root / "data" / "harvest"
    if harvest_root.exists():
        for school_dir in sorted(p for p in harvest_root.iterdir() if p.is_dir()):
            path = school_dir / "courses.json"
            if not path.exists():
                continue
            counts = Counter()
            try:
                rows = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            for row in rows:
                counts[str(row.get("source_document") or "")] += 1
            for source, n in counts.items():
                add(source, f"插件收割课程库：{n} 门课程")

    for filename, label in (("pdf_facts.json", "教育事实"), ("pdf_major_rows.json", "分专业就业行")):
        path = project_root / "data" / "processed" / filename
        if not path.exists():
            continue
        counts = Counter()
        for row in json.loads(path.read_text(encoding="utf-8")):
            counts[str(row.get("source_document") or "")] += 1
        for source, n in counts.items():
            add(source, f"{label}：{n} 条")

    literature = project_root / "data" / "processed" / "literature.json"
    if literature.exists():
        try:
            payload = json.loads(literature.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload = {}
        works = payload.get("works") if isinstance(payload, dict) else payload
        if isinstance(works, list):
            for work in works:
                for key in ("source_file", "source_document", "path"):
                    add(str(work.get(key) or ""), "文献题录")

    # 政策文件：运行时由 ingest_policy_dir 逐份装载（A 级原文）
    policy_dir = project_root / "data" / "source" / "政策文件"
    if policy_dir.exists():
        for path in sorted(policy_dir.rglob("*")):
            if path.is_file():
                add(path.relative_to(project_root).as_posix(), "政策库：A 级原文（运行时装载）")

    # 招聘数据：Excel 一手表 → 岗位库
    jobs_meta = project_root / "data" / "processed" / "jobs_meta.json"
    if jobs_meta.exists():
        try:
            meta = json.loads(jobs_meta.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            meta = {}
        note = f"岗位库：{meta.get('effective_count') or meta.get('counts', {}).get('effective_count') or '—'} 条有效岗位"
        for path in sorted((project_root / "data" / "source" / "招聘数据").rglob("*")):
            if path.is_file():
                add(path.relative_to(project_root).as_posix(), note)
    return dict(links)


def clean_structured_schools(project_root: Path | None = None) -> dict[str, Any]:
    """清洗结构化产物里的院校字段：别名归一 + 按来源路径回填缺失院校。

    真实缺陷（本轮修复）：PDF 抽取把"中国矿业大学（北京）/中国石油大学（北京）/
    中国地质大学（北京）"写成去掉括号的短名，导致按校检索命中 0；另有 53 条
    事实的 ``school`` 为空，但来源路径本身能确定院校。
    """
    root = (project_root or PROJECT_ROOT).resolve()
    source = root / "data" / "source"
    schools = known_schools(source)
    log: dict[str, Any] = {"normalized": 0, "backfilled": 0, "unresolved_empty": 0, "files": {}}
    targets = {
        "pdf_facts.json": root / "data" / "processed" / "pdf_facts.json",
        "pdf_major_rows.json": root / "data" / "processed" / "pdf_major_rows.json",
        "pdf_index.json": root / "data" / "processed" / "pdf_index.json",
    }
    for filename, path in targets.items():
        if not path.exists():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows = payload if isinstance(payload, list) else payload.get("files") or []
        normalized = backfilled = unresolved = 0
        for row in rows:
            current = str(row.get("school") or "").strip()
            canonical = canonical_school(current)
            inferred = infer_school_from_path(str(row.get("source_document") or row.get("path") or ""), schools)
            if current and canonical != current:
                normalized += 1
            if not current and inferred:
                backfilled += 1
            if not current and not inferred:
                unresolved += 1
            row["school"] = canonical or inferred
        if normalized or backfilled:
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        log["normalized"] += normalized
        log["backfilled"] += backfilled
        log["unresolved_empty"] += unresolved
        log["files"][filename] = {"normalized": normalized, "backfilled": backfilled,
                                  "unresolved_empty": unresolved}
    log["generated_at"] = _now()
    return log

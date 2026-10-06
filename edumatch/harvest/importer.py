"""把 edu-material-harvest 的收割产物接进 EduMatch 的供给端数据流。

插件产出 ``<out>/新增数据/<校>/<材料类型>/…`` + ``records.json`` 台账。本模块：

1. **入库**：把每份材料复制进 ``data/source/<材料类型>/<院校>/``（与本地规范结构一致，
   带来源直链台账，可追溯）；同名同内容跳过、同名不同内容加后缀，绝不覆盖本地材料。
2. **解析**：培养方案 → 课程记录（学分/学时/必修，A 级）；课程大纲/专业介绍/年度报告
   → 可检索正文；年度报告 → 就业/教学事实。
3. **落账**：解析结果写 ``data/harvest/<校>/{courses,facts,manifest}.json`` 与
   ``data/harvest/<校>/texts/…``，与本地库物理分离，供 ``plugin`` / ``hybrid`` 模式装配。

不联网、不改本地既有数据；重复导入幂等。
"""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..ingest.plan_tables import parse_plan_text, sanitize_text
from ..ingest.pdf_reader import extract_pdf
from ..dataset import major_family
from .client import HarvestOutcome

REPORT_KEYWORDS = (("就业", "就业质量报告"), ("毕业生", "就业质量报告"),
                   ("教学质量", "教学质量报告"), ("本科教学", "教学质量报告"),
                   ("研究生教育发展质量", "教学质量报告"))


@dataclass
class HarvestImportResult:
    school: str
    out_dir: str
    installed: list[dict[str, Any]] = field(default_factory=list)
    skipped: list[dict[str, Any]] = field(default_factory=list)
    n_courses: int = 0
    n_texts: int = 0
    n_facts: int = 0
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _sha1(path: Path) -> str:
    digest = hashlib.sha1()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _year_of(text: str) -> int | None:
    import re

    for match in re.finditer(r"(19|20)\d{2}", str(text or "")):
        year = int(match.group(0))
        if 1900 <= year <= 2099:
            return year
    return None


def derive_major(desc: str, kind: str) -> str:
    """从插件给的说明文字里取专业名（``2024_人工智能专业培养方案`` → ``人工智能``）。"""
    text = str(desc or "").strip()
    if "_" in text:
        head, tail = text.split("_", 1)
        if head.strip().isdigit():
            text = tail.strip()
    for suffix in ("专业培养方案", "培养方案", "专业介绍", "课程大纲", "教学大纲",
                   "招生专业介绍汇编", "招生报考指南"):
        if text.endswith(suffix):
            text = text[: -len(suffix)].strip(" 　·-_")
    return text.strip()


def report_subtype(name: str) -> str:
    for keyword, subtype in REPORT_KEYWORDS:
        if keyword in name:
            return subtype
    return "其他报告"


class HarvestImporter:
    """收割产物 → 规范目录树 + 供给侧解析产物。"""

    def __init__(self, project_root: Path, *, enabled: bool = True) -> None:
        self.root = Path(project_root).resolve()
        self.source = self.root / "data" / "source"
        self.harvest_root = self.root / "data" / "harvest"
        self.manifest_path = self.root / "data" / "processed" / "harvest_imports.json"
        self.enabled = enabled

    # ---------- 入口 ----------
    def import_outcome(self, outcome: HarvestOutcome) -> HarvestImportResult:
        school = outcome.school or "未识别院校"
        result = HarvestImportResult(school=school, out_dir=self._rel(Path(outcome.out_dir)))
        if not outcome.records:
            result.notes.append("台账为空：插件未产出任何材料（无候选/站点拦截/域名未核实）。")
            return result
        payload_root = Path(outcome.out_dir) / "新增数据"
        for record in outcome.records:
            rel = str(record.get("file") or "")
            if not rel:
                result.skipped.append({"reason": record.get("status") or "未下载",
                                       "desc": record.get("desc"), "url": record.get("url")})
                continue
            src = payload_root / rel
            if not src.exists():
                result.skipped.append({"reason": "文件缺失", "desc": record.get("desc"), "path": str(src)})
                continue
            self._install_one(school, record, src, result)
        self._write_manifest(result)
        return result

    # ---------- 单份处理 ----------
    def _install_one(self, school: str, record: dict[str, Any], src: Path,
                     result: HarvestImportResult) -> None:
        kind = str(record.get("kind") or "未分类")
        desc = str(record.get("desc") or src.stem)
        suspect = self._suspect_reason(kind, src)
        dst = (self.source / "非分析归档" / "疑似误判" / school / src.name if suspect
               else self._destination(school, kind, record, desc, src))
        action = self._place(src, dst)
        entry = {
            "kind": kind, "desc": desc, "src": self._rel(src), "dst": dst.relative_to(self.root).as_posix(),
            "action": action, "url": record.get("url"), "page": record.get("page"),
            "sha1": record.get("sha1") or _sha1(dst), "year": record.get("year") or _year_of(desc),
        }
        if suspect:
            # 插件文档里的"类型假"陷阱：附件是真的、类型判错（如把表格下载页当培养方案）。
            # 如实记录并隔离，绝不进分析语料。
            entry["suspect"] = suspect
            result.notes.append(f"疑似类型误判（{suspect}）：{src.name} → 非分析归档/疑似误判/")
        if action == "skip":
            result.skipped.append({"reason": "同名同内容已存在", **entry})
        else:
            result.installed.append(entry)
        # 关键：即使原件与本地重复（不重复入库），仍要把它解析进"收割库"，
        # 否则 plugin 模式（不依赖本地库）会缺这批课程。
        if not self.enabled:
            return
        if not suspect:
            self._derive(school, kind, desc, dst, entry, result)

    @staticmethod
    def _suspect_reason(kind: str, src: Path) -> str:
        """材料类型与文件形态明显不符时给出原因（空串=正常）。"""
        suffix = src.suffix.lower()
        if kind in {"培养方案", "课程大纲"} and suffix in {".doc", ".docx", ".xls", ".xlsx"}:
            return f"{kind}应为 PDF，实际是 {suffix}（多为站点表格/模版下载页）"
        return ""

    def _destination(self, school: str, kind: str, record: dict[str, Any],
                     desc: str, src: Path) -> Path:
        year = record.get("year") or _year_of(desc) or _year_of(src.name)
        suffix = src.suffix.lower() or ".pdf"
        if kind == "培养方案":
            major = derive_major(desc, kind) or src.stem
            name = f"{year}_{major}{suffix}" if year else f"{major}{suffix}"
            return self.source / "培养方案" / school / name
        if kind == "专业介绍":
            major = derive_major(desc, kind) or src.stem
            name = f"{year}_{major}{suffix}" if year else f"{major}{suffix}"
            return self.source / "专业介绍" / school / name
        if kind == "课程大纲":
            return self.source / "课程大纲" / school / f"{desc}{suffix}"
        if kind == "年度报告":
            subtype = report_subtype(desc) or report_subtype(src.name)
            return self.source / "年度报告" / school / subtype / src.name
        return self.source / "收割其他" / school / f"{desc}{suffix}"

    @staticmethod
    def _place(src: Path, dst: Path) -> str:
        """复制入库：同内容跳过、同路径不同内容加后缀，绝不覆盖。"""
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists():
            if dst.stat().st_size == src.stat().st_size and _sha1(dst) == _sha1(src):
                return "skip"
            for i in range(2, 1000):
                candidate = dst.with_name(f"{dst.stem}_harvest{i}{dst.suffix}")
                if not candidate.exists():
                    dst = candidate
                    break
        shutil.copy2(src, dst)
        return "added"

    # ---------- 解析 ----------
    def _derive(self, school: str, kind: str, desc: str, dst: Path,
                entry: dict[str, Any], result: HarvestImportResult) -> None:
        if dst.suffix.lower() != ".pdf":
            result.notes.append(f"未解析非 PDF 材料：{dst.name}")
            return
        pdf = extract_pdf(dst)
        pdf.path = dst.relative_to(self.root).as_posix()
        if pdf.text_status != "ok":
            result.notes.append(f"无可抽取文本层（{pdf.text_status}）：{dst.name}")
            return
        year = entry.get("year") or _year_of(dst.name)
        if kind in {"培养方案", "课程大纲", "专业介绍", "年度报告"}:
            if self._write_text(school, kind, dst, pdf):
                result.n_texts += 1
            entry["text_status"] = "ok"
        if kind == "培养方案":
            major = derive_major(desc, kind) or dst.stem
            parsed = parse_plan_text(
                pdf.text, school=school, year=year, major=major,
                family=major_family(major), source_document=pdf.path, evidence_level="A",
            )
            if parsed.courses:
                rows = [asdict(course) for course in parsed.courses]
                added = self._append_jsonl("courses", school, rows, key="course_id")
                entry["n_courses"] = added
                result.n_courses += added
            else:
                result.notes.append(
                    f"培养方案版式未适配（{parsed.n_rows} 行命中，低于阈值）：{dst.name}"
                )
        if kind == "年度报告" and "就业" in (desc + dst.name):
            from ..ingest.pdf_facts import extract_pdf_facts

            facts = extract_pdf_facts(pdf, school=school, year=year)
            if facts:
                rows = [asdict(f) for f in facts]
                added = self._append_jsonl("facts", school, rows, key="fact_id")
                entry["n_facts"] = added
                result.n_facts += added

    def _write_text(self, school: str, kind: str, dst: Path, pdf) -> bool:
        """写正文缓存；返回是否为新内容（重复导入不重复计数）。"""
        out_dir = self.harvest_root / school / "texts" / kind
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"{dst.stem}.txt"
        text = sanitize_text(pdf.text)
        if path.exists() and path.read_text(encoding="utf-8", errors="replace") == text:
            return False
        path.write_text(text, encoding="utf-8")
        return True

    def _append_jsonl(self, name: str, school: str, rows: list[dict[str, Any]], *, key: str) -> int:
        path = self.harvest_root / school / f"{name}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        existing: list[dict[str, Any]] = []
        if path.exists():
            try:
                existing = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                existing = []
        known = {str(r.get(key)) for r in existing}
        added = [r for r in rows if str(r.get(key)) not in known]
        if added:
            payload = existing + added
            path.write_text(sanitize_text(json.dumps(payload, ensure_ascii=False, indent=1)),
                            encoding="utf-8")
        return len(added)

    # ---------- 台账 ----------
    def _write_manifest(self, result: HarvestImportResult) -> None:
        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        records: list[dict[str, Any]] = []
        if self.manifest_path.exists():
            try:
                records = json.loads(self.manifest_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                records = []
        # 台账只保留可审计的摘要：条目列表截断到样本 + 计数，避免反复导入把文件撑大
        summary = result.to_dict()
        summary["n_installed"] = len(summary["installed"])
        summary["n_skipped"] = len(summary["skipped"])
        summary["installed"] = summary["installed"][:100]
        summary["skipped"] = summary["skipped"][:50]
        summary["notes"] = summary["notes"][:20]
        records.append({"imported_at": datetime.now(timezone.utc).isoformat(), **summary})
        records = records[-200:]
        self.manifest_path.write_text(
            sanitize_text(json.dumps(records, ensure_ascii=False, indent=1)), encoding="utf-8"
        )
        school_dir = self.harvest_root / result.school
        school_dir.mkdir(parents=True, exist_ok=True)
        cumulative = sum(int(entry.get("n_installed", len(entry.get("installed") or [])))
                         for entry in records if entry.get("school") == result.school)
        snapshot = {
            **result.to_dict(),
            "imported_at": records[-1]["imported_at"],
            "n_installed": cumulative,
            "n_courses": self._count(school_dir / "courses.json"),
            "n_facts": self._count(school_dir / "facts.json"),
            "n_texts": len(list((school_dir / "texts").rglob("*.txt")))
            if (school_dir / "texts").exists() else 0,
        }
        (school_dir / "manifest.json").write_text(
            sanitize_text(json.dumps(snapshot, ensure_ascii=False, indent=1)), encoding="utf-8"
        )

    @staticmethod
    def _count(path: Path) -> int:
        if not path.exists():
            return 0
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return 0
        return len(payload) if isinstance(payload, list) else 0

    def _rel(self, path: Path) -> str:
        """包内路径写成相对形式，保持整包可迁移（不出现盘符）。"""
        try:
            return Path(path).resolve().relative_to(self.root).as_posix()
        except ValueError:
            return str(path)


def harvest_school_dir(project_root: Path, school: str) -> Path:
    return Path(project_root).resolve() / "data" / "harvest" / school

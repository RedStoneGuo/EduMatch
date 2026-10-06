"""高校覆盖的端到端接线：发现 → 状态机 → 覆盖报告（spec §10、§11）。

把已有的三个能力接起来：

1. **发现**：`edumatch/peers.py` 的全国高校名单（教育部名单 + 985/211）按省市筛出
   目标高校集合；
2. **状态**：逐校逐材料判定 7 状态机（是否有原件、是否有正文、正文是否真的可分析）；
3. **报告**：`edumatch/coverage_state.py` 汇总
   `target / covered / coverage_rate / successful_documents / missing_universities / failure_reasons`。

关键约定：**搜索到 URL 不算覆盖**；材料存在但正文里没有可用的培养目标段落，
记为 `TEXT_EXTRACTED` + 失败原因，而不是 READY。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Sequence

from analysis.objective_alignment import extract_objective_candidates

from .coverage_state import CoverageRecord, STATE_ORDER, coverage_report
from .peers import UniversityCatalog, _local_majors

MATERIAL_TYPES: tuple[str, ...] = ("培养方案课程", "培养目标", "教学质量报告", "就业质量报告")
DEFAULT_REQUIRED: tuple[str, ...] = ("培养方案课程", "培养目标")


def major_matches_path(path: Path, major: str) -> bool:
    """文件名/路径是否对应**本专业**（避免把"电子信息类(含人工智能)"当成人工智能专业）。"""
    if not major:
        return True
    stem = path.stem
    tail = stem.split("_", 1)[1] if "_" in stem else stem
    tail = tail.strip()
    if tail == major or tail.startswith(major):
        return True
    if "-" in tail or "(" in tail or "（" in tail:
        return False
    return major in tail


def _source_dirs(project_root: Path, material: str) -> list[Path]:
    root = project_root / "data" / "source"
    if material == "培养方案课程":
        return [root / "培养方案", project_root / "data" / "raw" / "pdf_text"]
    if material == "培养目标":
        return [root / "培养方案", root / "专业介绍", project_root / "data" / "raw" / "pdf_text"]
    if material == "教学质量报告":
        return [root / "年度报告", project_root / "data" / "raw" / "pdf_text"]
    if material == "就业质量报告":
        return [root / "年度报告"]
    return [root]


def _files_for(project_root: Path, school: str, material: str,
               major: str = "") -> tuple[list[Path], list[Path]]:
    """Return (all files, files matching the major when a major is given)."""
    pdfs: list[Path] = []
    for base in _source_dirs(project_root, material):
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in {".pdf", ".txt"}:
                continue
            if school and school not in str(path):
                continue
            if "非分析归档" in str(path):
                continue
            pdfs.append(path)
    if not major:
        return pdfs, pdfs
    return pdfs, [p for p in pdfs if major_matches_path(p, major) or major in str(p.parent)]


def evaluate_school_material(
    project_root: Path,
    school: str,
    material: str,
    *,
    major: str = "",
) -> CoverageRecord:
    """Walk one (school, material) through the coverage state machine."""
    record = CoverageRecord(school=school, major=major)
    all_files, major_files = _files_for(project_root, school, material, major)
    if not all_files:
        record.advance("DISCOVERED", reason=f"本地与采集台账均无「{material}」线索")
        return record
    record.advance("SOURCE_VERIFIED", reason="材料出现在规范来源目录 data/source")
    record.advance("DOWNLOAD_ATTEMPTED", reason="本地已存在材料文件")
    record.advance("FILE_VALIDATED", reason=f"文件数量 {len(all_files)}")
    record.advance("ORIGINAL_FILE_SAVED", reason="原件保存在 data/source")
    documents = [str(p.relative_to(project_root).as_posix()) for p in all_files[:20]]
    record.documents = documents
    texts = [p for p in major_files if p.suffix.lower() == ".txt"]
    if material == "培养方案课程":
        if not texts:
            record.advance("ORIGINAL_FILE_SAVED", reason="只有 PDF，缺可检索正文（文本未抽取）")
            return record
        record.advance("TEXT_EXTRACTED", reason=f"可检索正文 {len(texts)} 份")
        has_codes = any(_looks_like_course_table(p) for p in texts)
        if has_codes:
            record.advance("READY_FOR_ANALYSIS", reason="正文含课程表，可提取课程")
        else:
            record.advance("TEXT_EXTRACTED", reason="正文未识别到课程表结构")
        return record
    if material == "培养目标":
        if not texts:
            record.advance("ORIGINAL_FILE_SAVED", reason="培养方案/专业介绍只有 PDF，正文未抽取")
            return record
        record.advance("TEXT_EXTRACTED", reason=f"可检索正文 {len(texts)} 份")
        for path in texts[:12]:
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if any(c.valid for c in extract_objective_candidates(text, limit=5)):
                record.advance("READY_FOR_ANALYSIS", reason=f"命中可核查培养目标：{path.name}")
                return record
        record.advance("TEXT_EXTRACTED",
                       reason="正文存在但未找到可核查的「培养目标」段落（S1 将记证据不足）")
        return record
    # 报告类材料：有正文即视为可分析
    if texts:
        record.advance("TEXT_EXTRACTED", reason=f"可检索正文 {len(texts)} 份")
        record.advance("READY_FOR_ANALYSIS", reason="报告正文可用于指标抽取")
    else:
        record.advance("ORIGINAL_FILE_SAVED", reason="仅有 PDF 原件，正文未抽取")
    return record


def _looks_like_course_table(path: Path) -> bool:
    try:
        head = path.read_text(encoding="utf-8", errors="ignore")[:4000]
    except OSError:
        return False
    import re

    return bool(re.search(r"\b\d{6,7}\b", head)) and ("学分" in head or "考试" in head or "考查" in head)


def discover_target_schools(
    project_root: Path,
    *,
    province: str = "北京市",
    schools: Sequence[str] | None = None,
) -> list[str]:
    if schools:
        return list(schools)
    catalog = UniversityCatalog.load(project_root)
    matched = [u.name for u in catalog.search(province=province)] if catalog.schools else []
    return sorted(set(matched))


def audit_university_coverage(
    project_root: Path,
    *,
    province: str = "北京市",
    major: str = "人工智能",
    schools: Sequence[str] | None = None,
    required: Iterable[str] = DEFAULT_REQUIRED,
    discovered_by: str = "教育部全国高校名单",
) -> dict[str, Any]:
    """发现 + 状态机 + 覆盖报告，返回可直接进报告的覆盖对象。"""
    project_root = Path(project_root).resolve()
    targets = discover_target_schools(project_root, province=province, schools=schools)
    local = _local_majors(project_root)
    required = list(required)
    records: list[CoverageRecord] = []
    per_school: dict[str, dict[str, Any]] = {}
    for school in targets:
        materials = {m: evaluate_school_material(project_root, school, m, major=major)
                     for m in MATERIAL_TYPES}
        records.extend(materials.values())
        ready = [m for m in required if materials[m].state == "READY_FOR_ANALYSIS"]
        per_school[school] = {
            "ready": len(ready) == len(required),
            "ready_materials": ready,
            "missing_materials": [m for m in required if m not in ready],
            "materials": {m: materials[m].to_dict() for m in MATERIAL_TYPES},
            "has_local_major": major in local.get(school, set()),
        }
    base = coverage_report(records, target_schools=targets)
    covered = [s for s, info in per_school.items() if info["ready"]]
    return {
        **base,
        "province": province,
        "major": major,
        "required_materials": required,
        "discovered_by": discovered_by,
        "covered_universities": sorted(covered),
        "missing_universities": sorted(s for s in targets if s not in set(covered)),
        "n_covered": len(covered),
        "coverage_rate": round(len(covered) / len(targets), 4) if targets else 0.0,
        "per_school": per_school,
        "note": ("只有必需材料全部到达 READY_FOR_ANALYSIS 的院校才算覆盖；"
                 "材料存在但正文缺培养目标段落，记 TEXT_EXTRACTED 并给出失败原因。"),
    }

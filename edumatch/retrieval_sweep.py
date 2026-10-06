"""全面检索（comprehensive retrieval）：把"查过哪些源"变成可审计的台账。

系统的默认意识是：**不要只查一个地方就下"没有"的结论**。对任意院校 + 任意专业，
按固定顺序穷举全部可用来源，逐项记录命中 / 未命中 / 失败原因 / 下一步动作：

1. 本地正文缓存      `data/raw/pdf_text/**`
2. 规范一手材料      `data/source/<数据类型>/<院校>/**`（PDF / DOCX / XLSX / TXT）
3. 归档历史资料      `AI竞赛数据归档/**`（只读）
4. 采集产物          `data/harvest/<院校>/**`（插件离线回放）
5. 联网插件采集      `vendor/edu-material-harvest`（有域名台账才允许；本次未联网时记 planned）

每条记录都带 ``state``：

    hit            — 找到正文且可读
    extracted_pdf  — 只有 PDF，已按需抽正文（缓存）
    need_online    — 本地/归档/采集都没有，需要联网补采（给出域名与入口）
    miss           — 该来源不存在
    error          — 文件在但抽取失败（如实记录，不猜测内容）
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

from analysis.objective_alignment import (
    extract_major_objective_candidates,
    extract_objective_candidates,
)

MATERIAL_KEYWORDS: dict[str, tuple[str, ...]] = {
    "培养目标": ("培养方案", "专业介绍", "教学质量报告", "就业质量报告", "年度报告"),
    "培养方案": ("培养方案",),
    "课程大纲": ("课程大纲", "教学大纲"),
    "教学质量报告": ("教学质量报告", "年度报告"),
    "就业质量报告": ("就业质量报告",),
    "专业介绍": ("专业介绍",),
}

SOURCE_KINDS: tuple[str, ...] = ("pdf_text", "source", "archive", "harvest")

#: 各来源的根目录（相对项目根）；archive 走包外归档。
SOURCE_ROOTS: dict[str, tuple[str, ...]] = {
    "pdf_text": ("data/raw/pdf_text",),
    "source": ("data/source",),
    "archive": ("../AI竞赛数据归档",),
    "harvest": ("data/harvest",),
}

TEXT_SUFFIXES = {".txt", ".md", ".json", ".csv"}
DOC_SUFFIXES = {".pdf", ".docx", ".doc", ".xlsx", ".xls"}


@dataclass
class SourceAttempt:
    kind: str
    reference: str
    state: str
    reason: str = ""
    text_chars: int = 0
    objectives_found: int = 0
    #: 明确标注"这条查的是哪所院校/哪个专业/哪份文件"，避免一屏同名材料。
    school: str = ""
    major: str = ""
    file: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class MaterialLedger:
    material: str
    attempts: list[SourceAttempt] = field(default_factory=list)
    online_plan: dict[str, Any] = field(default_factory=dict)

    @property
    def hits(self) -> list[SourceAttempt]:
        return [a for a in self.attempts if a.state in {"hit", "extracted_pdf"}]

    @property
    def needed_online(self) -> bool:
        return not self.hits or all(a.objectives_found == 0 for a in self.hits)

    def to_dict(self) -> dict[str, Any]:
        return {
            "material": self.material,
            "n_searched": len(self.attempts),
            "n_hit": len(self.hits),
            "n_need_online": sum(1 for a in self.attempts if a.state == "need_online"),
            "n_error": sum(1 for a in self.attempts if a.state == "error"),
            "attempts": [a.to_dict() for a in self.attempts],
            "online_plan": self.online_plan,
        }


def _domain_for(project_root: Path, school: str | None) -> str:
    if not school:
        return ""
    path = project_root / "data" / "harvest" / "domains.json"
    if not path.exists():
        return ""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return ""
    value = payload.get(school)
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return str(value.get("domain") or "")
    return ""


def _candidate_paths(project_root: Path, kind: str, school: str | None,
                     keywords: Sequence[str]) -> list[Path]:
    roots: list[Path] = []
    for rel in SOURCE_ROOTS.get(kind, ()):
        base = (project_root / rel).resolve()
        if base.exists():
            roots.append(base)
    found: list[Path] = []
    for base in roots:
        for path in base.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in (TEXT_SUFFIXES | DOC_SUFFIXES):
                continue
            text = str(path)
            if "非分析归档" in text:
                continue
            if school and school not in text:
                continue
            if keywords and not any(k in text for k in keywords):
                continue
            found.append(path)
    return sorted(found)


def _read_text(path: Path, project_root: Path, *, extract_pdf: bool,
               max_chars: int) -> tuple[str, str]:
    """Return (state, text); state is hit / extracted_pdf / error."""
    suffix = path.suffix.lower()
    if suffix in TEXT_SUFFIXES:
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError as exc:
            return "error", f"读取失败：{type(exc).__name__}"
        return "hit", text[:max_chars]
    if suffix == ".pdf" and extract_pdf:
        from .pdf_text import cached_pdf_text

        text = cached_pdf_text(path, project_root=project_root, max_chars=max_chars)
        if text:
            return "extracted_pdf", text
        return "error", "PDF 无文本层或抽取失败（不猜测内容）"
    if suffix in DOC_SUFFIXES:
        return "error", f"{suffix} 无文本层（extractor_unavailable）"
    return "miss", "不支持的格式"


def sweep_sources(
    project_root: Path,
    *,
    school: str | None,
    major: str | None = None,
    materials: Iterable[str] = ("培养目标",),
    extract_pdf: bool = True,
    max_files_per_kind: int = 8,
    max_chars_per_file: int = 200_000,
    max_total_chars: int = 400_000,
) -> dict[str, Any]:
    """穷举全部来源，返回可进报告/审计的检索台账 + 抽到的正文 + 培养目标候选。"""
    project_root = Path(project_root).resolve()
    # 区域尺度（未点名院校）文件量极大：只扫文本、限制条数，避免一次分析被检索拖慢。
    if not school:
        extract_pdf = False
    region_caps = {"pdf_text": 14, "source": 6, "archive": 3, "harvest": 3}
    ledgers: dict[str, MaterialLedger] = {}
    texts: list[dict[str, Any]] = []
    objective_candidates: list[dict[str, Any]] = []
    total_chars = 0
    for material in materials:
        keywords = MATERIAL_KEYWORDS.get(material, (material,))
        ledger = MaterialLedger(material=material)
        if school:
            domain = _domain_for(project_root, school)
            ledger.online_plan = {
                "needed": True,  # 由收尾时按命中情况改写
                "domain": domain or None,
                "domain_verified": bool(domain),
                "entry_a": "插件全站/栏目采集（--source-mode plugin --harvest）",
                "entry_b": "承载页直采（--harvest-page <url> --harvest-kind 培养方案）",
                "note": "域名必须先过 scripts/resolve_school_domains.py 实测核实，禁止猜域名。",
            }
        for kind in SOURCE_KINDS:
            paths = _candidate_paths(project_root, kind, school, keywords)
            if major:
                # 文件名/路径带专业名的优先，保证有限的检索额度用在"本专业"的材料上
                paths.sort(key=lambda p: (0 if major in str(p) else 1, str(p)))
            cap = (min(max_files_per_kind, region_caps.get(kind, 3)) if not school
                   else max_files_per_kind)
            if not paths:
                ledger.attempts.append(SourceAttempt(
                    kind=kind, reference=f"{kind}:<无匹配材料>", state="miss",
                    reason="该来源下没有匹配的院校/材料文件",
                    school=school or "", major=major or "", file="—"))
                continue
            for path in paths[:cap]:
                try:
                    reference = str(path.relative_to(project_root).as_posix())
                except ValueError:
                    reference = str(path)
                filename = path.name
                state, text_or_reason = _read_text(
                    path, project_root, extract_pdf=extract_pdf,
                    max_chars=max_chars_per_file)
                if state in {"hit", "extracted_pdf"}:
                    text = str(text_or_reason)
                    objectives = 0
                    if material == "培养目标":
                        found = []
                        for candidate in extract_objective_candidates(
                                text, limit=3, scope="school"):
                            candidate.anchor = f"{reference}"
                            found.append(candidate)
                        if major:
                            for candidate in extract_major_objective_candidates(
                                    text, major, limit=3):
                                candidate.anchor = f"{reference}:{major}"
                                found.append(candidate)
                        objectives = sum(1 for c in found if c.valid)
                        objective_candidates.extend(c.to_dict() for c in found[:6])
                        if objectives and total_chars < max_total_chars:
                            texts.append({"kind": kind, "reference": reference,
                                          "text": text[:max_chars_per_file],
                                          "objectives_found": objectives})
                            total_chars += min(len(text), max_chars_per_file)
                    ledger.attempts.append(SourceAttempt(
                        kind=kind, reference=reference, state=state, text_chars=len(text),
                        objectives_found=objectives,
                        school=school or "", major=major or "", file=filename,
                        reason="" if objectives or material != "培养目标"
                        else "正文可读，但未找到本专业的培养目标段落"))
                else:
                    ledger.attempts.append(SourceAttempt(
                        kind=kind, reference=reference, state=state, reason=str(text_or_reason),
                        school=school or "", major=major or "", file=filename))
        # 联网来源：本地/归档/采集都没命中可核查目标时才标 need_online
        if school and ledger.online_plan:
            ledger.online_plan["needed"] = all(a.objectives_found == 0 for a in ledger.hits) \
                if ledger.hits else True
            if ledger.online_plan["needed"]:
                ledger.attempts.append(SourceAttempt(
                    kind="plugin_online", reference=f"plugin:{school}", state="need_online",
                    school=school or "", major=major or "", file="—",
                    reason=("本地正文缓存 / 规范源 / 归档 / 采集产物均无可核查的"
                            f"「{material}」原文，需联网补采")))
        ledgers[material] = ledger

    return {
        "school": school or "",
        "major": major or "",
        "materials": {m: ledger.to_dict() for m, ledger in ledgers.items()},
        "texts": texts,
        "objective_candidates": objective_candidates,
        "summary": {
            "n_materials": len(ledgers),
            "n_attempts": sum(len(ledger.attempts) for ledger in ledgers.values()),
            "n_hits": sum(len(ledger.hits) for ledger in ledgers.values()),
            "needs_online": {m: ledger.needed_online for m, ledger in ledgers.items()},
            "by_kind": _by_kind(ledgers),
        },
        "note": ("全面检索：本地正文缓存 → 规范一手材料 → 归档 → 采集产物 → 联网插件；"
                 "任一来源未命中都要记录原因与下一步，不以单来源的未命中下结论。"),
    }


def _by_kind(ledgers: dict[str, MaterialLedger]) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    for ledger in ledgers.values():
        for attempt in ledger.attempts:
            bucket = out.setdefault(attempt.kind, {})
            bucket[attempt.state] = bucket.get(attempt.state, 0) + 1
    return out


def render_ledger_markdown(ledger: dict[str, Any], *, limit: int = 14) -> list[str]:
    """Render the ledger as markdown lines (used by reports)."""
    materials = ledger.get("materials") or {}
    if not materials:
        return []
    lines = ["## 全面检索台账（本地 → 归档 → 采集 → 联网）", "",
             "| 院校 | 专业 | 材料 | 来源 | 状态 | 说明 | 文件 |",
             "| --- | --- | --- | --- | --- | --- | --- |"]
    count = 0
    for material, block in materials.items():
        for attempt in block.get("attempts") or []:
            if count >= limit:
                break
            lines.append(
                f"| {attempt.get('school') or ledger.get('school') or '—'} | "
                f"{attempt.get('major') or ledger.get('major') or '—'} | {material} | "
                f"{attempt.get('kind')} | {attempt.get('state')} | "
                f"{(attempt.get('reason') or '')[:70]} | {attempt.get('file') or '—'} |")
            count += 1
    for material, block in materials.items():
        plan = block.get("online_plan") or {}
        if plan.get("needed"):
            lines += ["",
                      f"- **联网补采计划（{material}）**：域名 "
                      f"`{plan.get('domain') or '未核实'}`；入口 A：{plan.get('entry_a')}；"
                      f"入口 B：{plan.get('entry_b')}"]
    lines += ["", f"- {ledger.get('note', '')}", ""]
    return lines

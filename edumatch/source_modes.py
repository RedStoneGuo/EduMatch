"""教育供给端数据来源模式：``local`` / ``plugin`` / ``hybrid``。

| 模式 | 目标院校供给数据从哪来 | 是否用本地库 | 典型用途 |
| --- | --- | --- | --- |
| ``local``  | ``data/source`` + 本地结构化库 | 是 | 离线复现、已有 27 校 |
| ``plugin`` | edu-material-harvest 联网收割 | 仅需求侧（招聘） | 任意院校、脱离本地库 |
| ``hybrid`` | 插件新收割 **+** 本地全部对应数据 | 是 | 同一院校本地+新增合并分析 |

本模块只负责"装配"：解析模式、跑插件、入库、把收割产物转成 Dataset 能吃的形态。
真正的计算仍然全部在 ``analysis/``。
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

SOURCE_MODES: tuple[str, ...] = ("local", "plugin", "hybrid")


class SourceModeError(ValueError):
    """非法的数据来源模式或缺失必要参数。"""


def normalize_mode(mode: str | None) -> str:
    value = str(mode or "local").strip().lower()
    aliases = {"本地": "local", "插件": "plugin", "混合": "hybrid", "dual": "hybrid"}
    value = aliases.get(value, value)
    if value not in SOURCE_MODES:
        raise SourceModeError(f"未知数据来源模式 {mode!r}；可选 {SOURCE_MODES}")
    return value


def uses_local(mode: str) -> bool:
    return normalize_mode(mode) in {"local", "hybrid"}


def uses_harvest(mode: str) -> bool:
    return normalize_mode(mode) in {"plugin", "hybrid"}


@dataclass
class SupplySourceReport:
    """一次分析里供给侧数据的实际来源（写进报告与检索清单）。"""

    mode: str = "local"
    harvest_requested: bool = False
    harvest_performed: bool = False
    harvest_backend: str = ""
    harvest_school: str = ""
    harvest_domain: str = ""
    harvest_state: str = ""
    harvest_out_dir: str = ""
    harvest_records: dict[str, int] = field(default_factory=dict)
    harvest_import: dict[str, Any] = field(default_factory=dict)
    local_courses: int = 0
    harvest_courses: int = 0
    local_facts: int = 0
    harvest_facts: int = 0
    #: 同类院校（peer benchmark）口径
    peer_selector: str = ""                 # auto | explicit | none
    peer_candidates: list[dict[str, Any]] = field(default_factory=list)
    peer_harvested: list[str] = field(default_factory=list)
    peer_reused: list[str] = field(default_factory=list)
    peer_skipped: list[dict[str, str]] = field(default_factory=list)
    peer_note: str = ""
    notes: list[str] = field(default_factory=list)
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def describe(self) -> str:
        if self.mode == "local":
            return "本地数据模式：供给端全部取自 data/source 与本地结构化库。"
        if self.error:
            return f"插件数据模式未能联网收割（{self.error}）；已按证据不足处理。"
        source = "仅插件收割数据" if self.mode == "plugin" else "插件收割数据 + 本地全量数据"
        peer = ""
        if self.peer_candidates:
            peer = (f"；同类基准 = {len(self.peer_harvested) + len(self.peer_reused)} 所同类院校"
                    f"（新采 {len(self.peer_harvested)} / 复用 {len(self.peer_reused)}）")
        return (f"{self.mode} 模式：供给端 = {source}"
                f"（本地 {self.local_courses} 门课程 / 收割 {self.harvest_courses} 门课程；"
                f"本地 {self.local_facts} 条事实 / 收割 {self.harvest_facts} 条事实）{peer}。")


def harvest_root(project_root: Path) -> Path:
    return Path(project_root).resolve() / "data" / "harvest"


def load_harvest_bundle(project_root: Path, schools: Iterable[str]) -> dict[str, Any]:
    """读取 ``data/harvest/<校>/`` 下已解析的收割产物（不联网）。"""
    root = harvest_root(project_root)
    bundle: dict[str, Any] = {"courses": [], "facts": [], "text_roots": [], "schools": []}
    for school in schools:
        if not school:
            continue
        school_dir = root / school
        if not school_dir.exists():
            continue
        bundle["schools"].append(school)
        for name, key in (("courses.json", "courses"), ("facts.json", "facts")):
            path = school_dir / name
            if not path.exists():
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            if isinstance(payload, list):
                bundle[key].extend(payload)
        texts = school_dir / "texts"
        if texts.exists():
            bundle["text_roots"].append(texts)
    return bundle


def harvest_status(project_root: Path) -> dict[str, Any]:
    """本地已有哪些院校的插件收割产物（离线可查，不需要联网）。"""
    root = harvest_root(project_root)
    schools: list[dict[str, Any]] = []
    if root.exists():
        installed_history: dict[str, int] = {}
        history_path = Path(project_root).resolve() / "data" / "processed" / "harvest_imports.json"
        if history_path.exists():
            try:
                for entry in json.loads(history_path.read_text(encoding="utf-8")):
                    school_name = str(entry.get("school") or "")
                    installed_history[school_name] = installed_history.get(school_name, 0) + int(
                        entry.get("n_installed", len(entry.get("installed") or [])))
            except json.JSONDecodeError:
                pass
        # 跳过容器目录（插件原始产出放在 收割/）与临时目录
        for school_dir in sorted(p for p in root.iterdir()
                                 if p.is_dir() and not p.name.startswith((".", "_"))
                                 and p.name != "收割"):
            manifest = school_dir / "manifest.json"
            info: dict[str, Any] = {
                "school": school_dir.name,
                # 已入库的收割件 = 收割库课程/事实引用的原始件 ∪ 台账里登记过的入库件
                "n_source_materials": _harvested_sources(school_dir) or installed_history.get(
                    school_dir.name, 0),
                "n_courses": _count_json(school_dir / "courses.json"),
                "n_facts": _count_json(school_dir / "facts.json"),
                "n_texts": len(list((school_dir / "texts").rglob("*.txt")))
                if (school_dir / "texts").exists() else 0,
                "n_installed_ever": installed_history.get(school_dir.name, 0),
            }
            if manifest.exists():
                try:
                    payload = json.loads(manifest.read_text(encoding="utf-8"))
                    info["notes"] = payload.get("notes") or []
                    info["last_import_at"] = payload.get("imported_at") or ""
                except json.JSONDecodeError:
                    pass
            schools.append(info)
    return {"root": str(root.relative_to(Path(project_root).resolve()).as_posix()), "schools": schools}


def _count_json(path: Path) -> int:
    if not path.exists():
        return 0
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return 0
    return len(payload) if isinstance(payload, list) else 0


def _harvested_sources(school_dir: Path) -> int:
    """该校收割数据实际引用到的 ``data/source`` 原始件数量（自证式，不依赖可变计数）。"""
    sources: set[str] = set()
    for name in ("courses.json", "facts.json"):
        path = school_dir / name
        if not path.exists():
            continue
        try:
            rows = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        for row in rows:
            value = str(row.get("source_document") or "")
            if value.startswith("data/source/"):
                sources.add(value)
    return len(sources)


def resolve_school_domain(project_root: Path, school: str) -> str:
    """按本地已核实域名台账解析官方域名（``data/harvest/domains.json``）。"""
    path = harvest_root(project_root) / "domains.json"
    if not path.exists():
        return ""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return ""
    if isinstance(payload, dict):
        entry = payload.get(school)
        if isinstance(entry, str):
            return entry
        if isinstance(entry, dict):
            return str(entry.get("domain") or "")
        for value in payload.values():
            if isinstance(value, dict) and value.get("school") == school:
                return str(value.get("domain") or "")
    if isinstance(payload, list):
        for item in payload:
            if isinstance(item, dict) and item.get("school") == school:
                return str(item.get("domain") or "")
    return ""


def run_plugin_harvest(settings, school: str, *, domain: str | None = None,
                       kinds: Iterable[str] | None = None,
                       pages: list[dict[str, str]] | None = None,
                       out: str | Path | None = None,
                       timeout_s: int | None = None):
    """跑一次插件收割并入库；返回 (outcome, import_result)。"""
    from .harvest import HarvestClient, HarvestConfig, HarvestImporter

    config = HarvestConfig.from_settings(settings)
    domain = domain or config.resolve_domain(school)
    if not domain:
        raise SourceModeError(
            f"未核实 {school} 的官方域名：插件红线是「绝不猜域名」。"
            f"请把域名写入 {config.domains_path().as_posix()} 或显式传入。"
        )
    with HarvestClient(config) as client:
        if pages:
            # 入口 B：大站/被 WAF 挡时，由上层用联网搜索定位承载页，插件只做枚举+下载
            outcome = client.harvest_pages(school, domain, pages, out=out, timeout_s=timeout_s)
        else:
            outcome = client.harvest(school, domain, kinds=kinds, out=out, timeout_s=timeout_s)
    importer = HarvestImporter(settings.project_root)
    import_result = importer.import_outcome(outcome)
    return outcome, import_result


def import_replay(settings, out_dir: str | Path, *, school: str = "") -> tuple[Any, Any]:
    """离线回放一个既有收割目录（测试/断网），不启动插件、不联网。"""
    from .harvest import HarvestClient, HarvestImporter

    outcome = HarvestClient.replay(out_dir, school=school)
    importer = HarvestImporter(settings.project_root)
    return outcome, importer.import_outcome(outcome)


def carrier_pages_from(out_dir: str | Path, *, limit: int = 15) -> list[dict[str, str]]:
    """从插件 discover 产物里取出**承载页**列表（入口 B 的入参）。

    读 ``jobs.json``（已确认候选，带 ``page`` 承载页与 ``kind``）；它为空时退回
    ``discover_report.json`` 的 ``pages``（已扫描到的栏目页，kind 交给插件自判）。
    取不到就返回空列表——不猜 URL。
    """
    base = Path(out_dir)
    pages: dict[str, str] = {}
    jobs_path = base / "jobs.json"
    if jobs_path.exists():
        try:
            jobs = json.loads(jobs_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            jobs = []
        for job in jobs if isinstance(jobs, list) else []:
            if not isinstance(job, dict):
                continue
            url = str(job.get("page") or "").strip()
            if url and url not in pages:
                pages[url] = str(job.get("kind") or "")
    if not pages:
        report_path = base / "discover_report.json"
        if report_path.exists():
            try:
                report = json.loads(report_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                report = {}
            # 注意：`discover_report.json` 的 `pages` 是**扫描页数（int）**，不是 URL 列表；
            # 真正的候选在 `hits`（[(url, kind, text), …]，也兼容 dict 形式）。
            hits = report.get("hits") if isinstance(report, dict) else None
            for item in hits if isinstance(hits, list) else []:
                if isinstance(item, dict):
                    url, kind = item.get("url"), item.get("kind")
                elif isinstance(item, (list, tuple)) and item:
                    url = item[0]
                    kind = item[1] if len(item) > 1 else ""
                else:
                    continue
                text = str(url or "").strip()
                if text and text not in pages:
                    pages[text] = str(kind or "")
    return [{"url": url, "kind": kind} for url, kind in list(pages.items())[:limit]]


def run_plugin_entry_b(settings, school: str, *, domain: str | None = None,
                       kinds: Iterable[str] | None = None,
                       out: str | Path | None = None,
                       timeout_s: int | None = None):
    """入口 B 自动化：先 discover 定位承载页，再 ``harvest_pages`` 下载并入库。

    这是"插件跑完但没解析出材料"时的自主重试路径——Agent 不需要人工去找 URL。
    返回 ``(outcome, import_result, info)``；没找到承载页时 ``outcome`` 为 discover 的结果，
    ``info["reason"]`` 写明原因，绝不假装采到。
    """
    from .harvest import HarvestClient, HarvestConfig, HarvestImporter

    config = HarvestConfig.from_settings(settings)
    domain = domain or config.resolve_domain(school)
    if not domain:
        raise SourceModeError(
            f"未核实 {school} 的官方域名：插件红线是「绝不猜域名」。"
            f"请把域名写入 {config.domains_path().as_posix()} 或显式传入。"
        )
    importer = HarvestImporter(settings.project_root)
    with HarvestClient(config) as client:
        discovered = client.discover(school, domain, kinds=kinds, out=out, timeout_s=timeout_s)
        pages = carrier_pages_from(discovered.out_dir)
        info: dict[str, Any] = {
            "entry": "B",
            "discover_state": discovered.state,
            "discover_out": discovered.out_dir,
            "n_carrier_pages": len(pages),
            "carrier_pages": pages[:15],
        }
        if not pages:
            info["reason"] = ("插件 discover 未找到可用承载页（站点可能被 WAF 拦截或结构变化）；"
                              "已保留 discover 产物供人工核对")
            return discovered, importer.import_outcome(discovered), info
        outcome = client.harvest_pages(school, domain, pages, out=out, timeout_s=timeout_s)
    imported = importer.import_outcome(outcome)
    info["n_materials"] = int(getattr(outcome, "n_materials", 0) or 0)
    return outcome, imported, info

"""自动补采：每次分析都按插件流程把**相关材料尽量采全**。

设计目标（来自用户反馈）：不要"抓到一个教学计划就收手"。

流程：

1. **定目标**：点名院校 + 同类院校（`edumatch/peers.py`，可解释排序，不是排行榜）；
2. **定材料**：默认穷举插件支持的全部类型
   ``培养方案 / 专业介绍 / 课程大纲 / 年度报告 / 就业质量报告 / 教学质量报告``；
3. **定域名**：只从已核实台账 `data/harvest/domains.json` 取；缺域名时**不猜**，
   记录 ``no_domain`` 并给出 `scripts/resolve_school_domains.py` 的核实命令；
4. **逐个目标 × 材料类型**调插件（`run_plugin_harvest`，入口 A 全站/栏目；
   失败再按插件文档走入口 B 承载页直采）；
5. **采完复核**：用 `coverage_pipeline` 重新审计目标校材料状态，
   仍然缺的材料写进 `next_actions`，不假装采到了。

任何一步失败都不会抛异常中断分析：结果里如实记录 ``status / reason``。
"""

from __future__ import annotations

import json
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

#: 插件支持的材料类型（穷举，不"抓一个就完"）。
ALL_KINDS: tuple[str, ...] = (
    "培养方案", "专业介绍", "课程大纲", "年度报告", "就业质量报告", "教学质量报告",
)

#: 与需求侧最相关、缺了就影响结论的材料（用于判定"还要不要继续采"）。
CRITICAL_KINDS: tuple[str, ...] = ("培养方案", "专业介绍", "课程大纲", "就业质量报告")

#: 持久化补采台账：多次调用**累积**，支持"一轮只采一所、多轮把区域采全"。
LEDGER_REL = ("data", "harvest", "auto_harvest_ledger.json")

#: 本地优先：先看 ``data/source/<目录>/<院校>/`` 里已经有什么，只对**本地没有**的材料类型联网。
#: 这是用户明确要求的顺序——「先充分调用本地数据，再自行调用插件检索下载更多数据」。
LOCAL_DIR_BY_KIND: dict[str, tuple[str, ...]] = {
    "培养方案": ("培养方案",),
    "专业介绍": ("专业介绍",),
    "课程大纲": ("课程大纲",),
    "年度报告": ("年度报告",),
    "就业质量报告": ("年度报告",),
    "教学质量报告": ("年度报告",),
}

#: 年度报告目录下按子目录再细分，避免"有就业质量报告"被当成"有教学质量报告"。
LOCAL_SUBDIR_BY_KIND: dict[str, str] = {
    "就业质量报告": "就业质量报告",
    "教学质量报告": "教学质量报告",
}


def local_material_counts(project_root: Path, school: str) -> dict[str, int]:
    """统计该校在本地 ``data/source`` 里各材料类型已有多少份文件。"""
    root = Path(project_root) / "data" / "source"
    counts: dict[str, int] = {}
    for kind in ALL_KINDS:
        subdir = LOCAL_SUBDIR_BY_KIND.get(kind)
        found = 0
        for name in LOCAL_DIR_BY_KIND.get(kind, ()):
            base = root / name
            if not base.exists():
                continue
            if subdir:
                base = base / school / subdir
                found += sum(1 for p in base.rglob("*") if p.is_file()) if base.exists() else 0
                continue
            for path in base.rglob("*"):
                if (path.is_file() and school in str(path)
                        and "非分析归档" not in str(path)):
                    found += 1
        counts[kind] = found
    return counts


@dataclass
class HarvestAttempt:
    school: str
    domain: str
    kinds: list[str]
    status: str                      # ok | local_only | no_domain | unavailable | error | empty | skipped
    reason: str = ""
    n_materials: int = 0
    by_kind: dict[str, int] = field(default_factory=dict)
    imported: dict[str, Any] = field(default_factory=dict)
    elapsed_s: float = 0.0
    #: 本地已有材料（kind → 文件数）：联网前先看这里，只采本地没有的。
    local_materials: dict[str, int] = field(default_factory=dict)
    #: 实际走了哪个入口：local / A（全站栏目）/ B（承载页直采）
    entry: str = ""
    #: 入口 B 的自主重试信息（承载页数量、discover 状态、失败原因）
    entry_b: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"school": self.school, "domain": self.domain, "kinds": self.kinds,
                "status": self.status, "reason": self.reason,
                "n_materials": self.n_materials, "by_kind": self.by_kind,
                "local_materials": self.local_materials, "entry": self.entry,
                "entry_b": self.entry_b,
                "imported": self.imported, "elapsed_s": round(self.elapsed_s, 1)}


def plan_targets(
    project_root: Path,
    *,
    school: str | None,
    major: str | None,
    peer_max: int = 3,
    peers: Sequence[str] | None = None,
) -> list[str]:
    """点名院校优先，其次同类院校（可解释排序）；去重且保持顺序。"""
    targets: list[str] = []
    if school:
        targets.append(school)
    if peers:
        targets.extend(str(p) for p in peers)
    elif major:
        try:
            from .peers import find_peers

            anchor = school or "北京工业大学"
            found = find_peers(project_root, anchor, major=major, max_peers=peer_max) or {}
            for item in (found.get("peers") or []):
                name = item.get("school") if isinstance(item, dict) else getattr(item, "name", "")
                if name and name not in targets:
                    targets.append(str(name))
        except Exception:  # noqa: BLE001 - 同类校不可用时不影响主流程
            pass
    seen: set[str] = set()
    return [t for t in targets if t and not (t in seen or seen.add(t))]


def load_ledger(project_root: Path) -> dict[str, Any]:
    path = Path(project_root) / Path(*LEDGER_REL)
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def save_ledger(project_root: Path, ledger: dict[str, Any]) -> None:
    path = Path(project_root) / Path(*LEDGER_REL)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(ledger, ensure_ascii=False, indent=2), encoding="utf-8")


def region_targets(
    project_root: Path,
    *,
    major: str | None,
    region: str = "北京市",
    limit: int = 200,
) -> list[str]:
    """区域口径的目标院校：该地区**有该专业材料**的院校（本地目录 + 全国名单交叉）。

    用于宏观层"把区域采全"：一次调用只采一批，多次调用累积到全区域。
    """
    from .coverage_pipeline import discover_target_schools
    from .peers import UniversityCatalog, _local_majors

    names = discover_target_schools(project_root, province=region)
    local = _local_majors(project_root)
    with_major = [n for n in names if major and major in local.get(n, set())]
    others = [n for n in names if n not in with_major]
    return (with_major + others)[:limit]


def auto_harvest(
    settings,
    *,
    school: str | None,
    major: str | None = None,
    peer_max: int = 3,
    peers: Sequence[str] | None = None,
    kinds: Iterable[str] | None = None,
    timeout_s: int | None = None,
    allow_network: bool = True,
    max_targets: int = 6,
    domain_candidates: dict[str, Sequence[str]] | None = None,
    mode: str = "target",
    region: str = "北京市",
    batch_size: int | None = None,
    use_ledger: bool = True,
) -> dict[str, Any]:
    """按插件流程把相关院校的相关材料**尽量采全**，返回可审计台账。

    ``domain_candidates``：大模型自己联网检索到的候选 URL（``{校名: [url, …]}``）。
    系统会按「官方教育域 + HTTP 200 + 页面含校名」核验，通过后写入域名台账再采集；
    本地台账与存档只作辅助，不阻塞"自己找到官网"这条路径。
    """
    from .source_modes import (resolve_school_domain, run_plugin_entry_b,
                               run_plugin_harvest)
    from .domain_discovery import discover_domain

    project_root = Path(getattr(settings, "project_root", ".")).resolve()
    wanted = list(kinds or ALL_KINDS)
    ledger = load_ledger(project_root) if use_ledger else {}
    if mode == "region":
        # 区域口径：目标 = 该地区的高校（有该专业材料的优先），按批次推进、跨调用累积
        pool = region_targets(project_root, major=major, region=region)
        done = {s for s, rec in (ledger.get("schools") or {}).items()
                if rec.get("status") in {"ok", "local_only"}}
        pending = [s for s in pool if s not in done]
        size = batch_size or max_targets
        targets = pending[:size]
        mode_note = (f"区域口径（{region}）：目标池 {len(pool)} 所，已完成 {len(done)} 所，"
                     f"本轮补采 {len(targets)} 所，剩余 {max(len(pending) - len(targets), 0)} 所"
                     "——**再调一次即可继续采下一批**")
    else:
        targets = plan_targets(project_root, school=school, major=major,
                               peer_max=peer_max, peers=peers)[:max_targets]
        mode_note = ("目标口径：点名院校 + 同类院校（每轮都按台账跳过已采成功的）")
        done = {s for s, rec in (ledger.get("schools") or {}).items()
                if rec.get("status") in {"ok", "local_only"}}
        if school and school in done and not batch_size:
            targets = [t for t in targets if t not in done] or targets
    attempts: list[HarvestAttempt] = []
    discovery: list[dict[str, Any]] = []
    started = time.time()
    for name in targets:
        candidates = list((domain_candidates or {}).get(name) or [])
        if candidates:
            found = discover_domain(project_root, name, candidates=candidates,
                                    allow_network=allow_network)
            discovery.append({"school": name, **{k: found.get(k) for k in
                                                 ("ok", "domain", "source", "reason")},
                              "tried": found.get("tried") or []})
        domain = resolve_school_domain(project_root, name)
        attempt = HarvestAttempt(school=name, domain=domain, kinds=wanted, status="")
        # —— 本地优先：先看 data/source 里已经有什么，只对"本地没有"的材料类型联网 ——
        local = local_material_counts(project_root, name)
        attempt.local_materials = local
        missing_kinds = [k for k in wanted if not local.get(k)]
        attempt.kinds = missing_kinds or list(wanted)
        if not missing_kinds:
            attempt.status = "local_only"
            attempt.entry = "local"
            attempt.n_materials = sum(local.values())
            attempt.reason = ("本地 data/source 已覆盖全部材料类型，"
                              "未发起联网请求（避免重复下载）。")
            attempts.append(attempt)
            continue
        if not domain:
            attempt.status = "no_domain"
            attempt.reason = (
                "本地台账没有该院校域名。**请先联网检索该校官网（或承载页）URL**，"
                f"再交给系统核验：python scripts\\discover_school_domain.py --school \"{name}\" "
                "--candidate <你检索到的官方 URL>"
                "（核验标准：官方教育域后缀 + HTTP 200 + 页面含校名；通过后自动写入台账）")
            attempts.append(attempt)
            continue
        if not allow_network:
            attempt.status = "skipped"
            attempt.reason = "本次以 allow_network=False 运行（离线复现），未发起联网采集。"
            attempts.append(attempt)
            continue
        t0 = time.time()
        try:
            outcome, imported = run_plugin_harvest(
                settings, name, domain=domain, kinds=missing_kinds, timeout_s=timeout_s)
            attempt.elapsed_s = time.time() - t0
            by_kind = getattr(outcome, "by_kind", None) or {}
            attempt.by_kind = dict(by_kind) if isinstance(by_kind, dict) else {}
            attempt.n_materials = int(getattr(outcome, "n_materials", 0) or 0)
            attempt.imported = {
                "installed": list(getattr(imported, "installed", []) or [])[:20],
                "courses_added": len(getattr(imported, "courses", []) or []),
                "sources_added": len(getattr(imported, "sources", []) or []),
            }
            attempt.entry = "A"
            if attempt.n_materials:
                attempt.status = "ok"
            else:
                # —— 入口 A 没采到：**自主**转入口 B（discover 定位承载页 → 直采），
                #    不让用户/上层 Agent 手工去找 URL。——
                attempt.status = "empty"
                attempt.reason = "入口 A（全站/栏目）未解析出材料，已自动转入口 B 重试"
                b_outcome, b_imported, b_info = run_plugin_entry_b(
                    settings, name, domain=domain, kinds=missing_kinds, timeout_s=timeout_s)
                attempt.entry = "B"
                attempt.entry_b = b_info
                b_materials = int(getattr(b_outcome, "n_materials", 0) or 0)
                if b_materials:
                    attempt.status = "ok"
                    attempt.reason = (f"入口 A 未采到；入口 B（承载页直采 "
                                      f"{b_info.get('n_carrier_pages', 0)} 个承载页）"
                                      f"采到 {b_materials} 份。")
                    attempt.n_materials = b_materials
                    b_by_kind = getattr(b_outcome, "by_kind", None) or {}
                    attempt.by_kind = dict(b_by_kind) if isinstance(b_by_kind, dict) else {}
                    attempt.imported = {
                        "installed": list(getattr(b_imported, "installed", []) or [])[:20],
                        "courses_added": len(getattr(b_imported, "courses", []) or []),
                        "sources_added": len(getattr(b_imported, "sources", []) or []),
                    }
                else:
                    attempt.reason = ("入口 A 与入口 B 均未采到材料：" 
                                      + str(b_info.get("reason")
                                            or "站点不可达/被 WAF 拦截/结构变化"))
            attempt.elapsed_s = time.time() - t0
        except Exception as exc:  # noqa: BLE001 - 单校失败不中断
            attempt.elapsed_s = time.time() - t0
            attempt.status = "error"
            # 只留一句话会丢现场：把最后一行调用也记下来，便于定位插件/参数问题。
            tb = traceback.extract_tb(exc.__traceback__)
            where = f"{Path(tb[-1].filename).name}:{tb[-1].lineno}" if tb else "?"
            attempt.reason = f"{type(exc).__name__}: {exc}（{where}）"
        attempts.append(attempt)
    # 统一写台账：**所有**尝试都记录（含 no_domain / skipped / error），
    # 这样多次调用能"跳过已成功的、重试没成功的"，把区域一批批采厚。
    for attempt in attempts:
        ledger.setdefault("schools", {})[attempt.school] = {
            **attempt.to_dict(), "updated_at": datetime.now(timezone.utc).isoformat()}
    if use_ledger:
        ledger["updated_at"] = datetime.now(timezone.utc).isoformat()
        ledger["mode"] = mode
        ledger["region"] = region
        ledger["major"] = major or ""
        if mode == "region":
            pool = region_targets(project_root, major=major, region=region)
            ok = {s for s, rec in (ledger.get("schools") or {}).items()
                  if rec.get("status") in {"ok", "local_only"}}
            ledger["region_progress"] = {"pool": len(pool), "done": len(ok),
                                         "remaining": len([s for s in pool if s not in ok])}
        save_ledger(project_root, ledger)

    # 采完复核：目标校还缺哪些关键材料
    coverage: dict[str, Any] = {}
    if school:
        try:
            from .coverage_pipeline import audit_university_coverage

            coverage = audit_university_coverage(project_root, major=major or "人工智能",
                                                 schools=[school])
        except Exception as exc:  # noqa: BLE001
            coverage = {"status": "unavailable", "reason": f"{type(exc).__name__}: {exc}"}
    missing: list[str] = []
    if coverage:
        info = (coverage.get("per_school") or {}).get(school or "") or {}
        missing = list(info.get("missing_materials") or [])

    ok = [a for a in attempts if a.status == "ok"]
    local_only = [a for a in attempts if a.status == "local_only"]
    return {
        "school": school or "", "major": major or "",
        "targets": targets, "kinds": wanted,
        "n_targets": len(targets), "n_ok": len(ok),
        "n_local_only": len(local_only),
        "n_materials": sum(a.n_materials for a in attempts),
        "attempts": [a.to_dict() for a in attempts],
        "coverage_after": coverage,
        "domain_discovery": discovery,
        "still_missing_materials": missing,
        "next_actions": _next_actions(attempts, missing, school, major),
        "elapsed_s": round(time.time() - started, 1),
        "mode": mode, "mode_note": mode_note,
        "ledger_path": str(Path(*LEDGER_REL).as_posix()),
        "region_progress": ledger.get("region_progress") or {},
        "note": ("自动补采：点名院校 + 同类院校 × 全部材料类型（"
                 + "、".join(wanted) + "）；**先本地、后联网**——本地已有该类型就跳过网络；"
                 "入口 A（全站/栏目）没采到会自动转入口 B（承载页直采）；"
                 "失败逐条记录原因，不猜域名、不假装采到。"),
    }


def _next_actions(attempts: Sequence[HarvestAttempt], missing: Sequence[str],
                  school: str | None, major: str | None) -> list[str]:
    actions: list[str] = []
    for attempt in attempts:
        if attempt.status == "no_domain":
            actions.append(f"核实 {attempt.school} 的官方域名后重采"
                           "（scripts\\resolve_school_domains.py，需 HTTP 200 且页面出现校名）")
        elif attempt.status == "empty":
            n_pages = (attempt.entry_b or {}).get("n_carrier_pages")
            if n_pages:
                actions.append(
                    f"{attempt.school}：入口 A 与入口 B 均已自动重试仍未采到"
                    f"（已发现 {n_pages} 个承载页）——站点可能被 WAF 拦截或正文不可解析，"
                    "用插件 discover 产物人工复核后再决定")
            elif attempt.entry == "B":
                actions.append(
                    f"{attempt.school}：入口 A 已自动重试入口 B，但插件 discover "
                    "未找到可用承载页（站点结构变化/被拦截）——核对域名与官网栏目后重采")
            else:
                actions.append(
                    f"{attempt.school}：入口 A 未解析出材料（本台账若来自旧版流程，"
                    "说明当时还没有入口 B 自动重试）；新版运行会自动转入口 B 承载页直采。")
        elif attempt.status == "error":
            actions.append(f"{attempt.school}：插件采集异常，核对域名与网络后重采")
    if missing:
        actions.append("目标校仍缺材料：" + "、".join(missing)
                       + "；入口 A/B 已自动重试，仍未采到需人工核对官网栏目或放宽采集范围")
    if not actions:
        actions.append("相关院校的相关材料已按插件流程采全；如需补充更多同类院校，"
                       "调大 --auto-harvest-peer-max")
    return actions


def render_auto_harvest_markdown(payload: dict[str, Any], *, limit: int = 20) -> list[str]:
    """把自动补采台账渲染成报告小节。"""
    if not payload:
        return []
    lines = ["## 自动补采台账（插件流程）", "",
             f"- 目标院校 {payload.get('n_targets', 0)} 所："
             + "、".join(payload.get("targets") or []) or "—",
             f"- 采集材料类型：{'、'.join(payload.get('kinds') or [])}",
             f"- 联网采到 {payload.get('n_ok', 0)} 所，本地已覆盖跳过联网 "
             f"{payload.get('n_local_only', 0)} 所，累计材料 {payload.get('n_materials', 0)} 份，"
             f"耗时 {payload.get('elapsed_s', 0)}s",
             "- 顺序：**先本地 `data/source`（本地已有该材料类型则跳过网络）→ 入口 A 全站/栏目"
             "→ 入口 A 无果时自动转入口 B 承载页直采**。",
             "", "| 院校 | 域名 | 入口 | 状态 | 本地已有 | 采到材料 | 说明 |",
             "| --- | --- | --- | --- | --- | ---: | --- |"]
    for attempt in (payload.get("attempts") or [])[:limit]:
        local = attempt.get("local_materials") or {}
        local_txt = "、".join(f"{k}{v}" for k, v in local.items() if v) or "—"
        lines.append(f"| {attempt.get('school')} | {attempt.get('domain') or '—'} | "
                     f"{attempt.get('entry') or '—'} | {attempt.get('status')} | {local_txt} | "
                     f"{attempt.get('n_materials', 0)} | "
                     f"{(attempt.get('reason') or '')[:70]} |")
    if payload.get("still_missing_materials"):
        lines += ["", "- 采后仍缺材料：" + "、".join(payload["still_missing_materials"])]
    if payload.get("next_actions"):
        lines += ["", "**下一步动作**："] + [f"- {a}" for a in payload["next_actions"]]
    lines.append("")
    return lines

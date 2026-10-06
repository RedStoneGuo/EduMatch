"""供给端数据来源工具组：本地索引查询 + 插件收割（local / plugin / hybrid）。"""

from __future__ import annotations

from typing import Any

from edumatch.dataset import Dataset
from edumatch.local_supply import LocalSupplyIndex


def _obj(**props: Any) -> dict[str, Any]:
    return {"type": "object", "properties": props, "additionalProperties": False}


def _index(root: str) -> LocalSupplyIndex:
    from pathlib import Path

    return LocalSupplyIndex.load(Path(root))


def query_local_supply(ds: Dataset, args: dict[str, Any]) -> dict[str, Any]:
    """按院校/材料类型/专业定点检索 data/source 的本地材料。"""
    index = _index(str(ds.settings.project_root))
    school = args.get("school")
    material_type = args.get("material_type")
    major = args.get("major")
    if not school and not material_type and not major:
        profile = index.school_profile(school) if school else None
        return {"coverage": index.coverage(), "profile": profile}
    if school and not material_type and not major:
        return index.school_profile(str(school))
    rows = index.materials(school=str(school) if school else None,
                           material_type=str(material_type) if material_type else None,
                           major=str(major) if major else None)
    return {
        "n": len(rows),
        "school": school,
        "material_type": material_type,
        "major": major,
        "materials": [r.to_dict() for r in rows[:200]],
        "evidence_level": "A",
    }


def local_supply_coverage(ds: Dataset, args: dict[str, Any]) -> dict[str, Any]:
    return _index(str(ds.settings.project_root)).coverage()


def harvest_status(ds: Dataset, args: dict[str, Any]) -> dict[str, Any]:
    from edumatch.source_modes import harvest_status as status

    return status(ds.settings.project_root)


def harvest_school_materials(ds: Dataset, args: dict[str, Any]) -> dict[str, Any]:
    """联网跑插件收割指定院校并入库（可能耗时数分钟；失败如实返回原因）。"""
    from edumatch.source_modes import run_plugin_harvest

    school = str(args.get("school") or "").strip()
    if not school:
        return {"status": "error", "reason": "缺少 school"}
    try:
        outcome, import_result = run_plugin_harvest(
            ds.settings, school, domain=args.get("domain"),
            kinds=args.get("kinds"), timeout_s=args.get("timeout_s"),
        )
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "reason": f"{type(exc).__name__}: {exc}"}
    return {"status": "ok", "outcome": outcome.to_dict(), "import": import_result.to_dict()}


def find_peer_schools(ds: Dataset, args: dict[str, Any]) -> dict[str, Any]:
    """按全国高校名单判定同类院校（层次/地域/校型/可采集性，可解释排序）。"""
    from edumatch.peers import find_peers

    school = str(args.get("school") or "").strip()
    if not school:
        return {"status": "error", "reason": "缺少 school"}
    return find_peers(ds.settings.project_root, school,
                      major=args.get("major"), max_peers=int(args.get("max_peers") or 5),
                      require_domain=bool(args.get("require_domain")))


def harvest_peer_schools(ds: Dataset, args: dict[str, Any]) -> dict[str, Any]:
    """采集同类院校材料并入库（只采已核实官方域名的院校；可能耗时数分钟）。"""
    from edumatch.harvest import HarvestImporter
    from edumatch.peers import PeerSelector
    from edumatch.source_modes import run_plugin_harvest

    school = str(args.get("school") or "").strip()
    if not school:
        return {"status": "error", "reason": "缺少 school"}
    kinds = args.get("kinds") or ["培养方案"]
    selector = PeerSelector.from_project(ds.settings.project_root)
    explicit = args.get("peers")
    if explicit:
        names = [str(x) for x in explicit]
    else:
        peers, _ = selector.resolve(school, major=args.get("major"),
                                    max_peers=int(args.get("max_peers") or 3))
        names = [p.school for p in peers]
    results: list[dict[str, Any]] = []
    for name in names:
        if (ds.settings.project_root / "data" / "harvest" / name / "courses.json").exists():
            results.append({"school": name, "status": "cached"})
            continue
        domain = selector.domains.get(name, "")
        if not domain:
            results.append({"school": name, "status": "missing_domain"})
            continue
        try:
            outcome, imported = run_plugin_harvest(ds.settings, name, domain=domain,
                                                   kinds=kinds, timeout_s=args.get("timeout_s"))
            results.append({"school": name, "status": "ok", "downloaded": outcome.n_materials,
                            "installed": len(imported.installed), "courses": imported.n_courses})
        except Exception as exc:  # noqa: BLE001
            results.append({"school": name, "status": "error", "error": f"{type(exc).__name__}: {exc}"})
    return {"status": "ok", "target": school, "results": results}


def resolve_school_domain(ds: Dataset, args: dict[str, Any]) -> dict[str, Any]:
    """实测核实一所院校的官方域名并写入台账（插件不猜域名）。"""
    import importlib.util

    script = ds.settings.project_root / "scripts" / "resolve_school_domains.py"
    if not script.exists():
        return {"status": "error", "reason": "缺少 scripts/resolve_school_domains.py"}
    spec = importlib.util.spec_from_file_location("resolve_school_domains", script)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    school = str(args.get("school") or "").strip()
    domain = str(args.get("domain") or "").strip()
    if not (school and domain):
        return {"status": "error", "reason": "需要 school 与 domain"}
    result = module.verify(school, domain)
    if result.get("ok"):
        payload = module._load()
        payload[school] = {"domain": domain, "all_domains": [domain],
                           "n_source_urls": payload.get(school, {}).get("n_source_urls", 0),
                           "ledgers": payload.get(school, {}).get("ledgers", []),
                           "evidence": result["evidence"] + "（工具实测确认）",
                           "verified_at": result["verified_at"]}
        module._save(payload)
    return result


def specs():
    from .registry import ToolSpec

    return [
        ToolSpec("query_local_supply", "supply_source",
                 "检索本地 data/source 材料（按院校/数据类型/专业）；不带参数时返回覆盖率审计",
                 _obj(school={"type": ["string", "null"]},
                      material_type={"type": ["string", "null"]},
                      major={"type": ["string", "null"]}),
                 query_local_supply, returns="material list with coverage"),
        ToolSpec("local_supply_coverage", "supply_source",
                 "本地 data/source 的利用率审计（每份材料是否连到结构化产物/正文缓存）",
                 _obj(), local_supply_coverage),
        ToolSpec("harvest_status", "supply_source",
                 "已入库的插件收割产物清单（离线可查）", _obj(), harvest_status),
        ToolSpec("harvest_school_materials", "supply_source",
                 "用 edu-material-harvest 插件联网收割指定院校材料并入库（需已核实官方域名）",
                 _obj(school={"type": "string"},
                      domain={"type": ["string", "null"]},
                      kinds={"type": ["array"], "items": {"type": "string"}},
                      timeout_s={"type": ["integer", "null"]}),
                 harvest_school_materials),
        ToolSpec("find_peer_schools", "supply_source",
                 "按全国高校名单判定某校的同类院校（层次/地域/校型排序，可解释），含域名缺口清单",
                 _obj(school={"type": "string"},
                      major={"type": ["string", "null"]},
                      max_peers={"type": ["integer", "null"]},
                      require_domain={"type": ["boolean", "null"]}),
                 find_peer_schools, returns="peer candidates with reasons"),
        ToolSpec("harvest_peer_schools", "supply_source",
                 "采集同类院校材料并入库（只采已核实域名的；供 peer benchmark 使用）",
                 _obj(school={"type": "string"},
                      major={"type": ["string", "null"]},
                      peers={"type": ["array"], "items": {"type": "string"}},
                      kinds={"type": ["array"], "items": {"type": "string"}},
                      max_peers={"type": ["integer", "null"]},
                      timeout_s={"type": ["integer", "null"]}),
                 harvest_peer_schools),
        ToolSpec("resolve_school_domain", "supply_source",
                 "实测核实院校官方域名并写入台账（HTTP 200 且页面出现校名才通过）",
                 _obj(school={"type": "string"}, domain={"type": "string"}),
                 resolve_school_domain),
    ]

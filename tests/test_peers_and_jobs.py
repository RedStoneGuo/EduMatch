"""同类院校检索（全国口径）与按专业岗位语料并表。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from edumatch.dataset import Dataset
from edumatch.harvest import HarvestClient, HarvestImporter
from edumatch.peers import (PeerSelector, UniversityCatalog, find_peers, region_of,
                            school_category)

ROOT = Path(__file__).resolve().parents[1]


# ---------- 全国院校名单 ----------

def test_catalog_loads_national_list_with_tiers():
    catalog = UniversityCatalog.load(ROOT)
    assert len(catalog.schools) > 2900
    assert len(catalog.provinces()) >= 30
    pku = catalog.by_name["北京大学"]
    assert "985" in pku.tiers and "211" in pku.tiers
    bjut = catalog.by_name["北京工业大学"]
    assert bjut.tiers == ("211",)
    assert bjut.province == "北京市"


def test_school_category_and_region_helpers():
    assert school_category("北京工业大学") == "理工"
    assert school_category("北京师范大学") == "师范"
    assert school_category("中央财经大学") == "财经"
    assert region_of("北京市") == "华北"
    assert region_of("湖北省") == "华中"
    assert region_of("广东省") == "华南"


# ---------- 同类院校检索 ----------

def test_peers_exclude_self_and_prefer_same_tier_and_city():
    selector = PeerSelector.from_project(ROOT)
    peers, note = selector.resolve("北京工业大学", major="人工智能", max_peers=5)
    assert note["status"] == "ok"
    names = [p.school for p in peers]
    assert "北京工业大学" not in names
    assert all(p.province == "北京市" for p in peers), "同城同层次应排在前面"
    assert all(p.tiers and "211" in p.tiers for p in peers)
    assert all(p.reasons for p in peers)


def test_peers_are_nationwide_not_beijing_only():
    selector = PeerSelector.from_project(ROOT)
    peers, _ = selector.resolve("华中科技大学", major="机械工程", max_peers=6)
    provinces = {p.province for p in peers}
    assert provinces & {"湖北省", "湖南省"}, f"应能跨省取同类校，实际 {provinces}"
    assert len(provinces) >= 2


def test_peers_require_domain_filters_unharvestable():
    selector = PeerSelector.from_project(ROOT)
    all_peers, _ = selector.resolve("华中科技大学", max_peers=20)
    with_domain, _ = selector.resolve("华中科技大学", max_peers=20, require_domain=True)
    assert all(p.harvestable for p in with_domain)
    assert len(with_domain) <= len(all_peers)
    assert any(not p.harvestable for p in all_peers), "外地院校应有域名缺口（如实暴露）"


def test_peers_report_missing_domain_and_unknown_target():
    report = find_peers(ROOT, "华中科技大学", max_peers=5)
    assert report["status"] == "ok"
    assert report["missing_domain"], "未核实域名的候选必须列出来，不能静默"
    missing = find_peers(ROOT, "不存在的野鸡大学")
    assert missing["status"] == "target_not_found"
    assert missing["peers"] == []


# ---------- 按专业岗位语料 ----------

def test_major_export_corpus_is_isolated_from_legacy_funnel():
    ds = Dataset.build()
    # 专业作用域语料现在**按专业分文件**存储（data/processed/major_jobs/），
    # 惰性加载，不再混在 jobs.json 里；这里核对总量与隔离性。
    assert ds._major_export_total() > 10000, "按专业导出的岗位表应已并入"
    assert all(j.get("corpus") != "major_export" for j in ds.jobs), \
        "通用语料文件里不应再混入专业作用域行"
    assert any(j.get("search_keyword") for j in ds.jobs), "通用语料仍需带检索词"
    index = ds._major_jobs_dir() / "_index.json"
    assert index.exists() and len(json.loads(index.read_text(encoding="utf-8"))) >= 60
    # 既有 AI/计算机口径不受影响：target 只含通用语料（带检索词、非 major_export）
    assert len(ds.target_jobs()) > 10000
    assert all(j.get("corpus") != "major_export" for j in ds.target_jobs())
    # 同城基线：旧布局是 HAR 的 53 条；合并后通用语料没有"不带检索词"的行，
    # 退到全量招聘表的 2 万条同城抽样（口径已在 jobs_meta 披露）。
    assert len(ds.baseline_jobs()) > 0


def test_major_scope_selection_is_professional_not_keyword_based():
    ds = Dataset.build()
    assert len(ds.major_scope_jobs("机械工程")) > 100
    assert len(ds.major_scope_jobs("建筑学")) > 100
    # v2 总表已把人工智能也按专业导出（905 条）；关键是两者**物理隔离**：
    # 通用语料（target_jobs）不受专业作用域行影响。
    assert len(ds.major_scope_jobs("人工智能")) > 100
    assert all(j.get("corpus") != "major_export" for j in ds.target_jobs())
    demands = ds.demand_vector(major="机械工程")
    assert len(demands) > 5
    assert "按专业导出语料" in ds.demand_scope_note


# ---------- 收割件的类型闸门 ----------

def test_importer_quarantines_suspect_doc_as_curriculum(tmp_path):
    """站点表格页被误判为"培养方案"时，隔离开，不进分析语料。"""
    replay = tmp_path / "replay" / "某某大学"
    target = replay / "新增数据" / "某某大学" / "培养方案"
    target.mkdir(parents=True)
    (target / "某某大学课表模版.doc").write_bytes(b"\xd0\xcf\x11\xe0fake-doc")
    (replay / "records.json").write_text(json.dumps([{
        "school": "某某大学", "kind": "培养方案", "desc": "某某大学课表模版",
        "year": "", "file": "某某大学/培养方案/某某大学课表模版.doc",
        "size_mb": 0.1, "sha1": "", "status": "新增", "url": "https://x", "page": "https://y",
    }], ensure_ascii=False), encoding="utf-8")

    project = tmp_path / "project"
    outcome = HarvestClient.replay(replay, school="某某大学")
    result = HarvestImporter(project).import_outcome(outcome)
    corpus = project / "data" / "source" / "培养方案" / "某某大学"
    quarantine = project / "data" / "source" / "非分析归档" / "疑似误判" / "某某大学"
    assert not corpus.exists(), "疑似类型误判的材料不得进入培养方案语料"
    assert (quarantine / "某某大学课表模版.doc").exists()
    assert any("疑似类型误判" in n for n in result.notes)

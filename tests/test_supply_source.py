"""供给端数据来源：本地索引 / 插件收割入库 / local-plugin-hybrid 三模式。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from edumatch.dataset import Dataset
from edumatch.harvest import HarvestClient, HarvestImporter
from edumatch.local_supply import LocalSupplyIndex, canonical_school
from edumatch.source_modes import (SourceModeError, load_harvest_bundle, normalize_mode,
                                   uses_harvest, uses_local)

ROOT = Path(__file__).resolve().parents[1]
REPLAY = ROOT / "demo" / "harvest_replay" / "北京工业大学"


# ---------- 模式解析 ----------

def test_mode_names_and_aliases():
    assert normalize_mode(None) == "local"
    assert normalize_mode("plugin") == "plugin"
    assert normalize_mode("混合") == "hybrid"
    assert uses_local("hybrid") and uses_harvest("hybrid")
    assert not uses_local("plugin") and uses_harvest("plugin")
    with pytest.raises(SourceModeError):
        normalize_mode("nope")


# ---------- 院校名归一 ----------

def test_school_name_normalization_covers_pdf_truncation():
    assert canonical_school("中国矿业大学") == "中国矿业大学（北京）"
    assert canonical_school("中国地质大学(北京)") == "中国地质大学（北京）"
    assert canonical_school("北京工业大学") == "北京工业大学"


# ---------- 本地索引 ----------

def test_local_index_covers_every_material_type_and_links():
    index = LocalSupplyIndex.load(ROOT)
    coverage = index.coverage()
    assert coverage["n_schools"] >= 20
    assert coverage["link_rate"] > 0.9
    # 每份没连上的材料都必须有如实原因，不能静默
    for record in index.records:
        if record.in_analysis and not (record.derived or index.links_for(record.rel_path)):
            assert record.unparsed_reason
    profile = index.school_profile("北京工业大学")
    assert profile["material_counts"].get("培养方案", 0) > 0
    assert profile["n_files"] > 0


def test_local_index_finds_major_level_material():
    index = LocalSupplyIndex.load(ROOT)
    rows = index.materials(school="北京工业大学", material_type="培养方案", major="人工智能")
    assert rows, "本地应有北工大人工智能培养方案"
    assert all("人工智能" in r.file_name or "人工智能" in r.major for r in rows)


# ---------- 插件产物回放与入库 ----------

def test_replay_reads_plugin_records():
    outcome = HarvestClient.replay(REPLAY, school="北京工业大学", domain="bjut.edu.cn")
    assert outcome.backend == "replay"
    assert outcome.n_materials == 1
    assert outcome.by_kind() == {"培养方案": 1}
    assert outcome.records[0]["url"].startswith("https://")


def test_importer_installs_and_parses_harvested_curriculum(tmp_path):
    outcome = HarvestClient.replay(REPLAY, school="北京工业大学", domain="bjut.edu.cn")
    importer = HarvestImporter(tmp_path)
    result = importer.import_outcome(outcome)

    assert result.n_courses > 20, "2024 人工智能培养方案应解析出课程表"
    assert result.n_texts == 1
    installed = tmp_path / "data" / "source" / "培养方案" / "北京工业大学"
    assert any(p.suffix == ".pdf" for p in installed.iterdir())
    courses = json.loads((tmp_path / "data" / "harvest" / "北京工业大学" / "courses.json")
                         .read_text(encoding="utf-8"))
    assert all(row["evidence_level"] == "A" for row in courses)
    assert all(row["source_document"].startswith("data/source/培养方案/") for row in courses)
    manifest = json.loads((tmp_path / "data" / "processed" / "harvest_imports.json")
                          .read_text(encoding="utf-8"))
    assert manifest[-1]["school"] == "北京工业大学"


def test_importer_is_idempotent(tmp_path):
    outcome = HarvestClient.replay(REPLAY, school="北京工业大学")
    first = HarvestImporter(tmp_path).import_outcome(outcome)
    second = HarvestImporter(tmp_path).import_outcome(outcome)
    assert first.n_courses > 0
    assert second.n_courses == 0
    assert second.installed == []
    assert any("同名同内容" in s.get("reason", "") for s in second.skipped)


def test_harvest_bundle_loads_into_dataset_shape(tmp_path):
    outcome = HarvestClient.replay(REPLAY, school="北京工业大学")
    HarvestImporter(tmp_path).import_outcome(outcome)
    bundle = load_harvest_bundle(tmp_path, ["北京工业大学"])
    assert bundle["schools"] == ["北京工业大学"]
    assert bundle["courses"] and bundle["text_roots"]
    course = Dataset._course_from_harvest(bundle["courses"][0])
    assert course.school == "北京工业大学"
    assert course.evidence_level == "A"


def test_missing_school_yields_empty_bundle(tmp_path):
    bundle = load_harvest_bundle(tmp_path, ["不存在的大学"])
    assert bundle == {"courses": [], "facts": [], "text_roots": [], "schools": []}


# ---------- Dataset 三模式装配 ----------

def test_dataset_mode_switch_is_idempotent():
    ds = Dataset.build()
    local_courses = len(ds.courses)
    local_facts = len(ds.facts)
    assert ds.source_mode == "local"
    # hybrid：目标校没有收割产物 → 等价于本地；反复切换不叠加
    ds._apply_source_mode("hybrid", ("不存在的大学",))
    assert len(ds.courses) == local_courses
    ds._apply_source_mode("hybrid", ("不存在的大学",))
    assert len(ds.courses) == local_courses
    assert len(ds.facts) == local_facts
    # plugin：无收割产物 → 供给侧为空（如实记证据不足），需求侧招聘语料不受影响
    ds._apply_source_mode("plugin", ())
    assert ds.courses == [] and ds.facts == []
    assert "data" in ds.settings.processed_dir.as_posix()
    # 切回 local 必须完整还原
    ds._apply_source_mode("local", ())
    assert len(ds.courses) == local_courses
    assert len(ds.facts) == local_facts


def test_plugin_mode_excludes_local_text_roots():
    ds = Dataset.build()
    assert ds.text_roots()
    ds._apply_source_mode("plugin", ())
    assert ds.text_roots() == []


# ---------- 插件可用性 ----------

def test_plugin_vendor_is_present_and_has_mcp_server():
    from edumatch.config import load_settings
    from edumatch.harvest import HarvestConfig

    config = HarvestConfig.from_settings(load_settings())
    assert config.script.exists(), f"缺少插件 MCP 服务端：{config.script}"
    assert config.available()


def test_domain_ledger_is_verified_not_guessed():
    payload = json.loads((ROOT / "data" / "harvest" / "domains.json").read_text(encoding="utf-8"))
    assert payload["北京工业大学"]["domain"] == "bjut.edu.cn"
    assert payload["北京工业大学"]["n_source_urls"] > 0
    assert "采集台账" in payload["北京工业大学"]["evidence"]

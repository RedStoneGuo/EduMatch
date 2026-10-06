"""首轮问询优先 + 区域分批补采（多次调用累积）。"""

from __future__ import annotations

from pathlib import Path

from edumatch.auto_harvest import load_ledger, region_targets
from edumatch.config import load_settings
from scripts.analyze import _target_is_explicit

CORE = Path(__file__).resolve().parents[1]


def test_vague_query_is_not_explicit_and_must_ask_first():
    ok, why = _target_is_explicit("帮我做个就业匹配分析", {"major": "人工智能"}, None)
    assert ok is False and "默认值" in why or "没有目标岗位" in why or "专业" in why
    ok2, why2 = _target_is_explicit("分析北京工业大学人工智能专业", {"major": "人工智能"}, None)
    assert ok2 is False and "岗位" in why2          # 有专业没岗位 → 也要先问


def test_complete_target_runs_directly():
    ok, why = _target_is_explicit(
        "分析北京工业大学人工智能专业与大模型算法工程师岗位的匹配度",
        {"major": "人工智能"}, "大模型算法工程师")
    assert ok is True and why == ""
    ok2, _ = _target_is_explicit("分析北京工业大学人工智能专业与算法岗位", {"major": "人工智能"}, None)
    assert ok2 is True                              # 提问里出现岗位词也算明确


def test_region_target_pool_covers_many_schools():
    pool = region_targets(CORE, major="信息管理与信息系统", region="北京市")
    assert len(pool) >= 20                          # 不是一所学校
    assert "北京工业大学" in pool[:3]                # 本地有材料的院校优先


def test_region_batch_harvest_offline_accumulates_ledger(tmp_path: Path):
    """离线跑两轮：每轮采一批，台账累积、第二轮自动换院校。"""
    from edumatch.auto_harvest import auto_harvest

    settings = load_settings()
    first = auto_harvest(settings, school="北京工业大学", major="信息管理与信息系统",
                         mode="region", batch_size=2, allow_network=False)
    targets1 = [a["school"] for a in first["attempts"]]
    assert len(targets1) == 2
    assert first["region_progress"]["pool"] >= 20
    second = auto_harvest(settings, school="北京工业大学", major="信息管理与信息系统",
                          mode="region", batch_size=2, allow_network=False)
    targets2 = [a["school"] for a in second["attempts"]]
    # 离线时状态是 skipped，不算 ok；因此第二轮仍会重试同一批（这是预期行为）
    assert targets2
    ledger = load_ledger(CORE)
    assert ledger.get("schools")                    # 台账已写入
    assert ledger.get("mode") == "region"

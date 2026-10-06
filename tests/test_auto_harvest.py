"""自动补采：目标规划、材料穷举、离线安全、台账渲染。"""

from __future__ import annotations

from pathlib import Path

from edumatch.auto_harvest import (
    ALL_KINDS,
    CRITICAL_KINDS,
    auto_harvest,
    local_material_counts,
    plan_targets,
    render_auto_harvest_markdown,
)
from edumatch.config import load_settings

CORE = Path(__file__).resolve().parents[1]


def test_all_kinds_is_exhaustive_not_single_material():
    for kind in ("培养方案", "专业介绍", "课程大纲", "就业质量报告", "教学质量报告"):
        assert kind in ALL_KINDS
    assert set(CRITICAL_KINDS) <= set(ALL_KINDS)
    assert len(ALL_KINDS) >= 6


def test_plan_targets_includes_school_and_peers():
    targets = plan_targets(CORE, school="北京工业大学", major="信息管理与信息系统", peer_max=2)
    assert targets[0] == "北京工业大学"
    assert len(targets) >= 2                     # 至少带上同类院校
    assert len(set(targets)) == len(targets)     # 去重


def test_auto_harvest_offline_is_safe_and_actionable():
    payload = auto_harvest(load_settings(), school="北京工业大学",
                           major="信息管理与信息系统", peer_max=1, allow_network=False)
    assert payload["kinds"] == list(ALL_KINDS)   # 默认穷举全部材料类型
    assert payload["n_targets"] >= 1
    assert all(a["status"] in {"skipped", "no_domain", "local_only"}
               for a in payload["attempts"])
    assert payload["next_actions"]
    text = "\n".join(render_auto_harvest_markdown(payload))
    assert "自动补采台账" in text and "材料类型" in text
    assert "先本地" in text or "本地" in text


def test_local_first_order_and_entry_recording():
    """补采必须先看本地 data/source，再决定采哪些材料类型；台账要记清入口。"""
    counts = local_material_counts(CORE, "北京工业大学")
    assert counts["培养方案"] > 0 or counts["课程大纲"] > 0
    payload = auto_harvest(load_settings(), school="北京工业大学",
                           major="信息管理与信息系统", peer_max=1, allow_network=False)
    target = payload["attempts"][0]
    assert target["local_materials"], "必须记录该校本地已有材料数量"
    # 本地已有的材料类型不再请求联网：待采类型是本地为空的那几种
    assert set(target["kinds"]) <= set(ALL_KINDS)
    assert all(target["local_materials"].get(k, 0) == 0 for k in target["kinds"]) or \
        target["status"] == "local_only"
    assert target["entry"] in {"local", "A", "B", ""}


def test_auto_harvest_never_guesses_domain():
    payload = auto_harvest(load_settings(), school="不存在的大学", major="某专业",
                           peer_max=0, allow_network=True)
    statuses = {a["status"] for a in payload["attempts"]}
    assert statuses <= {"no_domain", "skipped"}
    # 没有台账域名时，必须让 Agent **自己去联网检索**并用 --candidate 交回核验，
    # 而不是猜一个域名去采。
    assert all(("联网检索" in a["reason"] and "discover_school_domain" in a["reason"])
               or "allow_network" in a["reason"] for a in payload["attempts"])

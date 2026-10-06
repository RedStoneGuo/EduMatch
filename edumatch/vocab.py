"""技能词表清洗：去掉"看起来很多、其实没信息量"的同类项。

需求/供给词表是从 JD 自由文本自动构建的，天然带两类噪声：

1. **通用词**：问题、场景、制定、内容、结合、前沿、支持、相关…… 这些在任何 JD 里都出现，
   对"这个岗位要什么能力"没有区分度；
2. **近义包含项**：算法 / 算法工程师 / 算法分析、数据 / 数据分析 / 数据工程 —— 同时列出
   会让页面显得"同类项一大堆"，读者无法判断哪个是重点。

本模块提供**确定性**清洗：先按规范形去重，再丢掉通用词，最后合并"一个词是另一个词
前缀/子串且明显更泛"的项（保留更具体的那个）。清洗只影响**展示与列举**，
匹配用的向量仍按原口径计算，并在结果里披露剔除了多少项。
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Mapping

#: 无区分度的通用词（宏观报告本来也披露过"含少量通用词"，这里统一收口）。
GENERIC_TOKENS: frozenset[str] = frozenset({
    "问题", "场景", "制定", "内容", "结合", "前沿", "支持", "相关", "进行", "识别",
    "生成", "使用", "具备", "能力", "工作", "方向", "技术", "方法", "能够", "要求",
    "负责", "熟悉", "掌握", "了解", "沟通", "团队", "经验", "优先", "以上", "以及",
    "其他", "完成", "提供", "实现", "设计", "开发",
})

#: 归一化时要去掉的装饰性字符
_NOISE = re.compile(r"[\s\-_·•、,，。；;：:()（）\[\]【】/\\]+")


def norm_key(skill: str) -> str:
    return _NOISE.sub("", str(skill or "")).lower()


def is_generic(skill: str) -> bool:
    key = norm_key(skill)
    return not key or key in GENERIC_TOKENS


def _merge_containment(names: list[str]) -> tuple[list[str], int]:
    """合并"更泛的子串项"：保留更具体的一个（如 算法分析 ⊃ 算法 → 保留 算法分析）。"""
    ordered = sorted(set(names), key=lambda s: (-len(norm_key(s)), s))
    kept: list[str] = []
    dropped = 0
    for name in ordered:
        key = norm_key(name)
        # 与已保留项互相包含时，丢掉更泛的那个（orders 已保证长词优先）
        if any(key in norm_key(k) or norm_key(k) in key for k in kept):
            # 例外：**短拉丁词**（C / R / Go ⊂ C++ / R语言）不因包含被吞；
            # 中文短词不设例外，否则"算法"会跟着"算法分析"一起留下（用户反馈的同类项噪声）。
            if len(key) <= 2 and key.isascii() and not any(key == norm_key(k) for k in kept):
                kept.append(name)
                continue
            dropped += 1
            continue
        kept.append(name)
    return sorted(kept, key=lambda s: (-len(norm_key(s)), s)), dropped


def clean_vocabulary(
    values: Iterable[str] | Mapping[str, Any],
    *,
    merge_containment: bool = True,
) -> tuple[list[str], dict[str, Any]]:
    """返回（清洗后的技能名列表, 审计信息）。"""
    names = list(values.keys()) if isinstance(values, Mapping) else [str(v) for v in values]
    seen: dict[str, str] = {}
    generic = 0
    for name in names:
        key = norm_key(name)
        if is_generic(name):
            generic += 1
            continue
        seen.setdefault(key, str(name))
    unique = list(seen.values())
    dropped_dup = len(names) - generic - len(unique)
    dropped_contain = 0
    if merge_containment:
        unique, dropped_contain = _merge_containment(unique)
    return unique, {
        "n_in": len(names),
        "n_out": len(unique),
        "dropped_generic": generic,
        "dropped_duplicate": max(dropped_dup, 0),
        "dropped_containment": dropped_contain,
        "note": (f"词表清洗：{len(names)} → {len(unique)} 项"
                 f"（通用词 {generic}、重复 {max(dropped_dup, 0)}、"
                 f"近义包含 {dropped_contain}）；匹配口径不变，仅影响展示与列举。"),
    }


def clean_rows(
    rows: Iterable[Mapping[str, Any]],
    *,
    key: str = "skill",
    limit: int | None = None,
) -> list[Mapping[str, Any]]:
    """按清洗后的技能名过滤行（保持原顺序）。"""
    names = [str(r.get(key)) for r in rows]
    kept, _ = clean_vocabulary(names)
    keep = set(kept)
    out = [r for r in rows if str(r.get(key)) in keep]
    return out[:limit] if limit else out

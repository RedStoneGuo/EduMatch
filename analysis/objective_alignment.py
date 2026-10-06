"""S1 培养目标—岗位能力一致性：从"文本余弦"改为"需求能力覆盖"。

为什么改？

旧实现把「培养目标原文」与「岗位技能名列表」做 TF-IDF 字符余弦，再把低于校准下限的
余弦**压成 0.0** 输出。这条链有两个致命缺陷：

1. **0 是假 0**：余弦低于下限代表"这段文本不足以支撑判断"，应当记证据不足（None），
   而不是记 0 分。旧实现把 0.0 交给 TSI，导致 S1 恒等于 0。
2. **度量本身不对**：培养目标与岗位技能列表用词天然不同，对称余弦会把"方向一致但用词
   不同"判成 0。正确的问法是：

      目标岗位要求的知识/技能/能力，有多少被本专业的培养目标明确覆盖？

   这是一个**单侧覆盖度**（demand-weighted coverage），可解释、可复现、可追溯到词。

新定义（确定性，无 LLM 参与数值）：

    S1 = Σ_{s ∈ Demand, s 被培养目标文本命中} w(s) / Σ_{s ∈ Demand} w(s) × 100

* 命中的判定：技能名/别名在培养目标文本中出现，或本体的课程—技能解析器在该文本上解析出该技能；
* 培养目标文本必须通过**有效性校验**（是真正的目标表述，不是目录/选课说明/学分要求）；
* 无有效培养目标文本 → S1 = `None`（证据不足），**绝不记 0**；
* 有效文本但确实一个需求能力都没覆盖 → 记真实的 0，并显式标记 `real_zero=True`；
* 只有在"技能覆盖"不可用时，才回退到"培养目标 vs 岗位文本"的向量余弦，并且要求
  余弦**高于校准下限**，否则仍记 None。
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Mapping, Sequence

#: 培养目标的特征词：出现得越多，越像真正的目标表述。
OBJECTIVE_MARKERS: tuple[str, ...] = (
    "培养目标", "培养", "人才", "能力", "素质", "掌握", "具备", "面向",
    "德智体美劳", "专业", "能够", "胜任", "基础", "创新", "应用",
)

#: 明显不是培养目标的样板文字（目录 / 选课 / 学分 / 表格说明）。
BOILERPLATE_MARKERS: tuple[str, ...] = (
    "拓展型", "修读要求", "选课", "课程级别", "修读学分", "教学计划表",
    "附表", "目录", "最低要求", "学分总数", "开课单位", "考核方式",
)

MIN_OBJECTIVE_CHARS = 40

#: 强特征词：出现其一基本可确认是目标表述（而不是"培养方案/基础"这类泛词）。
STRONG_OBJECTIVE_MARKERS: tuple[str, ...] = (
    "培养目标", "本专业培养", "培养德智体", "培养具备", "培养掌握",
    "培养能够", "旨在培养", "培养面向", "培养符合", "培养具有",
)

#: 强锚点：出现在这些标题之后的段落本身就处在目标语境中。
STRONG_ANCHORS: tuple[str, ...] = ("培养目标", "专业培养目标", "培养目标与要求", "培养定位")


@dataclass
class ObjectiveCandidate:
    text: str
    anchor: str = ""
    position: int = -1
    marker_hits: int = 0
    boilerplate_hits: int = 0
    valid: bool = False
    invalid_reason: str = ""
    #: "major" = 明确属于本专业；"school" = 院校级（全校口径）目标表述，只能作代理并披露。
    scope: str = ""

    @property
    def score(self) -> tuple[int, int, int]:
        """排序键：有效优先 → 目标特征词多 → 样板词少 → 文本长。"""
        return (1 if self.valid else 0, self.marker_hits,
                -self.boilerplate_hits + len(self.text) // 50)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _count(text: str, terms: Sequence[str]) -> int:
    return sum(1 for term in terms if term in text)


def is_valid_objective(text: str, *, strong_context: bool = False) -> tuple[bool, str]:
    """判断一段文字是否可能是真正的培养目标表述。

    ``strong_context=True`` 表示该段落取自"培养目标"等强锚点之后，允许它在样板词
    稍多时通过，但样板词过多（≥4）仍判无效——这正是旧实现把"拓展型培养方案/
    课程修读要求"当成培养目标的场景。
    """
    snippet = (text or "").strip()
    if len(snippet) < MIN_OBJECTIVE_CHARS:
        return False, f"文本过短（{len(snippet)} < {MIN_OBJECTIVE_CHARS} 字符），更像标题或目录条目"
    markers = _count(snippet, OBJECTIVE_MARKERS)
    boilerplate = _count(snippet, BOILERPLATE_MARKERS)
    strong = _count(snippet, STRONG_OBJECTIVE_MARKERS)
    if markers < 2:
        return False, f"缺少培养目标特征词（命中 {markers} < 2），不是目标表述"
    if boilerplate >= 2 and strong == 0 and not strong_context:
        return False, (f"样板文字过多（样板词 {boilerplate} 个 / 目标特征词 {markers} 个），"
                       "属于选课或课程说明")
    if boilerplate >= 4:
        return False, (f"样板文字过多（样板词 {boilerplate} 个），"
                       "即使位于培养目标锚点之后也不足以作为目标原文")
    return True, ""


def extract_objective_candidates(
    full_text: str,
    anchors: Sequence[str] = ("培养目标", "专业培养目标", "培养目标与要求", "培养定位"),
    *,
    window: int = 400,
    limit: int = 8,
    scope: str = "school",
) -> list[ObjectiveCandidate]:
    """扫描所有锚点出现处，返回按可信度排序的候选培养目标段落。"""
    if not full_text:
        return []
    found: list[ObjectiveCandidate] = []
    for anchor in anchors:
        index = full_text.find(anchor)
        while index >= 0 and len(found) < limit * 4:
            snippet = full_text[index + len(anchor): index + len(anchor) + window]
            snippet = snippet.strip(" ：:，,。；;\n\t")
            valid, reason = is_valid_objective(
                snippet, strong_context=anchor in STRONG_ANCHORS)
            found.append(ObjectiveCandidate(
                text=snippet.replace("\n", " "),
                anchor=anchor,
                position=index,
                marker_hits=_count(snippet, OBJECTIVE_MARKERS),
                boilerplate_hits=_count(snippet, BOILERPLATE_MARKERS),
                valid=valid,
                invalid_reason=reason,
                scope=scope,
            ))
            index = full_text.find(anchor, index + 1)
    found.sort(key=lambda c: c.score, reverse=True)
    return found[:limit]


def extract_major_objective_candidates(
    text: str,
    major: str,
    *,
    window: int = 500,
    limit: int = 6,
    look_back: int = 300,
    anchor_window: int = 60,
) -> list[ObjectiveCandidate]:
    """从**院校级**报告（就业质量报告 / 教学质量报告 / 专业介绍）里定位某个专业的培养目标。

    与按文件名匹配的 ``extract_objective_candidates`` 互补：院校级报告的正文里
    会出现"XX专业：培养目标 ……"这类段落，文件名却只有学校名。这里按专业名在正文中
    定位，并检查附近是否有培养目标锚点——因此适用于**任意院校 + 任意专业**。
    """
    if not text or not major:
        return []
    found: list[ObjectiveCandidate] = []
    index = text.find(major)
    anchor_names = ("培养目标", "培养要求", "培养定位")
    while index >= 0 and len(found) < limit * 3:
        before = text[max(0, index - look_back):index]
        best_name, anchor_pos = "", -1
        for candidate_name in anchor_names:
            pos = before.rfind(candidate_name)
            if pos > anchor_pos:
                best_name, anchor_pos = candidate_name, pos
        near_anchor = anchor_pos >= 0 and (len(before) - anchor_pos) <= anchor_window
        if not near_anchor:
            # 专业名附近没有"培养目标/培养要求/培养定位"锚点 → 不是目标段落，跳过。
            # 否则统计表里的"XX专业"会被误判成培养目标（实测过的假阳性）。
            index = text.find(major, index + 1)
            continue
        start = max(0, index - look_back) + anchor_pos + len(best_name)
        snippet = text[start:start + window]
        strong_context = True
        snippet = snippet.strip(" ：:，,。；;\n\t")
        valid, reason = is_valid_objective(snippet, strong_context=strong_context)
        if valid and strong_context:
            # 锚点必须紧邻专业名，且上下文真的像目标表述，避免把统计表当成培养目标
            if (_count(snippet, OBJECTIVE_MARKERS) < 3
                    and _count(snippet, STRONG_OBJECTIVE_MARKERS) == 0):
                valid, reason = False, "锚点附近文本缺少目标特征，判为非目标段落"
        found.append(ObjectiveCandidate(
            text=snippet.replace("\n", " "),
            anchor=f"{major}:培养目标",
            position=index,
            marker_hits=_count(snippet, OBJECTIVE_MARKERS),
            boilerplate_hits=_count(snippet, BOILERPLATE_MARKERS),
            valid=valid,
            invalid_reason=reason,
            scope="major",
        ))
        index = text.find(major, index + 1)
    found.sort(key=lambda c: c.score, reverse=True)
    return found[:limit]


_LATIN_TOKEN = re.compile(r"[A-Za-z]" )


def _mentioned(skill: str, text: str, resolved: set[str]) -> bool:
    if not skill:
        return False
    if skill in resolved:
        return True
    if skill in text:
        return True
    lowered = text.lower()
    token = skill.lower()
    if _LATIN_TOKEN.search(skill) and len(skill) <= 4:
        return re.search(rf"(?<![a-z0-9]){re.escape(token)}(?![a-z0-9])", lowered) is not None
    return False


def objective_skill_coverage(
    text: str,
    demand: Mapping[str, float],
    *,
    resolve_skills: Callable[[str, str], Sequence[str]] | None = None,
) -> dict[str, Any]:
    """需求加权的单侧覆盖度：岗位需求能力被培养目标文本覆盖的比例。"""
    weights = {str(k): float(v) for k, v in (demand or {}).items()
               if isinstance(v, (int, float)) and not isinstance(v, bool) and float(v) > 0}
    if not weights:
        return {"coverage": None, "status": "insufficient_evidence",
                "reason": "需求向量为空，无法计算覆盖度",
                "covered_skills": [], "missing_skills": [], "n_demanded": 0}
    if not text or not text.strip():
        return {"coverage": None, "status": "insufficient_evidence",
                "reason": "培养目标文本缺失",
                "covered_skills": [], "missing_skills": sorted(weights), "n_demanded": len(weights)}
    resolved: set[str] = set()
    if resolve_skills is not None:
        try:
            resolved = set(resolve_skills(text, "") or [])
        except Exception:  # noqa: BLE001 - 解析器失败不阻断，退回字符串命中
            resolved = set()
    covered = [s for s in weights if _mentioned(s, text, resolved)]
    missing = [s for s in weights if s not in set(covered)]
    total = sum(weights.values())
    hit = sum(weights[s] for s in covered)
    return {
        "coverage": round(hit / total, 4) if total else None,
        "status": "ok",
        "reason": "",
        "covered_skills": sorted(covered, key=lambda s: -weights[s]),
        "missing_skills": sorted(missing, key=lambda s: -weights[s]),
        "n_demanded": len(weights),
        "n_covered": len(covered),
        "weight_covered": round(hit, 4),
        "weight_total": round(total, 4),
        "resolver_skills": sorted(resolved)[:40],
    }


def objective_job_alignment(
    candidates: Sequence[ObjectiveCandidate | Mapping[str, Any] | str],
    demand: Mapping[str, float],
    *,
    resolve_skills: Callable[[str, str], Sequence[str]] | None = None,
    lexical_score: Mapping[str, Any] | None = None,
    provider: str = "objective_skill_coverage_v1",
) -> dict[str, Any]:
    """S1 主计算：返回与旧 `VectorScore.to_dict()` 兼容的结果字典。"""
    normalized: list[ObjectiveCandidate] = []
    for item in candidates or []:
        if isinstance(item, ObjectiveCandidate):
            normalized.append(item)
        elif isinstance(item, str):
            valid, reason = is_valid_objective(item)
            normalized.append(ObjectiveCandidate(text=item, valid=valid, invalid_reason=reason,
                                                 marker_hits=_count(item, OBJECTIVE_MARKERS),
                                                 boilerplate_hits=_count(item, BOILERPLATE_MARKERS)))
        else:
            normalized.append(ObjectiveCandidate(
                text=str(item.get("text") or ""), anchor=str(item.get("anchor") or ""),
                marker_hits=int(item.get("marker_hits") or 0),
                boilerplate_hits=int(item.get("boilerplate_hits") or 0),
                valid=bool(item.get("valid")), invalid_reason=str(item.get("invalid_reason") or ""),
                scope=str(item.get("scope") or ""),
            ))
    normalized.sort(key=lambda c: c.score, reverse=True)
    all_valid = [c for c in normalized if c.valid]
    major_valid = [c for c in all_valid if c.scope == "major"]
    school_valid = [c for c in all_valid if c.scope != "major"]
    # 专业级目标优先；只有校级目标时作**已披露的代理**，绝不冒充本专业目标。
    valid = major_valid or school_valid
    proxy_school_level = bool(school_valid) and not major_valid

    lexical = dict(lexical_score or {})
    lexical_cosine = lexical.get("cosine")
    lexical_status = lexical.get("status")

    if not valid:
        return {
            "similarity": None,
            "cosine": lexical_cosine,
            "calibration": lexical.get("calibration") or {},
            "provider": provider,
            "status": "insufficient_evidence",
            "top_terms": lexical.get("top_terms") or [],
            "notes": ("未找到可信的培养目标文本"
                      + (f"（{normalized[0].invalid_reason}）" if normalized else "（无候选）")
                      + "；S1 记证据不足，不记 0。"),
            "evidence_level": "E",
            "caveat": "培养目标—岗位能力一致性需要可核查的培养目标原文；缺文本时不输出分数。",
            "basis": "none",
            "basis_text_preview": "",
            "covered_skills": [], "missing_skills": [], "n_demanded": len(demand or {}),
            "real_zero": False,
            "proxy_school_level": False,
            "scope_note": "未检索到本专业培养目标原文（校级目标也没有可核查文本）。",
            "method": "demand_weighted_objective_coverage",
        }

    # 多来源合并：一个需求能力只要被任一有效培养目标覆盖即算覆盖。
    # 区域尺度（多校）下这是"覆盖高校目标的并集"；单校尺度通常只有 1 份文本。
    seen: set[str] = set()
    merged_parts: list[str] = []
    used_chars = 0
    for candidate in valid:
        text = candidate.text.strip()
        if not text or text in seen:
            continue
        seen.add(text)
        merged_parts.append(text)
        used_chars += len(text)
        if used_chars >= 6000:
            break
    merged_text = " ".join(merged_parts)
    basis_sources = [c.anchor or "section" for c in valid[:6]]
    basis_kind = "school_level_objective" if proxy_school_level else "major_objective"
    coverage = objective_skill_coverage(merged_text, demand, resolve_skills=resolve_skills)
    if coverage.get("coverage") is None:
        # 需求向量缺失：退回向量余弦，但仍要求高于下限
        above = (lexical_status == "ok" and isinstance(lexical.get("similarity"), (int, float)))
        return {
            "similarity": float(lexical["similarity"]) if above else None,
            "cosine": lexical_cosine,
            "calibration": lexical.get("calibration") or {},
            "provider": provider,
            "status": "ok" if above else "insufficient_evidence",
            "top_terms": lexical.get("top_terms") or [],
            "notes": coverage.get("reason") or "需求向量缺失，已回退文本余弦",
            "evidence_level": "D",
            "caveat": "回退到文本向量余弦，仅作代理指标。",
            "basis": f"{basis_kind}:{'+'.join(sorted(set(basis_sources)))}",
            "basis_text_preview": merged_text[:160],
            "proxy_school_level": proxy_school_level,
            "covered_skills": [], "missing_skills": [], "n_demanded": 0,
            "real_zero": False,
            "method": "lexical_fallback_above_floor",
        }

    value = float(coverage["coverage"])
    return {
        "similarity": round(value, 4),
        "cosine": lexical_cosine,
        "calibration": lexical.get("calibration") or {},
        "provider": provider,
        "status": "ok",
        "top_terms": lexical.get("top_terms") or [],
        "notes": (f"培养目标文本 {len(merged_text)} 字（{len(merged_parts)} 段"
                  + ("，校级代理" if proxy_school_level else "")
                  + f"）；覆盖 {coverage['n_covered']}/"
                  f"{coverage['n_demanded']} 项需求能力（需求加权 {value:.4f}）"),
        "evidence_level": "D",
        # 校级代理的置信度更低：它只反映学校层面表述，不是本专业目标。
        "confidence": 0.35 if proxy_school_level else 0.55,
        "caveat": ("覆盖度 = 岗位需求能力中被培养目标文本明确命中的比例（需求加权），"
                   "是可复现的规则指标，不等同于语义等价判断。"
                   + ("本值以校级培养目标为代理，不是专业级结论。" if proxy_school_level else "")),
        "basis": f"{basis_kind}:{'+'.join(sorted(set(basis_sources)))}",
        "basis_text_preview": merged_text[:160],
        "basis_sources": basis_sources,
        "n_basis_segments": len(merged_parts),
        "proxy_school_level": proxy_school_level,
        "scope_note": ("使用**校级**培养目标作为代理：本地未检索到本专业的培养目标原文，"
                       "该分数只反映学校层面的目标表述，不能当作专业级结论。"
                       if proxy_school_level else "基于本专业培养目标原文。"),
        "covered_skills": coverage["covered_skills"],
        "missing_skills": coverage["missing_skills"],
        "n_demanded": coverage["n_demanded"],
        "n_covered": coverage["n_covered"],
        "real_zero": value == 0.0,
        "lexical_cosine": lexical_cosine,
        "method": "demand_weighted_objective_coverage",
        "candidates_considered": len(normalized),
    }

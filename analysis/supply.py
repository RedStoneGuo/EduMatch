"""Skill Supply Vector - continuous, channel-decomposed supply strength.

The legacy matrix answered "does any course mention this skill" (a 0/1 cell
weighted by credits). The Core TSI Engine needs a real *supply strength* that
can be compared with the demand intensity scale, so every (course, skill) edge
now carries an explicit weight built from channels:

    w(c, s) = credits · required_factor · depth_factor · practice_factor

    Supply(s) = min( Σ_c w(c, s) / C_ref  +  β · 1[培养目标命中 s] , 1 )

Channel semantics (``SupplyChannel`` records what was actually available):

* ``coverage``  - how many distinct courses teach the skill (multi-course cover)
* ``credits``   - credit volume; falls back to a neutral 1.0 when unstated
* ``required``  - 必修 vs 选修, parsed from explicit fields or the course text
* ``depth``     - 导论/核心/进阶 grading when the source states it
* ``practice``  - 实践/实训/实习/项目/实验 courses and stated practice hours
* ``objective`` - the programme objective text names the skill

Channels that the source data does not support stay ``None`` and are listed in
``unavailable_channels`` - they are never silently replaced with a guess, and
their weight is not redistributed inside a course weight (a missing depth grade
means "neutral 1.0", which is disclosed rather than treated as evidence).

``provenance`` makes the Target/Peer separation explicit: a supply vector is
either the target institution's own evidence or a regional peer benchmark. The
engine builds both and never substitutes one for the other.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence

DEFAULT_REFERENCE_CREDITS = 6.0
DEFAULT_OBJECTIVE_BONUS = 0.10

REQUIRED_HINTS = ("必修", "必选", "专业核心", "核心课程")
ELECTIVE_HINTS = ("选修", "任选", "限选", "通识", "微专业", "双学位")

DEPTH_FACTORS: dict[str, float] = {
    "intro": 0.90, "basic": 0.90,
    "core": 1.10, "advanced": 1.20, "research": 1.15,
}
DEPTH_HINTS: list[tuple[str, tuple[str, ...]]] = [
    ("advanced", ("进阶", "高级", "前沿", "专题")),
    ("research", ("研讨", "研究型", "科研")),
    ("core", ("核心", "主干", "专业必修")),
    ("intro", ("导论", "概论", "基础", "入门", "通识")),
]

REQUIRED_FACTOR = 1.15
ELECTIVE_FACTOR = 0.85


@dataclass
class SupplyChannel:
    """Per-skill audit of which supply channels were actually observed."""

    n_courses: int = 0
    credits: float = 0.0
    weight: float = 0.0
    required_courses: int = 0
    elective_courses: int = 0
    unknown_requirement_courses: int = 0
    practice_courses: int = 0
    practice_hours: float = 0.0
    depth_levels: list[str] = field(default_factory=list)
    objective_hit: bool = False
    course_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "n_courses": self.n_courses,
            "credits": round(self.credits, 2),
            "weight": round(self.weight, 4),
            "required_courses": self.required_courses,
            "elective_courses": self.elective_courses,
            "unknown_requirement_courses": self.unknown_requirement_courses,
            "practice_courses": self.practice_courses,
            "practice_hours": round(self.practice_hours, 2),
            "depth_levels": sorted(set(self.depth_levels)),
            "objective_hit": self.objective_hit,
            "course_ids": self.course_ids,
        }


@dataclass
class SupplyVector:
    provenance: str                      # "target" | "peer"
    skills: list[str]
    score: dict[str, float]
    channels: dict[str, SupplyChannel]
    n_courses: int
    n_mapped_courses: int
    n_unmapped_courses: int
    reference_credits: float
    status: str                          # ok | insufficient_evidence
    reliability: str                     # high | medium | low | none
    reason: str = ""
    objective_skills: list[str] = field(default_factory=list)
    unavailable_channels: list[str] = field(default_factory=list)
    min_courses: int = 3
    partial: bool = False

    @property
    def total_weight(self) -> float:
        return sum(c.weight for c in self.channels.values())

    def credits_by_skill(self) -> dict[str, float]:
        return {s: c.credits for s, c in self.channels.items()}

    def supply_share(self) -> dict[str, float]:
        total = self.total_weight or 1.0
        return {s: c.weight / total for s, c in self.channels.items()}

    def to_dict(self, *, top_n: int = 12) -> dict[str, Any]:
        top = sorted(self.score.items(), key=lambda kv: (-kv[1], kv[0]))[:top_n]
        return {
            "provenance": self.provenance,
            "status": self.status,
            "reliability": self.reliability,
            "reason": self.reason,
            "n_courses": self.n_courses,
            "n_mapped_courses": self.n_mapped_courses,
            "n_unmapped_courses": self.n_unmapped_courses,
            "partial": self.partial,
            "status_label": (
                "ok" if self.status == "ok" and not self.partial
                else "partial_evidence" if self.status == "ok"
                else "insufficient_evidence"
            ),
            "reference_credits": self.reference_credits,
            "min_courses": self.min_courses,
            "n_skills": len(self.skills),
            "objective_skills": self.objective_skills,
            "unavailable_channels": self.unavailable_channels,
            "top_skills": [{"skill": s, "supply": round(v, 4)} for s, v in top],
            "channels": {s: self.channels[s].to_dict() for s, _ in top},
        }


def parse_requirement(course: Mapping[str, Any]) -> bool | None:
    """True=必修, False=选修, None=来源未说明（不得猜测）。"""
    explicit = course.get("is_required")
    if isinstance(explicit, bool):
        return explicit
    text = " ".join(
        str(course.get(k) or "") for k in ("name", "category", "description", "requirement")
    )
    if any(hint in text for hint in REQUIRED_HINTS):
        return True
    if any(hint in text for hint in ELECTIVE_HINTS):
        return False
    return None


def parse_depth(course: Mapping[str, Any]) -> str | None:
    explicit = course.get("teaching_depth")
    if isinstance(explicit, str) and explicit in DEPTH_FACTORS:
        return explicit
    text = " ".join(str(course.get(k) or "") for k in ("name", "category", "description"))
    for level, hints in DEPTH_HINTS:
        if any(hint in text for hint in hints):
            return level
    return None


def course_supply_weight(course: Mapping[str, Any]) -> tuple[float, dict[str, Any]]:
    """Weight of one course in the supply sum, plus the channel audit trail."""
    credits = course.get("credits")
    if not isinstance(credits, (int, float)) or credits <= 0:
        credits = None
    base = float(credits) if credits is not None else 1.0

    practice_hours = course.get("practice_hours")
    has_practice_hours = isinstance(practice_hours, (int, float)) and practice_hours > 0
    is_practice = bool(course.get("is_practice")) or has_practice_hours

    practice_factor = 1.2 if is_practice else 1.0
    practice_bonus = min(float(practice_hours) / 64.0, 0.5) if has_practice_hours else 0.0
    weight = base * practice_factor + practice_bonus

    requirement = parse_requirement(course)
    if requirement is True:
        weight *= REQUIRED_FACTOR
    elif requirement is False:
        weight *= ELECTIVE_FACTOR

    depth = parse_depth(course)
    depth_factor = DEPTH_FACTORS.get(depth or "", 1.0)
    weight *= depth_factor

    return weight, {
        "credits": float(credits) if credits is not None else None,
        "credits_imputed": credits is None,
        "practice_factor": practice_factor,
        "practice_bonus": round(practice_bonus, 4),
        "required": requirement,
        "depth": depth,
        "depth_factor": depth_factor,
        "weight": round(weight, 4),
    }


def _reliability(n_mapped: int, min_courses: int) -> str:
    if n_mapped <= 0:
        return "none"
    if n_mapped >= min_courses * 2:
        return "high"
    if n_mapped >= min_courses:
        return "medium"
    return "low"


def build_supply_vector(
    courses: Sequence[Mapping[str, Any]],
    resolve_skills: Callable[[str, str], Sequence[str]],
    *,
    provenance: str = "peer",
    skill_universe: Sequence[str] | None = None,
    reference_credits: float = DEFAULT_REFERENCE_CREDITS,
    objective_skills: Sequence[str] | None = None,
    objective_bonus: float = DEFAULT_OBJECTIVE_BONUS,
    min_courses: int = 3,
) -> SupplyVector:
    """Build the continuous Skill Supply Score for one evidence scope."""
    channels: dict[str, SupplyChannel] = {}
    mapped_courses = 0
    unmapped_courses = 0
    objective = sorted(set(objective_skills or []))

    for idx, course in enumerate(courses):
        name = str(course.get("name") or course.get("course") or f"course_{idx}")
        cid = str(course.get("course_id") or f"c{idx:03d}")
        skills = sorted(set(resolve_skills(name, str(course.get("description") or ""))))
        if skills:
            mapped_courses += 1
        else:
            unmapped_courses += 1
        weight, audit = course_supply_weight(course)
        requirement = audit["required"]
        practice_hours = course.get("practice_hours")
        for skill in skills:
            channel = channels.setdefault(skill, SupplyChannel())
            channel.n_courses += 1
            channel.credits += audit["credits"] or 0.0
            channel.weight += weight
            if requirement is True:
                channel.required_courses += 1
            elif requirement is False:
                channel.elective_courses += 1
            else:
                channel.unknown_requirement_courses += 1
            if audit["practice_factor"] > 1.0 or audit["practice_bonus"]:
                channel.practice_courses += 1
            if isinstance(practice_hours, (int, float)) and practice_hours > 0:
                channel.practice_hours += float(practice_hours)
            if audit["depth"]:
                channel.depth_levels.append(audit["depth"])
            channel.course_ids.append(cid)

    universe = sorted(set(skill_universe)) if skill_universe is not None else sorted(channels)
    score: dict[str, float] = {}
    for skill in universe:
        channel = channels.get(skill)
        raw = (channel.weight / reference_credits) if channel and reference_credits > 0 else 0.0
        hit = skill in objective
        if hit:
            if channel is None:
                channel = channels.setdefault(skill, SupplyChannel())
            channel.objective_hit = True
            raw += objective_bonus
        # 保留全精度：matching/skill_gap 的手工复算与历史结果都依赖未截断值，
        # 仅在接受输出时（to_dict）做 4 位小数展示。
        score[skill] = min(raw, 1.0)

    status = "ok" if mapped_courses > 0 else "insufficient_evidence"
    reason = "" if status == "ok" else "该口径下没有可核查的课程—技能证据"
    reliability = _reliability(mapped_courses, min_courses)
    partial = bool(status == "ok" and mapped_courses < min_courses)
    if partial:
        reason = (f"仅 {mapped_courses} 门可核查课程（低于 {min_courses} 门门槛），"
                  "该供给画像为可核查证据的保守下界，不能代表完整培养体系")

    unavailable = ["required"] if all(
        c.unknown_requirement_courses and not c.required_courses and not c.elective_courses
        for c in channels.values()
    ) else []
    if all(not c.depth_levels for c in channels.values()):
        unavailable.append("depth")
    if all(not c.practice_courses for c in channels.values()):
        unavailable.append("practice")
    if not objective:
        unavailable.append("objective")

    return SupplyVector(
        provenance=provenance,
        skills=universe,
        score=score,
        channels={s: channels[s] for s in universe if s in channels},
        n_courses=len(courses),
        n_mapped_courses=mapped_courses,
        n_unmapped_courses=unmapped_courses,
        reference_credits=reference_credits,
        status=status,
        reliability=reliability,
        reason=reason,
        objective_skills=objective,
        unavailable_channels=sorted(set(unavailable)),
        min_courses=min_courses,
        partial=partial,
    )


_SKILL_TOKEN = re.compile(r"[\u4e00-\u9fffA-Za-z][\u4e00-\u9fffA-Za-z0-9+.#]{1,}")


def objective_skill_hits(text: str, skill_names: Sequence[str]) -> list[str]:
    """Skills explicitly named in the programme objective text (for the β channel)."""
    if not text:
        return []
    haystack = text
    found: list[str] = []
    for name in skill_names:
        if not name:
            continue
        if name.isascii() and len(name) <= 3:
            if re.search(rf"(?<![A-Za-z0-9]){re.escape(name)}(?![A-Za-z0-9])", haystack):
                found.append(name)
        elif name in haystack:
            found.append(name)
    return sorted(set(found))

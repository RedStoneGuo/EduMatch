"""Canonical Supply/Demand profile schemas (multi-scale upgrade layer).

This module is the single place where the four capability layers and the
Supply/Demand profile objects are defined.  It deliberately **wraps** the
existing deterministic engine instead of replacing it:

* :class:`SupplyProfile` - one供给对象 for all three scales (regional / major /
  personal).  ``from_supply_vector`` adapts the existing
  :class:`analysis.supply.SupplyVector` without recomputing anything.
* :class:`JobProfile` - the unified target-job picture (spec §26).  Education
  and salary are *constraints / segmentation variables*; only
  knowledge/skill/capability/practice take part in the matching body.
* :class:`PersonalEvidenceProfile` - the micro-level evidence profile with the
  sparse-data degradation levels L0-L4 and the three gap classes.
* :class:`Gap` - one缺口 row carrying its layer so Knowledge / Skill /
  Capability / Practice gaps never collapse into a single number.

Legacy field compatibility (spec §46) lives in :func:`apply_legacy_compat`:
old payloads keep their keys, and canonical aliases are added on top.

Nothing here invents numbers.  A value is a float only when a deterministic
source produced it; otherwise it is ``None`` with an explicit status.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, Mapping, Sequence

#: The four capability layers, in the order they are built and compared.
LAYERS: tuple[str, ...] = ("knowledge", "skill", "capability", "practice")

#: Chinese labels used by reports / HTML.
LAYER_LABEL: dict[str, str] = {
    "knowledge": "知识",
    "skill": "技能",
    "capability": "能力",
    "practice": "实践",
}


def _clean(values: Mapping[str, Any] | None) -> dict[str, float | None]:
    """Keep only numeric values; missing stays ``None`` (never 0)."""
    out: dict[str, float | None] = {}
    for key, value in (values or {}).items():
        if value is None:
            out[str(key)] = None
        elif isinstance(value, bool):
            continue
        elif isinstance(value, (int, float)):
            out[str(key)] = float(value)
        else:
            out[str(key)] = None
    return out


def _layer_coverage(vector: Mapping[str, float | None]) -> float:
    if not vector:
        return 0.0
    known = sum(1 for v in vector.values() if v is not None)
    return round(known / len(vector), 4)


@dataclass
class SupplyProfile:
    """One supply object for a region, an institution-major, or a person.

    ``scale`` is ``regional`` / ``major`` / ``personal``.  The four vectors are
    the *same* schema at every scale, which is what makes Macro/Meso/Micro a
    projection of one model rather than three models.
    """

    scale: str
    knowledge_supply: dict[str, float | None] = field(default_factory=dict)
    skill_supply: dict[str, float | None] = field(default_factory=dict)
    capability_supply: dict[str, float | None] = field(default_factory=dict)
    practice_supply: dict[str, float | None] = field(default_factory=dict)
    graduate_profile: list[dict[str, Any]] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    coverage: dict[str, Any] = field(default_factory=dict)
    confidence: dict[str, Any] = field(default_factory=dict)
    provenance: str = ""
    status: str = "ok"
    reason: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    def vector(self, layer: str) -> dict[str, float | None]:
        if layer not in LAYERS:
            raise KeyError(f"unknown layer: {layer}")
        return getattr(self, f"{layer}_supply")

    def refresh_coverage(self) -> None:
        for layer in LAYERS:
            self.coverage[layer] = _layer_coverage(self.vector(layer))
        self.confidence.setdefault("layers", {})

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_supply_vector(
        cls,
        vector: Any,
        *,
        scale: str = "major",
        knowledge: Mapping[str, float | None] | None = None,
        practice: Mapping[str, float | None] | None = None,
        capability: Mapping[str, float | None] | None = None,
        evidence: Sequence[str] | None = None,
        graduate_profile: Sequence[Mapping[str, Any]] | None = None,
    ) -> "SupplyProfile":
        """Adapt a :class:`analysis.supply.SupplyVector` into the canonical form.

        ``skill_supply`` is taken verbatim from the deterministic engine.  The
        other three layers are only filled when a caller supplies them (the
        engine does not yet emit them), so they start empty rather than guessed.
        """
        score = getattr(vector, "score", None)
        channels = getattr(vector, "channels", {}) or {}
        profile = cls(
            scale=scale,
            knowledge_supply=_clean(knowledge),
            skill_supply=_clean(score if isinstance(score, Mapping) else None),
            capability_supply=_clean(capability),
            practice_supply=_clean(practice),
            graduate_profile=[dict(g) for g in (graduate_profile or [])],
            evidence=list(evidence or []),
            provenance=str(getattr(vector, "provenance", "") or ""),
            status=str(getattr(vector, "status", "ok") or "ok"),
            reason=str(getattr(vector, "reason", "") or ""),
            meta={
                "n_courses": getattr(vector, "n_courses", None),
                "n_mapped_courses": getattr(vector, "n_mapped_courses", None),
                "reliability": getattr(vector, "reliability", None),
                "unavailable_channels": list(getattr(vector, "unavailable_channels", []) or []),
                "channels": {
                    name: (channel.to_dict() if hasattr(channel, "to_dict") else dict(channel))
                    for name, channel in channels.items()
                },
            },
        )
        profile.refresh_coverage()
        return profile


@dataclass
class JobProfile:
    """Unified target-job picture (spec §26).

    ``education_requirement`` is an *eligibility constraint* and
    ``salary_segment`` is a *market segmentation variable*.  Neither enters the
    matching body; ``matching_body()`` returns exactly the four layers.
    """

    job_family: list[str] = field(default_factory=list)
    industry: list[str] = field(default_factory=list)
    experience_requirement: list[str] = field(default_factory=list)
    education_requirement: list[str] = field(default_factory=list)
    knowledge_requirements: dict[str, float | None] = field(default_factory=dict)
    skill_requirements: dict[str, float | None] = field(default_factory=dict)
    capability_requirements: dict[str, float | None] = field(default_factory=dict)
    practice_requirements: dict[str, float | None] = field(default_factory=dict)
    task_chain: list[str] = field(default_factory=list)
    technology_stack: list[str] = field(default_factory=list)
    salary_segment: dict[str, Any] = field(default_factory=dict)
    evidence: list[str] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)

    def matching_body(self) -> dict[str, dict[str, float | None]]:
        return {layer: getattr(self, f"{layer}_requirements") for layer in LAYERS}

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_demand(
        cls,
        demand: Mapping[str, float | None],
        *,
        occupation: Mapping[str, Any] | None = None,
        demand_meta: Mapping[str, Any] | None = None,
        salary_segment: Mapping[str, Any] | None = None,
        evidence: Sequence[str] | None = None,
    ) -> "JobProfile":
        occupation = occupation or {}
        requirements = {str(k): float(v) for k, v in demand.items()
                        if isinstance(v, (int, float)) and not isinstance(v, bool)}
        return cls(
            job_family=[occupation.get("name")] if occupation.get("name") else [],
            skill_requirements=requirements,
            technology_stack=list((occupation.get("typical_skills") or [])),
            salary_segment=dict(salary_segment or {}),
            evidence=list(evidence or []),
            meta={
                "occupation_id": occupation.get("id"),
                "match_scope": occupation.get("match_scope"),
                "n_jobs": occupation.get("n_jobs"),
                "demand_meta": dict(demand_meta or {}),
            },
        )


@dataclass
class PersonalEvidenceProfile:
    """Micro-level evidence profile (spec §21-§24).

    ``sparse_level`` follows the spec: 0 = school+major+grade+target only,
    1 = + courses, 2 = + skills, 3 = + projects, 4 = + internship/research/
    portfolio/outcome.
    """

    knowledge_evidence: list[dict[str, Any]] = field(default_factory=list)
    skill_evidence: list[dict[str, Any]] = field(default_factory=list)
    capability_evidence: list[dict[str, Any]] = field(default_factory=list)
    practice_evidence: list[dict[str, Any]] = field(default_factory=list)
    evidence_strength: dict[str, float] = field(default_factory=dict)
    coverage: dict[str, Any] = field(default_factory=dict)
    confidence: dict[str, Any] = field(default_factory=dict)
    sparse_level: int = 0
    declared: dict[str, Any] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)

    def layer_items(self, layer: str) -> list[dict[str, Any]]:
        if layer not in LAYERS:
            raise KeyError(f"unknown layer: {layer}")
        return getattr(self, f"{layer}_evidence")

    def summary(self) -> dict[str, int]:
        return {layer: len(self.layer_items(layer)) for layer in LAYERS}

    def compute_sparse_level(self) -> int:
        summary = self.summary()
        if any(self.practice_evidence):
            return 4
        if summary["capability"]:
            return 3
        if summary["skill"]:
            return 2
        if summary["knowledge"]:
            return 1
        return 0

    def refresh(self) -> None:
        self.sparse_level = self.compute_sparse_level()
        self.coverage["items"] = self.summary()
        self.coverage["sparse_level"] = self.sparse_level

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_text(
        cls,
        text: str,
        *,
        extractor: Any | None = None,
        declared: Mapping[str, Any] | None = None,
    ) -> "PersonalEvidenceProfile":
        """Build a profile from free-form text.

        The default extractor is a deterministic keyword/rule pass (no LLM
        needed, no fabricated numbers).  A richer ``extractor`` may be injected;
        it must return the four evidence lists.
        """
        from .personal_extract import extract_personal_evidence

        if extractor is not None:
            payload = extractor(text)
        else:
            payload = extract_personal_evidence(text)
        declared_payload = dict(declared or {})
        declared_payload.update(payload.get("declared") or {})
        profile = cls(
            knowledge_evidence=list(payload.get("knowledge") or []),
            skill_evidence=list(payload.get("skill") or []),
            capability_evidence=list(payload.get("capability") or []),
            practice_evidence=list(payload.get("practice") or []),
            declared=declared_payload,
            meta={"source": "natural_language", "length": len(text or "")},
        )
        profile.refresh()
        return profile


@dataclass
class Gap:
    """One缺口 row that keeps its layer and its evidence basis."""

    skill: str
    layer: str = "skill"
    demand: float | None = None
    supply: float | None = None
    gap: float | None = None
    category: str = ""            # critical | emerging | coverage | practice
    severity: str = "unknown"     # high | medium | low | unknown
    supply_basis: str = ""
    evidence_ids: list[str] = field(default_factory=list)


def gaps_from_fit(
    fit_result: Mapping[str, Any],
    *,
    layer: str = "skill",
    critical_gap: float = 0.25,
    emerging_skills: Iterable[str] = (),
    evidence_ids: Sequence[str] | None = None,
) -> list[Gap]:
    """Turn the engine's per-skill fit rows into canonical :class:`Gap` objects."""
    emerging = {str(s) for s in emerging_skills}
    out: list[Gap] = []
    for row in fit_result.get("per_skill") or []:
        gap = row.get("gap")
        if gap is None or gap <= 0:
            continue
        if gap >= critical_gap:
            category = "critical"
        elif row["skill"] in emerging:
            category = "emerging"
        else:
            category = "coverage"
        severity = "high" if gap >= 0.4 else "medium" if gap >= critical_gap else "low"
        out.append(Gap(
            skill=str(row["skill"]), layer=layer,
            demand=row.get("demand"), supply=row.get("supply"), gap=gap,
            category=category, severity=severity,
            supply_basis=str(row.get("supply_basis") or ""),
            evidence_ids=list(evidence_ids or []),
        ))
    return sorted(out, key=lambda g: -(g.gap or 0))


# --------------------------------------------------------------------------- #
# Legacy compatibility layer (spec §46)
# --------------------------------------------------------------------------- #

#: legacy key -> canonical key.  The legacy key is kept, never deleted.
LEGACY_FIELD_MAP: dict[str, str] = {
    "match": "structural_fit",
    "match_100": "structural_fit_100",
    "tsi_score": "primary_tsi",
    "tsi_value": "primary_tsi",
    "matching_score": "skill_fit",
    "matching_score_100": "skill_fit_100",
}


def apply_legacy_compat(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Return a copy of ``payload`` with canonical aliases added.

    The original keys are preserved so existing reports, JSON consumers and
    tests keep working.  ``legacy_fields`` records what was aliased, which is
    what makes "why did the number change?" answerable.
    """
    out = dict(payload)
    aliased: list[dict[str, str]] = []
    for legacy, canonical in LEGACY_FIELD_MAP.items():
        if legacy in out and canonical not in out:
            out[canonical] = out[legacy]
            aliased.append({"legacy": legacy, "canonical": canonical})
    if aliased:
        out["legacy_fields"] = aliased
        out.setdefault(
            "canonical_note",
            "Primary TSI 是唯一正式总分；match / matching_score 为子指标别名，"
            "对外统一读 primary_tsi。",
        )
    return out


def canonical_field_map() -> dict[str, str]:
    """Exposed for docs and the validator."""
    return dict(LEGACY_FIELD_MAP)

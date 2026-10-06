"""Task planner: query -> research plan.

Planning is rule-based and deterministic so that the same question always
produces the same plan. The LLM layer may *propose* a plan, but the plan that is
executed is the one produced here and recorded in ``result['plan']``.
"""

from __future__ import annotations

from edumatch.dataset import Dataset
from edumatch.engine import ResearchPlan, build_plan, detect_major, detect_school

__all__ = ["ResearchPlan", "build_plan", "detect_major", "detect_school", "plan_for"]


def plan_for(query: str, dataset: Dataset | None = None, **overrides) -> ResearchPlan:
    """Convenience wrapper used by the agent and the demo UI."""
    ds = dataset or Dataset.build()
    plan = build_plan(query, ds, major=overrides.get("major"), school=overrides.get("school"))
    if overrides.get("include_template") is not None:
        plan.include_template = bool(overrides["include_template"])
    return plan

"""Executable skill registry: maps each SKILL.md to the tools it drives."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent


@dataclass
class SkillDef:
    skill_id: str
    name: str
    path: Path
    tools: list[str] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "skill_id": self.skill_id,
            "name": self.name,
            "path": str(self.path.relative_to(SKILLS_DIR.parent)),
            "tools": self.tools,
            "outputs": self.outputs,
            "has_doc": self.path.exists(),
        }


SKILLS: list[SkillDef] = [
    SkillDef("01_evidence_retrieval", "证据检索", SKILLS_DIR / "01_evidence_retrieval" / "SKILL.md",
             ["get_report", "find_report_evidence", "query_employment", "search_policy",
              "find_policy_evidence", "list_sources"], ["evidence[]"]),
    SkillDef("02_curriculum_analysis", "培养方案与课程分析", SKILLS_DIR / "02_curriculum_analysis" / "SKILL.md",
             ["query_curriculum", "calculate_skill_coverage"], ["courses[]", "course_skill_matrix"]),
    SkillDef("03_employment_analysis", "就业结果分析", SKILLS_DIR / "03_employment_analysis" / "SKILL.md",
             ["query_employment", "find_report_evidence", "run_trend_analysis"], ["employment"]),
    SkillDef("04_job_market_analysis", "招聘需求分析", SKILLS_DIR / "04_job_market_analysis" / "SKILL.md",
             ["crawl_jobs", "normalize_job", "deduplicate_jobs", "query_skill_frequency",
              "query_salary", "query_job_trend"], ["demand[]", "counts"]),
    SkillDef("05_skill_ontology", "技能本体归一化", SKILLS_DIR / "05_skill_ontology" / "SKILL.md",
             ["calculate_skill_coverage"], ["skill_mentions[]"]),
    SkillDef("06_matching_model", "供需匹配与缺口模型", SKILLS_DIR / "06_matching_model" / "SKILL.md",
             ["calculate_matching", "calculate_skill_gap", "compare_schools", "simulate_curriculum_change"],
             ["matching", "skill_gaps", "simulation"]),
    SkillDef("07_policy_mechanism", "政策与机制分析", SKILLS_DIR / "07_policy_mechanism" / "SKILL.md",
             ["search_policy", "query_industry_direction", "run_regression", "run_shap_analysis"],
             ["policy", "mechanism"]),
    SkillDef("08_audit_and_report", "审计与报告", SKILLS_DIR / "08_audit_and_report" / "SKILL.md",
             ["trace_claim", "search_evidence", "list_sources"], ["report", "audit_log"]),
    SkillDef("10_scoped_report", "按层级交付与追问", SKILLS_DIR / "10_scoped_report" / "SKILL.md",
             ["render_scoped_report", "render_result_html", "resolve_scope"],
             ["report.md", "report.html", "scope"]),
    SkillDef("11_comprehensive_retrieval", "全面检索台账", SKILLS_DIR / "11_comprehensive_retrieval" / "SKILL.md",
             ["sweep_sources", "render_ledger_markdown"],
             ["retrieval_ledger", "online_plan"]),
]

SKILL_BY_ID = {s.skill_id: s for s in SKILLS}


def list_skills() -> list[dict]:
    return [s.to_dict() for s in SKILLS]

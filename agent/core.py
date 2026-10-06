"""TalentSupplyDemandAgent: the main agent used by the demo and the CLI."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from edumatch.config import Settings, load_settings
from edumatch.dataset import Dataset
from edumatch.engine import ResearchEngine, build_plan

from .llm import LLMConfig, polish
from .report import render_markdown


@dataclass
class AgentResult:
    query: str
    plan: dict[str, Any]
    report: str
    data: dict[str, Any]
    explanation: dict[str, Any] = field(default_factory=dict)
    started_at: str = ""
    finished_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "plan": self.plan,
            "report": self.report,
            "explanation": self.explanation,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "data": self.data,
        }


class TalentSupplyDemandAgent:
    """1 main agent + skills + tools + python analysis engine.

    Deliberately *not* a swarm of agents: the research workflow is a fixed,
    auditable pipeline, and the value comes from evidence discipline rather than
    from agent count.
    """

    name = "TalentSupplyDemandAgent"

    def __init__(
        self,
        dataset: Dataset | None = None,
        settings: Settings | None = None,
        llm_config: LLMConfig | None = None,
    ) -> None:
        self.settings = settings or load_settings()
        self.dataset = dataset or Dataset.build(self.settings)
        self.engine = ResearchEngine(self.dataset, self.settings)
        self.llm_config = llm_config or LLMConfig.from_env()

    def plan(self, query: str) -> dict[str, Any]:
        return build_plan(query, self.dataset).to_dict()

    def research(
        self,
        query: str,
        *,
        include_template: bool = False,
        simulate: bool = False,
        persist: bool = False,
        explain: bool = True,
        target_occupation: str | None = None,
        source_mode: str | None = None,
        harvest: bool = False,
        harvest_domain: str | None = None,
        harvest_kinds: list[str] | None = None,
        harvest_pages: list[dict[str, str]] | None = None,
        harvest_timeout_s: int | None = None,
        peers: str | list[str] | None = None,
        peer_max: int = 3,
        peer_harvest_kinds: list[str] | None = None,
        micro_profile: str | None = None,
        report_scope: str = "all",
    ) -> AgentResult:
        started = datetime.now(timezone.utc).isoformat()
        data = self.engine.run(
            query, include_template=include_template, persist=persist, simulation=simulate,
            target_occupation=target_occupation,
            source_mode=source_mode, harvest=harvest, harvest_domain=harvest_domain,
            harvest_kinds=harvest_kinds, harvest_pages=harvest_pages,
            harvest_timeout_s=harvest_timeout_s, peers=peers, peer_max=peer_max,
            peer_harvest_kinds=peer_harvest_kinds,
        )
        if micro_profile:
            data["micro_result"] = self.analyze_micro(
                micro_profile, data, run_id=str(data.get("run_id") or ""))
        data["report_scope"] = report_scope
        report = render_markdown(data, scope=report_scope)
        data["report"] = report
        explanation: dict[str, Any] = {}
        if explain:
            if "tsi_v2" in data:
                explanation = polish(report, data["tsi_v2"], self.llm_config)
            else:
                explanation = {
                    "provider": "deterministic_template",
                    "enabled": False,
                    "explanation": data.get("message", "该专业缺少数据，未生成结论。"),
                    "note": "无 TSI 结果时不调用解释层。",
                }
        result = AgentResult(
            query=query,
            plan=data["plan"],
            report=report,
            data=data,
            explanation=explanation,
            started_at=started,
            finished_at=datetime.now(timezone.utc).isoformat(),
        )
        return result

    def analyze_micro(
        self,
        profile_text: str,
        data: dict[str, Any],
        *,
        run_id: str = "",
    ) -> dict[str, Any]:
        """个人尺度：自然语言画像 × 同一目标岗位需求（保留原有问询交互）。"""
        from analysis import evaluation as evaluation_mod
        from edumatch.personal_extract import extract_personal_evidence
        from edumatch.profiles import PersonalEvidenceProfile

        profile = PersonalEvidenceProfile.from_text(profile_text)
        demand_map = {str(r.get("skill")): float(r.get("demand"))
                      for r in (data.get("demand_rows") or [])
                      if r.get("skill") and isinstance(r.get("demand"), (int, float))}
        occupation = (data.get("occupation") or {}).get("occupation") or {}
        result = evaluation_mod.evaluate_micro(
            profile, demand_map, occupation=occupation, run_id=run_id)
        result["input_kind"] = "natural_language"
        result["extracted"] = extract_personal_evidence(profile_text)
        return result

    def save(self, result: AgentResult, directory: Path | None = None) -> dict[str, Path]:
        directory = directory or (self.settings.processed_dir / "runs" / result.data["run_id"])
        directory.mkdir(parents=True, exist_ok=True)
        paths = {
            "report": directory / "report.md",
            "data": directory / "result.json",
            "plan": directory / "plan.json",
            "evidence": directory / "evidence.json",
        }
        paths["report"].write_text(result.report, encoding="utf-8")
        paths["data"].write_text(json.dumps(result.data, ensure_ascii=False, indent=2), encoding="utf-8")
        paths["plan"].write_text(json.dumps(result.plan, ensure_ascii=False, indent=2), encoding="utf-8")
        paths["evidence"].write_text(
            json.dumps(result.data["evidence"], ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return paths

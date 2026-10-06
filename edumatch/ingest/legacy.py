"""Read the legacy Coze intermediate artefacts.

These are LLM outputs from the old pipeline. They are ingested as evidence
level ``D`` (semantic extraction) and, critically, the old TSI score is
*recomputed* here from the published weight formula so that the old pipeline can
serve as a reproducible baseline instead of a remembered number.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Published legacy weights (docs: TSI指标搭建.docx)
TSI_V1_WEIGHTS: dict[str, float] = {
    "A11": 0.32 * 0.25,
    "A12": 0.32 * 0.38,
    "A13": 0.32 * 0.37,
    "A21": 0.68 * 0.06,
    "A22": 0.68 * 0.24,
    "A23": 0.68 * 0.41,
    "A24": 0.68 * 0.29,
    "B11": 0.17 * 0.60,
    "B12": 0.17 * 0.40,
    "B21": 0.20 * 0.50,
    "B22": 0.20 * 0.50,
    "B31": 0.23 * 0.28,
    "B32": 0.23 * 0.43,
    "B33": 0.23 * 0.29,
    "B41": 0.20 * 0.33,
    "B42": 0.20 * 0.67,
    "B51": 0.20 * 0.33,
    "B52": 0.20 * 0.67,
    "C11": 0.36 * 0.25,
    "C12": 0.36 * 0.45,
    "C13": 0.36 * 0.30,
    "C21": 0.34 * 0.30,
    "C22": 0.34 * 0.25,
    "C23": 0.34 * 0.45,
    "C31": 0.30 * 0.20,
    "C32": 0.30 * 0.45,
    "C33": 0.30 * 0.35,
}
TSI_V1_DIMENSION_WEIGHTS = {"A": 0.25, "B": 0.30, "C": 0.45}

TSI_V1_NAMES: dict[str, str] = {
    "A11": "专业设置依据科学性", "A12": "专业-产业匹配度", "A13": "培养目标与岗位能力一致性",
    "A21": "组织建设", "A22": "经费投入", "A23": "师资队伍", "A24": "硬软件投入",
    "B11": "培养方案对产业需求响应程度", "B12": "培养方案更新频率",
    "B21": "产业需求融入教学深度", "B22": "校企联合培养程度",
    "B31": "专业品牌", "B32": "行业声誉", "B33": "数字化教学水平",
    "B41": "校企共编教材", "B42": "企业参与课程开发",
    "B51": "实践学时设计合理性", "B52": "实践教学成效",
    "C11": "基本素养", "C12": "专业能力", "C13": "数字技能",
    "C21": "就业率", "C22": "就业稳定性", "C23": "专业-岗位匹配度",
    "C31": "用人单位总体满意度", "C32": "岗位胜任度", "C33": "创新与发展潜力",
}

WEIGHTED_OUTPUT_RE = re.compile(r"TSI\s*总分[:：]\s*([0-9]+(?:\.[0-9]+)?)")


def _dimension_of(indicator: str) -> str:
    return indicator[0]


def replay_tsi_v1(indicator_scores: dict[str, float]) -> dict[str, Any]:
    """Recompute the legacy TSI from its published weights (baseline, no LLM)."""
    # Legacy semantics: every indicator contributes with a fixed absolute weight;
    # "insufficient evidence" was submitted as the number 0.
    global_weights = {
        k: TSI_V1_DIMENSION_WEIGHTS[_dimension_of(k)] * w for k, w in TSI_V1_WEIGHTS.items()
    }
    dims: dict[str, float] = {}
    steps: list[dict[str, Any]] = []
    for dimension in ("A", "B", "C"):
        keys = [k for k in TSI_V1_WEIGHTS if _dimension_of(k) == dimension]
        value = sum(global_weights[k] * indicator_scores.get(k, 0.0) / 100.0 for k in keys)
        dims[dimension] = value
        steps.append(
            {
                "dimension": dimension,
                "value": round(value, 6),
                "n_indicators": sum(1 for k in keys if k in indicator_scores),
                "n_zero": sum(1 for k in keys if indicator_scores.get(k, 0.0) == 0.0),
            }
        )
    tsi = sum(dims.values())
    zero_indicators = [k for k, v in indicator_scores.items() if v == 0]
    return {
        "tsi_v1": round(tsi * 100, 4),
        "dimension_scores": {k: round(v * 100, 2) for k, v in dims.items()},
        "steps": steps,
        "n_indicators": len(indicator_scores),
        "n_zero_scores": len(zero_indicators),
        "zero_indicators": sorted(zero_indicators),
        "missing_indicators": [k for k in TSI_V1_WEIGHTS if k not in indicator_scores],
    }


@dataclass
class LegacyArtifacts:
    scores: dict[str, float] = field(default_factory=dict)
    score_reasoning: dict[str, str] = field(default_factory=dict)
    score_evidence: dict[str, str] = field(default_factory=dict)
    replay: dict[str, Any] = field(default_factory=dict)
    stated_final_tsi: float | None = None
    stated_final_text: str = ""
    teaching_documents: list[dict[str, Any]] = field(default_factory=list)
    employment_output: str = ""
    recruitment_output: str = ""
    policy_output: str = ""
    load_errors: list[str] = field(default_factory=list)


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8", errors="replace"))


def load_legacy(record_dir: Path) -> LegacyArtifacts:
    art = LegacyArtifacts()

    score_input = record_dir / "人工智能专业 TSI得分计算输入.txt"
    if score_input.exists():
        try:
            payload = _load_json(score_input)["input"]
            parsed = json.loads(payload) if isinstance(payload, str) else payload
            for key, item in parsed.items():
                art.scores[key] = float(item.get("score", 0))
                art.score_reasoning[key] = str(item.get("reasoning", ""))
                art.score_evidence[key] = str(item.get("evidence", ""))
        except Exception as exc:  # noqa: BLE001
            art.load_errors.append(f"{score_input.name}: {exc}")
    art.replay = replay_tsi_v1(art.scores) if art.scores else {}

    final_text = record_dir / "人工智能专业 最终TSI评价输出.txt"
    if final_text.exists():
        art.stated_final_text = final_text.read_text(encoding="utf-8", errors="replace")
        m = WEIGHTED_OUTPUT_RE.search(art.stated_final_text)
        if m:
            art.stated_final_tsi = float(m.group(1))

    teaching = record_dir / "教学.txt"
    if teaching.exists():
        try:
            payload = _load_json(teaching)
            art.teaching_documents = (payload.get("_input") or {}).get("input") or []
        except Exception as exc:  # noqa: BLE001
            art.load_errors.append(f"{teaching.name}: {exc}")

    for attr, name in (
        ("employment_output", "就业.txt"),
        ("recruitment_output", "招聘.txt"),
        ("policy_output", "政策.txt"),
    ):
        path = record_dir / name
        if path.exists():
            try:
                payload = _load_json(path)
                text = next((v for v in payload.values() if isinstance(v, str) and len(v) > 20), "")
                setattr(art, attr, text)
            except Exception as exc:  # noqa: BLE001
                art.load_errors.append(f"{name}: {exc}")
    return art


def missing_as_zero_report(scores: dict[str, float]) -> dict[str, Any]:
    """Quantify the legacy '缺失即 0 分' defect."""
    zeros = {k: v for k, v in scores.items() if v == 0}
    penalty = sum(
        TSI_V1_DIMENSION_WEIGHTS[_dimension_of(k)] * TSI_V1_WEIGHTS[k]
        for k in zeros
        if k in TSI_V1_WEIGHTS
    )
    return {
        "n_indicators": len(scores),
        "n_zero": len(zeros),
        "zero_ratio": round(len(zeros) / max(len(scores), 1), 4),
        "weight_penalty": round(penalty, 4),
        "weight_coverage_lost": round(penalty, 4),
        "zero_indicators": sorted(zeros),
    }

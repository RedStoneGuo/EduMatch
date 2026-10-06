"""Optional LLM adapter (OpenAI-compatible). Disabled by default.

The LLM is only allowed to *explain* and *summarise* numbers produced by the
analysis engine. ``polish()`` therefore receives the computed report as the only
source of numeric truth and is instructed to never invent numbers.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

SYSTEM_PROMPT = (
    "你是 EduMatch 的解释层，只做两件事：把已经计算好的指标翻译成高校管理者能读懂的语言；"
    "指出数据缺口与不确定性。禁止新增任何数字，禁止修改给定数字，禁止使用因果断言"
    "（不得写“导致/证明”，只能写“与……呈现关联/在模型中具有较高解释贡献”）。"
)


@dataclass
class LLMConfig:
    enabled: bool = False
    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-4o-mini"
    api_key: str = ""
    timeout: float = 60.0

    @classmethod
    def from_env(cls, *, enabled: bool | None = None) -> "LLMConfig":
        flag = os.environ.get("EDUMATCH_LLM_ENABLED", "").strip() in {"1", "true", "yes"} if enabled is None else enabled
        return cls(
            enabled=flag and bool(os.environ.get("OPENAI_API_KEY")),
            base_url=os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            model=os.environ.get("EDUMATCH_LLM_MODEL", "gpt-4o-mini"),
            api_key=os.environ.get("OPENAI_API_KEY", ""),
            timeout=float(os.environ.get("EDUMATCH_LLM_TIMEOUT", "60")),
        )


def polish(report: str, metrics: dict[str, Any], config: LLMConfig | None = None) -> dict[str, Any]:
    """Return an LLM-polished narrative, or a deterministic fallback."""
    config = config or LLMConfig.from_env()
    if not config.enabled:
        return {
            "provider": "deterministic_template",
            "enabled": False,
            "explanation": deterministic_explanation(metrics),
            "note": "未配置 LLM（EDUMATCH_LLM_ENABLED / OPENAI_API_KEY），使用可复现的模板解释层。",
        }
    try:
        import httpx

        payload = {
            "model": config.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(
                    {"report": report[:12000], "metrics": metrics}, ensure_ascii=False)[:20000]},
            ],
            "temperature": 0.2,
        }
        response = httpx.post(
            f"{config.base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {config.api_key}", "Content-Type": "application/json"},
            json=payload, timeout=config.timeout,
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        return {"provider": config.model, "enabled": True, "explanation": content}
    except Exception as exc:  # noqa: BLE001 - never break the deterministic path
        return {
            "provider": "deterministic_template",
            "enabled": False,
            "explanation": deterministic_explanation(metrics),
            "note": f"LLM 调用失败，已回退到模板解释：{exc}",
        }


def deterministic_explanation(tsi_result: dict[str, Any]) -> str:
    tsi = tsi_result.get("tsi_v2")
    band = tsi_result.get("band")
    dims = tsi_result.get("dimensions") or {}
    if tsi is None:
        return "本次运行未能计算 TSI：所有维度覆盖率均低于阈值，请补充数据后重试。"
    weakest = min(
        (v for v in dims.values() if v["score"] is not None),
        key=lambda v: v["score"], default=None,
    )
    strongest = max(
        (v for v in dims.values() if v["score"] is not None),
        key=lambda v: v["score"], default=None,
    )
    parts = [f"TSI 2.0 = {tsi:.2f}（{band}），加权覆盖率 {tsi_result['weighted_coverage'] * 100:.1f}%。"]
    if strongest is not None and weakest is not None:
        parts.append(
            f"其中{strongest['name']}相对靠前（{strongest['score']:.2f}），"
            f"{weakest['name']}是主要短板（{weakest['score']:.2f}）。"
        )
    missing = tsi_result.get("missing_indicators") or []
    if missing:
        parts.append(
            f"有 {len(missing)} 个指标因证据不足记为 null（{'、'.join(missing)}），"
            "这些缺失没有被折算成 0 分，结论时请一并说明数据缺口。"
        )
    return " ".join(parts)

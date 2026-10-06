"""Declarative tool registry.

Every tool is a plain Python function with a JSON-schema description, so the
same definition can be (a) called by the agent, (b) exported as an MCP tool, and
(c) unit-tested directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Callable

from edumatch.dataset import Dataset

from . import (analysis_tools, education, evidence_tools, literature_tools, policy,
               recruitment, supply_source)


@dataclass
class ToolSpec:
    name: str
    group: str
    description: str
    input_schema: dict[str, Any]
    handler: Callable[[Dataset, dict[str, Any]], Any]
    returns: str = ""
    requires: list[str] = field(default_factory=list)

    def to_mcp(self) -> dict[str, Any]:
        return {"name": self.name, "description": self.description, "inputSchema": self.input_schema}


def _collect() -> dict[str, ToolSpec]:
    specs: list[ToolSpec] = []
    for module in (education, recruitment, policy, analysis_tools, evidence_tools, literature_tools,
                   supply_source):
        specs.extend(module.specs())
    return {spec.name: spec for spec in specs}


TOOL_REGISTRY: dict[str, ToolSpec] = _collect()


@lru_cache(maxsize=1)
def _default_dataset() -> Dataset:
    return Dataset.build()


def list_tools(group: str | None = None) -> list[dict[str, Any]]:
    return [
        {"name": s.name, "group": s.group, "description": s.description,
         "inputSchema": s.input_schema, "returns": s.returns}
        for s in TOOL_REGISTRY.values() if group in (None, s.group)
    ]


def call_tool(name: str, arguments: dict[str, Any] | None = None, dataset: Dataset | None = None) -> Any:
    spec = TOOL_REGISTRY.get(name)
    if spec is None:
        raise KeyError(f"unknown tool: {name}")
    ds = dataset or _default_dataset()
    return spec.handler(ds, arguments or {})

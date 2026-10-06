"""Minimal MCP-compatible stdio server built on the standard library.

Transport: newline-delimited JSON-RPC 2.0 over stdin/stdout (MCP stdio
transport). Methods implemented: ``initialize``, ``tools/list``, ``tools/call``,
``ping``. No third-party SDK is required, so the servers run in the competition
environment without network access.

Usage:
    python -m mcp_servers.server --group education
    python -m mcp_servers.server --all            # expose all 33 tools
    python -m mcp_servers.server --selftest       # offline protocol check
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, TextIO

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from edumatch.dataset import Dataset  # noqa: E402
from edumatch.tools import TOOL_REGISTRY, call_tool  # noqa: E402

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "edumatch-mcp"
SERVER_VERSION = "2.0.0"


class MCPServer:
    def __init__(self, group: str | None = None, dataset: Dataset | None = None) -> None:
        self.group = group
        self.dataset = dataset
        self._dataset_cache: Dataset | None = dataset

    @property
    def tools(self) -> list[dict[str, Any]]:
        return [s.to_mcp() for s in TOOL_REGISTRY.values() if self.group in (None, s.group)]

    def _ds(self) -> Dataset:
        if self._dataset_cache is None:
            self._dataset_cache = Dataset.build()
        return self._dataset_cache

    def handle(self, request: dict[str, Any]) -> dict[str, Any] | None:
        method = request.get("method")
        req_id = request.get("id")
        params = request.get("params") or {}
        try:
            if method == "initialize":
                result = {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": f"{SERVER_NAME}{'-' + self.group if self.group else ''}",
                                   "version": SERVER_VERSION},
                }
            elif method == "notifications/initialized":
                return None
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                result = {"tools": self.tools}
            elif method == "tools/call":
                name = params.get("name")
                arguments = params.get("arguments") or {}
                if name not in {t["name"] for t in self.tools}:
                    raise KeyError(f"tool not available on this server: {name}")
                payload = call_tool(str(name), arguments, self._ds())
                result = {
                    "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False, indent=2)}],
                    "isError": False,
                }
            else:
                return {"jsonrpc": "2.0", "id": req_id,
                        "error": {"code": -32601, "message": f"method not found: {method}"}}
        except Exception as exc:  # noqa: BLE001 - MCP must answer with an error payload
            return {"jsonrpc": "2.0", "id": req_id,
                    "error": {"code": -32000, "message": f"{type(exc).__name__}: {exc}"}}
        return {"jsonrpc": "2.0", "id": req_id, "result": result}

    def serve(self, stdin: TextIO = sys.stdin, stdout: TextIO = sys.stdout) -> None:
        for line in stdin:
            line = line.strip()
            if not line:
                continue
            try:
                request = json.loads(line)
            except json.JSONDecodeError as exc:
                stdout.write(json.dumps(
                    {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": str(exc)}}) + "\n")
                stdout.flush()
                continue
            response = self.handle(request)
            if response is not None:
                stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
                stdout.flush()


def selftest(group: str | None = None) -> int:
    server = MCPServer(group)
    print(f"[1] initialize -> {server.handle({'id': 1, 'method': 'initialize'})['result']['serverInfo']}")
    tools = server.handle({"id": 2, "method": "tools/list"})["result"]["tools"]
    print(f"[2] tools/list -> {len(tools)} tools: {', '.join(t['name'] for t in tools[:6])} ...")
    for name, args in (("search_major", {"major": "人工智能"}), ("query_job_trend", {})):
        if name not in {t["name"] for t in tools}:
            continue
        payload = server.handle({"id": 3, "method": "tools/call",
                                 "params": {"name": name, "arguments": args}})["result"]
        print(f"[3] tools/call {name} -> {payload['content'][0]['text'][:120]} ...")
    print("[ok] MCP stdio server responds to initialize / tools/list / tools/call")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="EduMatch MCP server")
    ap.add_argument("--group", choices=["education", "recruitment", "policy", "analysis", "evidence"])
    ap.add_argument("--all", action="store_true", help="expose every group in one server")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)
    group = None if args.all else args.group
    if args.selftest:
        return selftest(group)
    MCPServer(group).serve()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

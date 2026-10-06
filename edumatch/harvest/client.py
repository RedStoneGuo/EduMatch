"""edu-material-harvest 插件客户端：MCP（stdio JSON-RPC）/ 脚本 / 离线回放 三种后端。

插件仓库自带一个零依赖 stdio MCP 服务端（``skills/edu-material-harvest/scripts/
mcp_server.py``）。本客户端启动它、走 NDJSON JSON-RPC 调用工具表：

    env_check → harvest_school {school, domain, kinds, auto=true} → job_id
              → job_wait {job_id, timeout_s} → 终态摘要
              → out/records.json 取逐份材料台账

另外两条后端用于降级与测试：

* ``script``  —— 直接调用插件文档化的 CLI（``discover.py --school … --domain … --auto``）；
* ``replay``  —— 不联网，回放一个既有的产出目录（离线验证与单元测试用）。

插件红线：只采官方免登录 ``*.edu.cn`` 源、**绝不猜域名**。因此域名必须显式给出，
或来自本地已核实的域名台账（``data/harvest/domains.json`` / 采集台账）。
"""

from __future__ import annotations

import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

PROTOCOL_VERSION = "2025-06-18"
DEFAULT_KINDS = ("培养方案", "专业介绍", "课程大纲", "年度报告")
JOB_ID_RE = re.compile(r"job_id=([A-Za-z0-9._\-]+)")


class HarvestUnavailable(RuntimeError):
    """插件不可用（未安装 / 缺依赖 / 后端启动失败）。"""


@dataclass
class HarvestConfig:
    """插件接入配置（全部相对项目根）。"""

    vendor_dir: Path
    script: Path
    work_dir: Path
    python: str = ""
    timeout_seconds: int = 900
    kinds: tuple[str, ...] = DEFAULT_KINDS
    backend: str = "mcp"

    @classmethod
    def from_settings(cls, settings) -> "HarvestConfig":
        section = dict(settings.section("harvest") or {})
        project_root = settings.project_root

        def _path(value: str, default: str) -> Path:
            raw = str(value or default)
            path = Path(raw)
            return path if path.is_absolute() else (project_root / path).resolve()

        vendor = _path(section.get("vendor_dir"), "vendor/edu-material-harvest")
        script = section.get("script") or "skills/edu-material-harvest/scripts/mcp_server.py"
        script_path = Path(str(script))
        if not script_path.is_absolute():
            script_path = vendor / script_path
        kinds = section.get("kinds") or list(DEFAULT_KINDS)
        return cls(
            vendor_dir=vendor,
            script=script_path,
            work_dir=_path(section.get("work_dir"), "data/harvest"),
            python=str(section.get("python") or ""),
            timeout_seconds=int(section.get("timeout_seconds") or 900),
            kinds=tuple(str(k) for k in kinds),
            backend=str(section.get("backend") or "mcp"),
        )

    def interpreter(self) -> str:
        return self.python or sys.executable

    def available(self) -> bool:
        return self.script.exists()

    def domains_path(self) -> Path:
        return self.work_dir / "domains.json"

    def resolve_domain(self, school: str) -> str:
        """按本地已核实台账解析官方域名；解析不到返回空串（绝不猜）。"""
        path = self.domains_path()
        if not path.exists():
            return ""
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return ""
        if isinstance(payload, dict):
            entry = payload.get(school)
            if isinstance(entry, str):
                return entry
            if isinstance(entry, dict):
                return str(entry.get("domain") or "")
            for value in payload.values():
                if isinstance(value, dict) and value.get("school") == school:
                    return str(value.get("domain") or "")
        if isinstance(payload, list):
            for item in payload:
                if isinstance(item, dict) and item.get("school") == school:
                    return str(item.get("domain") or "")
        return ""


@dataclass
class HarvestOutcome:
    school: str
    domain: str
    out_dir: str
    backend: str
    job_id: str = ""
    state: str = ""
    summary: str = ""
    log_tail: list[str] = field(default_factory=list)
    records: list[dict[str, Any]] = field(default_factory=list)
    n_errors: int = 0
    error: str = ""

    @property
    def n_materials(self) -> int:
        return sum(1 for r in self.records if r.get("file"))

    def by_kind(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for record in self.records:
            if not record.get("file"):
                continue
            kind = str(record.get("kind") or "未分类")
            out[kind] = out.get(kind, 0) + 1
        return dict(sorted(out.items(), key=lambda kv: -kv[1]))

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "n_materials": self.n_materials, "by_kind": self.by_kind()}


class _MCPProcess:
    """一条到插件 MCP 服务端的 stdio 连接（后台读线程 + 请求-应答配对）。"""

    def __init__(self, script: Path, python: str, cwd: Path, timeout: float) -> None:
        self.script = script
        self.timeout = timeout
        env = dict(os.environ)
        env.setdefault("PYTHONIOENCODING", "utf-8")
        env.setdefault("PYTHONUTF8", "1")
        try:
            self.proc = subprocess.Popen(
                [python, str(script)],
                cwd=str(cwd),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                env=env,
            )
        except OSError as exc:  # 解释器不存在等
            raise HarvestUnavailable(f"无法启动插件 MCP 服务端：{exc}") from exc
        self._queue: "queue.Queue[str | None]" = queue.Queue()
        self._id = 0
        self._lock = threading.Lock()
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self) -> None:
        assert self.proc.stdout is not None
        for line in self.proc.stdout:
            line = line.strip()
            if line:
                self._queue.put(line)
        self._queue.put(None)

    def close(self) -> None:
        try:
            if self.proc.stdin:
                self.proc.stdin.close()
        except OSError:
            pass
        try:
            self.proc.terminate()
            self.proc.wait(timeout=5)
        except Exception:  # noqa: BLE001
            try:
                self.proc.kill()
            except OSError:
                pass

    def send(self, payload: dict[str, Any]) -> None:
        if self.proc.stdin is None:
            raise HarvestUnavailable("MCP 服务端 stdin 不可用")
        self.proc.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
        self.proc.stdin.flush()

    def request(self, method: str, params: dict[str, Any], *, timeout: float | None = None) -> dict[str, Any]:
        with self._lock:
            self._id += 1
            mid = self._id
        self.send({"jsonrpc": "2.0", "id": mid, "method": method, "params": params})
        deadline = time.monotonic() + (timeout or self.timeout)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"MCP 调用超时：{method}")
            try:
                line = self._queue.get(timeout=remaining)
            except queue.Empty as exc:
                raise TimeoutError(f"MCP 调用超时：{method}") from exc
            if line is None:
                raise HarvestUnavailable("MCP 服务端已退出（stdout 关闭）")
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            if message.get("id") != mid:
                continue
            if "error" in message:
                raise HarvestUnavailable(f"MCP 错误：{message['error']}")
            return message.get("result") or {}

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        self.send({"jsonrpc": "2.0", "method": method, "params": params or {}})

    def initialize(self) -> dict[str, Any]:
        result = self.request("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "EduMatch", "version": "2.0"},
        })
        self.notify("notifications/initialized")
        return result

    def call_tool(self, name: str, arguments: dict[str, Any], *, timeout: float | None = None) -> dict[str, Any]:
        result = self.request("tools/call", {"name": name, "arguments": arguments}, timeout=timeout)
        content = result.get("content") or []
        text = "\n".join(str(c.get("text") or "") for c in content if isinstance(c, dict))
        if result.get("isError"):
            raise HarvestUnavailable(f"插件工具 {name} 失败：{text}")
        return {"text": text, "structured": result.get("structuredContent")}


class HarvestClient:
    """面向 EduMatch 的插件门面：一次调用完成"采集 → 等终态 → 收台账"。"""

    def __init__(self, config: HarvestConfig) -> None:
        self.config = config
        self._mcp: _MCPProcess | None = None
        self.calls: list[dict[str, Any]] = []

    # ---------- lifecycle ----------
    def _connect(self) -> _MCPProcess:
        if self._mcp is None:
            if not self.config.available():
                raise HarvestUnavailable(
                    f"未找到插件：{self.config.script}（请把 edu-material-harvest 放到 "
                    f"{self.config.vendor_dir}）"
                )
            self._mcp = _MCPProcess(
                self.config.script, self.config.interpreter(),
                self.config.vendor_dir, float(self.config.timeout_seconds),
            )
            self._mcp.initialize()
        return self._mcp

    def close(self) -> None:
        if self._mcp is not None:
            self._mcp.close()
            self._mcp = None

    def __enter__(self) -> "HarvestClient":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # ---------- tools ----------
    def _call(self, name: str, arguments: dict[str, Any], *, timeout: float | None = None) -> dict[str, Any]:
        started = time.monotonic()
        client = self._connect()
        result = client.call_tool(name, arguments, timeout=timeout)
        self.calls.append({
            "tool": name, "arguments": arguments,
            "elapsed_ms": round((time.monotonic() - started) * 1000, 1),
            "summary": (result.get("text") or "")[:400],
        })
        return result

    def env_check(self) -> str:
        return str(self._call("env_check", {}).get("text") or "")

    def list_tools(self) -> list[dict[str, Any]]:
        client = self._connect()
        return list(client.request("tools/list", {}).get("tools") or [])

    def out_dir_for(self, school: str) -> Path:
        safe = re.sub(r"[\\/:*?\"<>|]", "_", school).strip() or "school"
        return self.config.work_dir / "收割" / safe

    def harvest(
        self, school: str, domain: str, *, kinds: Iterable[str] | None = None,
        out: Path | str | None = None, timeout_s: int | None = None,
    ) -> HarvestOutcome:
        """一键采集：discover → download → 台账，返回终态与 records 台账。"""
        out_dir = Path(out) if out else self.out_dir_for(school)
        out_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "school": school,
            "domain": domain,
            "kinds": list(kinds or self.config.kinds),
            "auto": True,
            "out": str(out_dir),
        }
        first = self._call("harvest_school", payload)
        job_id = _extract_job_id(str(first.get("text") or ""), first.get("structured"))
        return self._finish(school, domain, out_dir, job_id, timeout_s)

    def harvest_pages(
        self, school: str, domain: str, pages: list[dict[str, str]], *,
        out: Path | str | None = None, timeout_s: int | None = None,
    ) -> HarvestOutcome:
        """承载页直采：Agent 先用联网搜索定位承载页，再交给插件枚举+下载。"""
        out_dir = Path(out) if out else self.out_dir_for(school)
        out_dir.mkdir(parents=True, exist_ok=True)
        first = self._call("harvest_pages", {
            "school": school, "domain": domain, "pages": pages,
            "auto": True, "out": str(out_dir),
        })
        job_id = _extract_job_id(str(first.get("text") or ""), first.get("structured"))
        return self._finish(school, domain, out_dir, job_id, timeout_s)

    def discover(self, school: str, domain: str, *, kinds: Iterable[str] | None = None,
                 out: Path | str | None = None, timeout_s: int | None = None) -> HarvestOutcome:
        """只侦察，不下载（产出 candidates.md 供人工过目）。"""
        out_dir = Path(out) if out else self.out_dir_for(school)
        out_dir.mkdir(parents=True, exist_ok=True)
        first = self._call("discover_school", {
            "school": school, "domain": domain,
            "kinds": list(kinds or self.config.kinds), "out": str(out_dir),
        })
        job_id = _extract_job_id(str(first.get("text") or ""), first.get("structured"))
        return self._finish(school, domain, out_dir, job_id, timeout_s)

    def read_artifacts(self, out: Path | str, which: str) -> str:
        return str(self._call("read_artifacts", {"out": str(out), "which": which}).get("text") or "")

    def _finish(self, school: str, domain: str, out_dir: Path,
                job_id: str, timeout_s: int | None) -> HarvestOutcome:
        outcome = HarvestOutcome(school=school, domain=domain, out_dir=str(out_dir),
                                 backend="mcp", job_id=job_id)
        if job_id:
            waited = self._call("job_wait", {
                "job_id": job_id,
                "timeout_s": int(timeout_s or self.config.timeout_seconds),
            }, timeout=float(timeout_s or self.config.timeout_seconds) + 30)
            text = str(waited.get("text") or "")
            outcome.summary = text
            outcome.log_tail = [line for line in text.splitlines() if line.strip()][-30:]
            match = re.search(r"状态=(\S+)", text)
            outcome.state = match.group(1) if match else ""
        records_path = out_dir / "records.json"
        if records_path.exists():
            try:
                outcome.records = json.loads(records_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                outcome.records = []
        outcome.n_errors = sum(1 for r in outcome.records if not r.get("file"))
        return outcome

    # ---------- offline ----------
    @staticmethod
    def replay(out_dir: Path | str, *, school: str = "", domain: str = "") -> HarvestOutcome:
        """离线回放：直接读一个既有产出目录（不启动插件、不联网）。"""
        out = Path(out_dir)
        outcome = HarvestOutcome(school=school, domain=domain, out_dir=str(out), backend="replay")
        records_path = out / "records.json"
        if records_path.exists():
            try:
                outcome.records = json.loads(records_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                outcome.records = []
        outcome.state = "replay"
        outcome.n_errors = sum(1 for r in outcome.records if not r.get("file"))
        return outcome


def _extract_job_id(text: str, structured: Any = None) -> str:
    if isinstance(structured, dict):
        for key in ("job_id", "id"):
            if structured.get(key):
                return str(structured[key])
    match = JOB_ID_RE.search(text or "")
    return match.group(1) if match else ""

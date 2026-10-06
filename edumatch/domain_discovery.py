"""院校域名发现与验证：让系统能自己找到目标院校的官网，而不是被"台账没有"卡死。

工作方式（本地辅助 + 外部候选 + 规则核验）：

1. **本地优先**：已核实台账 `data/harvest/domains.json`、承载页台账
   `data/harvest/carrier_pages.json`、采集台账与 `data/source` 目录里出现过的
   URL/域名 —— 这些是**交叉验证**，不是唯一来源；
2. **外部候选**：大模型自行联网检索到的官网 URL（或承载页 URL）通过
   ``candidates=`` / ``--candidate`` 传进来；
3. **规则核验**（必须全部满足才算通过）：
   - 协议 http/https，主机名以官方后缀结尾（``.edu.cn`` / ``.edu`` / ``.ac.cn``
     或本地台账里该院校已核实的域名后缀）；
   - 实际请求返回 200；
   - 页面正文或标题里出现**院校名**（或其去掉"（）"后的核心名）。
4. **通过即入库**：把 ``domain / source_url / evidence / verified_at`` 写进
   `data/harvest/domains.json`（保留原有条目），下次直接复用。

核验不通过就如实记录原因，**不写台账、不用于采集**。
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

OFFICIAL_SUFFIXES: tuple[str, ...] = (".edu.cn", ".edu", ".ac.cn")
URL_RE = re.compile(r"https?://[^\s\"'<>）)】\]]+")
USER_AGENT = "Mozilla/5.0 (compatible; EduMatch/1.0; official-source verification)"


def _domains_path(project_root: Path) -> Path:
    return Path(project_root) / "data" / "harvest" / "domains.json"


def load_domain_ledger(project_root: Path) -> dict[str, Any]:
    path = _domains_path(project_root)
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def ledger_domain(project_root: Path, school: str) -> str:
    payload = load_domain_ledger(project_root)
    entry = payload.get(school)
    if isinstance(entry, str):
        return entry
    if isinstance(entry, dict):
        return str(entry.get("domain") or "")
    return ""


def school_core_names(school: str) -> list[str]:
    """院校名的可用匹配形式：全名、去括号名、去掉"大学/学院"的核心名。"""
    name = str(school or "").strip()
    if not name:
        return []
    forms = [name]
    stripped = re.sub(r"[（(][^）)]*[）)]", "", name).strip()
    if stripped and stripped not in forms:
        forms.append(stripped)
    core = re.sub(r"(大学|学院|学校)$", "", stripped)
    if core and core not in forms and len(core) >= 2:
        forms.append(core)
    return forms


def local_domain_candidates(project_root: Path, school: str) -> list[dict[str, Any]]:
    """本地辅助：台账 / 承载页台账 / 采集台账里出现过的该院校 URL 与域名。"""
    root = Path(project_root)
    out: list[dict[str, Any]] = []
    ledger = ledger_domain(root, school)
    if ledger:
        out.append({"url": f"https://{ledger}/" if not ledger.startswith("http") else ledger,
                    "source": "domains.json", "kind": "ledger"})
    for name in ("carrier_pages.json",):
        path = root / "data" / "harvest" / name
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        for url in URL_RE.findall(json.dumps(payload, ensure_ascii=False)):
            if school in url or any(form in url for form in school_core_names(school)):
                out.append({"url": url, "source": name, "kind": "carrier"})
    for base in (root / "data" / "source" / "采集台账", root / "data" / "harvest"):
        if not base.exists():
            continue
        for path in list(base.rglob("*.json"))[:40]:
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if school not in text:
                continue
            for url in URL_RE.findall(text)[:5]:
                out.append({"url": url, "source": str(path.relative_to(root).as_posix()),
                            "kind": "archive"})
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for item in out:
        if item["url"] in seen:
            continue
        seen.add(item["url"])
        unique.append(item)
    return unique


def _host(url: str) -> str:
    match = re.match(r"https?://([^/]+)", url or "")
    return (match.group(1) if match else "").lower()


def _fetch(url: str, *, timeout: float = 12.0) -> tuple[int, str]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - 只读公开站点
        raw = resp.read(200_000)
        charset = resp.headers.get_content_charset() or "utf-8"
        return int(getattr(resp, "status", 200)), raw.decode(charset, errors="ignore")


def verify_candidate(
    url: str,
    school: str,
    *,
    allow_network: bool = True,
    timeout: float = 12.0,
    fetch=_fetch,
) -> dict[str, Any]:
    """按「官方后缀 + HTTP 200 + 页面含校名」核验一个候选 URL。"""
    result: dict[str, Any] = {"url": url, "school": school, "ok": False, "reason": ""}
    host = _host(url)
    if not host:
        result["reason"] = "URL 不合法（缺少主机名）"
        return result
    result["domain"] = host
    if not host.endswith(OFFICIAL_SUFFIXES):
        result["reason"] = (f"域名后缀不是官方教育域（{host} 不以 "
                            + " / ".join(OFFICIAL_SUFFIXES) + " 结尾）")
        return result
    if not allow_network:
        result["reason"] = "离线模式：未发起网络核验"
        return result
    try:
        status, body = fetch(url, timeout=timeout)
    except urllib.error.HTTPError as exc:
        result["reason"] = f"HTTP {exc.code}（页面不可访问）"
        return result
    except Exception as exc:  # noqa: BLE001 - 网络/解析失败都算核验不通过
        result["reason"] = f"{type(exc).__name__}: {exc}"
        return result
    result["http_status"] = status
    if status != 200:
        result["reason"] = f"HTTP {status}（非 200）"
        return result
    title = ""
    match = re.search(r"<title[^>]*>(.*?)</title>", body, re.S | re.I)
    if match:
        title = re.sub(r"\s+", " ", match.group(1)).strip()[:120]
    hit = next((form for form in school_core_names(school) if form in body), "")
    if not hit and title:
        hit = next((form for form in school_core_names(school) if form in title), "")
    if not hit:
        result["reason"] = "页面未出现该院校名称（无法确认属于这所学校）"
        result["title"] = title
        return result
    result.update({"ok": True, "matched_name": hit, "title": title,
                   "reason": "官方教育域 + HTTP 200 + 页面含院校名，核验通过"})
    return result


def _write_ledger(project_root: Path, school: str, verified: dict[str, Any]) -> None:
    path = _domains_path(project_root)
    payload = load_domain_ledger(project_root)
    payload[school] = {
        "domain": verified["domain"],
        "source_url": verified["url"],
        "evidence": {"matched_name": verified.get("matched_name"),
                     "title": verified.get("title"),
                     "http_status": verified.get("http_status")},
        "verified_by": "domain_discovery.verify_candidate",
        "verified_at": datetime.now(timezone.utc).isoformat(),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def discover_domain(
    project_root: Path,
    school: str,
    *,
    candidates: Sequence[str] | Iterable[str] = (),
    allow_network: bool = True,
    write: bool = True,
) -> dict[str, Any]:
    """返回 ``{ok, domain, source, url, reason, tried}``。

    顺序：本地台账 → 本地存档 URL（若本来就已核实）→ 外部候选（逐个核验）。
    外部候选通过后写入台账，后续直接复用。
    """
    project_root = Path(project_root)
    tried: list[dict[str, Any]] = []
    ledger = ledger_domain(project_root, school)
    if ledger:
        return {"ok": True, "domain": ledger, "source": "ledger",
                "url": f"https://{ledger}/", "reason": "命中本地已核实台账", "tried": tried}
    for item in candidates:
        verified = verify_candidate(str(item), school, allow_network=allow_network)
        tried.append(verified)
        if verified.get("ok"):
            if write:
                _write_ledger(project_root, school, verified)
            return {**verified, "source": "candidate"}
    for item in local_domain_candidates(project_root, school):
        verified = verify_candidate(item["url"], school, allow_network=allow_network)
        verified["source"] = item.get("source", "")
        tried.append(verified)
        if verified.get("ok"):
            if write:
                _write_ledger(project_root, school, verified)
            return verified
    return {"ok": False, "domain": "", "school": school, "tried": tried,
            "reason": ("没有可核验的官方域名：请先联网检索该校官网/承载页 URL，"
                       "再用 --candidate 交给系统核验（官方教育域 + HTTP 200 + 页面含校名）。")}

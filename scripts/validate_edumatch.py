"""Automatic quality gate for the EduMatch upgrade (spec §49).

Checks five families of invariants and prints a machine-readable report:

* **数值**  Primary TSI ∈ [0,100]；维度权重和 = 1；无 NaN / 非法负值
* **TSI**   正式总分唯一；Match 已被降级为子指标
* **Missing**  status=insufficient_evidence 的指标 value 必须为 None（不等于 0）
* **语义**  报告中不得残留"总供给 / 总需求 / 16,161 个岗位需求 / 13 所代表全市"等表述
* **证据链** 有值的指标必须能挂到证据或打分依据

用法：

    python scripts\\validate_edumatch.py
    python scripts\\validate_edumatch.py --json audit/validation_report.json

退出码 0 = 无 error；1 = 存在 error（warning 不影响退出码）。
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

CORE = Path(__file__).resolve().parents[1]
PROJECT = CORE.parent
sys.path.insert(0, str(CORE))

from analysis import primary_tsi  # noqa: E402
from edumatch import semantics  # noqa: E402

RESULT_CANDIDATES = (
    CORE / "data" / "processed" / "result.json",
    PROJECT / "EduMatch-演示页面" / "_build" / "_macro_probe.json",
)

# 目录名不写死：本地包叫 EduMatch，公开发布包叫 EduMatch，都能正确匹配。
_CORE_DIR = CORE.name
REPORT_GLOBS = (
    "EduMatch-演示页面/*.md",
    "EduMatch-演示页面/*.html",
    f"{_CORE_DIR}/README.md",
    f"{_CORE_DIR}/交接文档.md",
    # 整包单独拷走（没有同级演示页面）时，仍然覆盖包内自有文档与产物
    f"{_CORE_DIR}/docs/*.md",
    f"{_CORE_DIR}/AGENTS.md",
    f"{_CORE_DIR}/PROMPT.md",
)


class Report:
    def __init__(self) -> None:
        self.items: list[dict[str, Any]] = []

    def add(self, check_id: str, level: str, message: str, detail: Any = None) -> None:
        self.items.append({"check": check_id, "level": level,
                           "message": message, "detail": detail})

    def error(self, check_id: str, message: str, detail: Any = None) -> None:
        self.add(check_id, "error", message, detail)

    def warn(self, check_id: str, message: str, detail: Any = None) -> None:
        self.add(check_id, "warn", message, detail)

    def ok(self, check_id: str, message: str, detail: Any = None) -> None:
        self.add(check_id, "ok", message, detail)

    @property
    def n_errors(self) -> int:
        return sum(1 for i in self.items if i["level"] == "error")

    @property
    def n_warnings(self) -> int:
        return sum(1 for i in self.items if i["level"] == "warn")

    def to_dict(self) -> dict[str, Any]:
        return {"summary": {"errors": self.n_errors, "warnings": self.n_warnings,
                            "checks": len(self.items)},
                "items": self.items}


def _load_result() -> tuple[Path | None, dict[str, Any] | None]:
    for path in RESULT_CANDIDATES:
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        data = payload.get("data") if isinstance(payload, dict) and "data" in payload else payload
        if isinstance(data, dict) and data.get("primary_tsi"):
            return path, data
    return None, None


def check_weights(report: Report) -> None:
    dim_sum = sum(v["weight"] for v in primary_tsi.DIMENSIONS.values())
    if math.isclose(dim_sum, 1.0, abs_tol=1e-9):
        report.ok("weights.dimensions", f"维度权重和 = {dim_sum:.4f}")
    else:
        report.error("weights.dimensions", f"维度权重和 ≠ 1：{dim_sum}")
    for dim, specs in primary_tsi.SPECS_BY_DIMENSION.items():
        total = sum(s.weight for s in specs)
        if math.isclose(total, 1.0, abs_tol=1e-9):
            report.ok(f"weights.{dim}", f"{dim} 维内权重和 = {total:.4f}")
        else:
            report.error(f"weights.{dim}", f"{dim} 维内权重和 ≠ 1：{total}")


def _walk_metrics(primary: dict[str, Any]) -> list[dict[str, Any]]:
    return list(primary.get("metrics") or [])


def check_numeric(report: Report, primary: dict[str, Any]) -> None:
    value = primary.get("primary_tsi")
    if value is None:
        report.warn("numeric.primary_tsi", "Primary TSI 未计算（可能证据不足）")
    elif not (0 <= float(value) <= 100):
        report.error("numeric.primary_tsi", f"Primary TSI 越界：{value}")
    else:
        report.ok("numeric.primary_tsi", f"Primary TSI = {value} ∈ [0,100]")
    for dim, item in (primary.get("dimensions") or {}).items():
        score = item.get("score")
        if score is None:
            continue
        if math.isnan(score) or not (0 <= score <= 100):
            report.error(f"numeric.dimension.{dim}", f"维度得分非法：{score}")
    for metric in _walk_metrics(primary):
        v = metric.get("value")
        if isinstance(v, float) and math.isnan(v):
            report.error(f"numeric.metric.{metric.get('metric_id')}", "出现 NaN")
        if v is not None and isinstance(v, (int, float)) and v < 0:
            report.error(f"numeric.metric.{metric.get('metric_id')}",
                         f"指标得分为负：{v}")


def check_missing(report: Report, primary: dict[str, Any]) -> None:
    bad = [m.get("metric_id") for m in _walk_metrics(primary)
           if m.get("status") == "insufficient_evidence" and m.get("value") is not None]
    if bad:
        report.error("missing.not_zero", "证据不足的指标被赋予了数值（应记 None）", bad)
    else:
        report.ok("missing.not_zero", "缺失指标均为 None，未记 0")
    counted = [m.get("metric_id") for m in _walk_metrics(primary)
               if m.get("value") == 0]
    if counted:
        report.warn("missing.zero_valued",
                    "以下指标值为 0，需确认是真实 0 还是缺失误记", counted)


def check_tsi_singleton(report: Report, primary: dict[str, Any]) -> None:
    registry = primary.get("versions") or primary.get("tsi_versions") or {}
    formal = [k for k, v in registry.items() if isinstance(v, dict) and v.get("role") == "primary"]
    if not registry:
        report.warn("tsi.singleton", "结果中未找到 tsi_versions 版本注册表")
        return
    if len(formal) == 1:
        report.ok("tsi.singleton", f"唯一正式总分：{formal[0]}")
    else:
        report.error("tsi.singleton", f"正式总分不唯一：{formal}")


def check_semantics(report: Report) -> None:
    files: list[Path] = []
    for pattern in REPORT_GLOBS:
        files.extend(sorted(PROJECT.glob(pattern)))
    sibling = PROJECT / "EduMatch-演示页面"
    if not sibling.exists():
        report.warn("semantics.scope",
                    "未找到同级 EduMatch-演示页面（整包单独拷贝时正常），"
                    "本轮语义检查只覆盖 core 内部文档与产物")
    total = 0
    for path in files:
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        findings = semantics.find_forbidden_claims(text)
        if findings:
            total += len(findings)
            report.error("semantics.quantity_claims",
                         f"{path.relative_to(PROJECT)} 含 {len(findings)} 处违规数量表述",
                         findings[:6])
    if total == 0:
        report.ok("semantics.quantity_claims", f"抽检 {len(files)} 份报告，未发现违规数量表述")


def check_match_demoted(report: Report) -> None:
    offenders: list[str] = []
    for path in sorted(PROJECT.glob("EduMatch-演示页面/*.md")):
        text = path.read_text(encoding="utf-8", errors="ignore")
        if "模型主输出" in text:
            offenders.append(str(path.relative_to(PROJECT)))
    if offenders:
        report.warn("tsi.match_demoted", "Match 仍被标为『主输出』，应降级为子指标", offenders)
    else:
        report.ok("tsi.match_demoted", "未发现把 Match 当作主总分的表述")


def check_evidence_chain(report: Report, primary: dict[str, Any]) -> None:
    broken: list[str] = []
    for metric in _walk_metrics(primary):
        if metric.get("value") is None:
            continue
        has_ids = bool(metric.get("evidence_ids"))
        has_basis = bool((metric.get("detail") or {}).get("formula")
                         or (metric.get("detail") or {}).get("source_metric"))
        if not has_ids and not has_basis:
            broken.append(metric.get("metric_id"))
    if broken:
        report.warn("evidence.chain", "以下有值指标缺少证据 ID 与打分依据", broken)
    else:
        report.ok("evidence.chain", "有值指标均带证据 ID 或打分依据")


def run() -> Report:
    report = Report()
    check_weights(report)
    path, data = _load_result()
    if data is None:
        report.warn("result.load", "未找到可用的 result.json / _macro_probe.json")
    else:
        report.ok("result.load", f"已加载 {path}")
        check_numeric(report, data["primary_tsi"])
        check_missing(report, data["primary_tsi"])
        check_tsi_singleton(report, data["primary_tsi"])
        check_evidence_chain(report, data["primary_tsi"])
    check_semantics(report)
    check_match_demoted(report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="EduMatch 自动质量检查")
    parser.add_argument("--json", type=Path, default=None, help="输出 JSON 报告路径")
    args = parser.parse_args()
    report = run()
    payload = report.to_dict()
    for item in report.items:
        if item["level"] == "ok":
            continue
        mark = "ERROR" if item["level"] == "error" else "WARN "
        print(f"[{mark}] {item['check']}: {item['message']}")
        if item["detail"]:
            print(f"        {item['detail']}")
    print(f"\n结果：{report.n_errors} error / {report.n_warnings} warning / "
          f"{len(report.items)} checks")
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                             encoding="utf-8")
        print(f"报告已写入 {args.json}")
    return 1 if report.n_errors else 0


if __name__ == "__main__":
    raise SystemExit(main())

"""CLI：高校覆盖端到端审计（发现 → 状态机 → 覆盖报告）。

    python scripts\\audit_university_coverage.py --major 人工智能 --province 北京市
    python scripts\\audit_university_coverage.py --major 人工智能 --schools 北京工业大学,北京邮电大学
    python scripts\\audit_university_coverage.py --major 人工智能 --json data/processed/coverage_audit.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

CORE = Path(__file__).resolve().parents[1]
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))

from edumatch.coverage_pipeline import audit_university_coverage  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="EduMatch 高校覆盖审计")
    ap.add_argument("--province", default="北京市")
    ap.add_argument("--major", default="人工智能")
    ap.add_argument("--schools", default=None, help="逗号分隔的院校名；缺省用省市名单")
    ap.add_argument("--required", default="培养方案课程,培养目标",
                    help="判定为已覆盖所必需的材料类型")
    ap.add_argument("--json", type=Path, default=None)
    ap.add_argument("--top", type=int, default=20)
    args = ap.parse_args()
    schools = [s.strip() for s in args.schools.split(",") if s.strip()] if args.schools else None
    payload = audit_university_coverage(
        CORE, province=args.province, major=args.major, schools=schools,
        required=[s.strip() for s in args.required.split(",") if s.strip()],
    )
    print(f"省市 {payload['province']} · 专业「{payload['major']}」")
    print(f"目标高校 {payload['n_target']} · 已覆盖 {payload['n_covered']} "
          f"· 覆盖率 {payload['coverage_rate'] * 100:.1f}%")
    print(f"缺失院校（前 {args.top}）：")
    for school in payload["missing_universities"][:args.top]:
        info = (payload.get("per_school") or {}).get(school) or {}
        missing = "、".join(info.get("missing_materials") or [])
        print(f"  - {school}：缺 {missing or '—'}")
    for reason in payload.get("failure_reasons", [])[:args.top]:
        print(f"  失败原因 {reason['n']} 次：{reason['reason']}")
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"报告已写入 {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

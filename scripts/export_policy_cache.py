"""把 `data/source/政策文件/` 的原始文件**预解析**成一个 JSON 缓存。

    python scripts\\export_policy_cache.py

产出：``data/processed/policies.json``（政策记录 + 去重清单 + 来源说明）

为什么需要：政策原文是 147 个 docx/pdf/xls 文件（26.4 MB），运行时要逐个抽文本；
公开发布包不便携带这么多原始件，于是改成"导出一次、运行时读缓存"。
**本地行为不变**：只要 `data/source/政策文件/` 存在且非空，`Dataset.build()` 仍然按原路径实时解析；
只有该目录缺失（发布包场景）时才回退读这个缓存。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

CORE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CORE))

from edumatch.config import load_settings  # noqa: E402
from edumatch.ingest.policy import deduplicate, ingest_policy_dir  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="导出政策库 JSON 缓存")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args(argv)
    settings = load_settings()
    policy_dir = settings.resolve(
        settings.raw.get("ingestion", {}).get("policy_dir", "data/source/政策文件"))
    if not policy_dir.exists():
        print(f"[error] 政策目录不存在：{policy_dir}")
        return 1
    records = ingest_policy_dir(
        policy_dir,
        max_chars=int(settings.raw.get("ingestion", {}).get("max_policy_chars", 20000)),
    )
    kept, dupes = deduplicate(records)
    out = args.out or (settings.processed_dir / "policies.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "source_dir": "data/source/政策文件",
        "n_files": sum(1 for p in policy_dir.rglob("*") if p.is_file()),
        "n_records": len(kept),
        "n_duplicates": len(dupes),
        "note": ("政策原文的预解析缓存：本地存在 data/source/政策文件/ 时仍实时解析，"
                 "该目录缺失时才读本文件（公开发布包即此场景）。"
                 "文本状态 text_status=extractor_unavailable 表示该文件抽不出文本层。"),
        "duplicates": dupes,
        "records": [r.to_dict() for r in kept],
    }
    out.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({
        "files": payload["n_files"], "records": payload["n_records"],
        "duplicates": payload["n_duplicates"],
        "mb": round(out.stat().st_size / 1024 / 1024, 2), "out": str(out),
    }, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# -*- coding: utf-8 -*-
"""生成"零真实数据"的报告模板 HTML（供 Agent 每次生成时参考结构与维度）。

运行（在 EduMatch 目录下）：

    python reporting/templates/build_page_template.py

产出：
    reporting/templates/page_template.html   ← 模板（无任何真实数据）
    reporting/templates/page_template_micro.html

模板只演示**结构与维度**：所有数值为 null（显示为「—」或「未获取」），文本为占位语。
Agent 生成正式报告时，应使用同一套 `reporting.render` / `theme` / `components`，
把占位换成引擎结果里的真实值。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CORE = HERE.parents[1]
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))

from reporting.render import render_result  # noqa: E402

BANNER = ("这是**零真实数据的报告模板**：只演示结构与维度，所有数值为占位（null / 未获取）。"
          "正式报告请用本模板同一套版式（reporting.render）填入引擎结果。"
          "禁止把模板里的占位当成任何院校/专业的数据。")


def main() -> int:
    payload = json.loads((HERE / "placeholder_result.json").read_text(encoding="utf-8"))
    result = payload.get("data") or payload
    for scope, name in (("all", "page_template.html"), ("micro", "page_template_micro.html")):
        html = render_result(result, scope, banner=BANNER)
        out = HERE / name
        out.write_text(html, encoding="utf-8")
        print(f"[ok] wrote {out}  ({len(html.encode('utf-8'))/1024:.0f} KB, scope={scope})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

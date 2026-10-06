"""把（单层级）报告渲染成自包含 HTML。

网页只呈现用户选择的层级：`render_result_html(result, scope)` 生成一个不依赖任何
外部资源的单文件 HTML；`scope="all"` 才呈现三视角。

实现方式：先由 `agent/scoped_report.py`（或 `agent/report.py`）产出受控子集的
Markdown，再用一个小而确定的转换器转 HTML，保证报告与网页内容完全一致。
"""

from __future__ import annotations

import html as html_mod
import re
from typing import Any, Mapping

from .report import render_markdown
from .scoped_report import render_scoped


def markdown_to_html(md: str) -> str:
    """Convert the controlled Markdown subset we emit into HTML."""
    lines = (md or "").split("\n")
    out: list[str] = []
    in_ul = False
    in_table = False

    def close_lists() -> None:
        nonlocal in_ul, in_table
        if in_ul:
            out.append("</ul>")
            in_ul = False
        if in_table:
            out.append("</tbody></table>")
            in_table = False

    def inline(text: str) -> str:
        escaped = html_mod.escape(text, quote=False)
        escaped = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", escaped)
        escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
        return escaped

    for raw in lines:
        line = raw.rstrip()
        if not line.strip():
            close_lists()
            continue
        if line.startswith("|"):
            cells = [c.strip() for c in line.strip("|").split("|")]
            if all(set(c) <= set("-: ") and c for c in cells):
                continue
            if not in_table:
                close_lists()
                out.append('<table class="tbl"><thead><tr>'
                           + "".join(f"<th>{inline(c)}</th>" for c in cells)
                           + "</tr></thead><tbody>")
                in_table = True
            else:
                out.append("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in cells) + "</tr>")
            continue
        close_lists()
        if line.startswith("### "):
            out.append(f"<h3>{inline(line[4:])}</h3>")
        elif line.startswith("## "):
            out.append(f"<h2>{inline(line[3:])}</h2>")
        elif line.startswith("# "):
            out.append(f"<h1>{inline(line[2:])}</h1>")
        elif line.startswith("> "):
            out.append(f'<blockquote>{inline(line[2:])}</blockquote>')
        elif line.startswith("- "):
            if not in_ul:
                out.append("<ul>")
                in_ul = True
            out.append(f"<li>{inline(line[2:])}</li>")
        elif line.startswith("---"):
            out.append("<hr>")
        else:
            out.append(f"<p>{inline(line)}</p>")
    close_lists()
    return "\n".join(out)


CSS = """
:root{--ink:#141414;--paper:#fbfaf6;--red:#d8342a;--clay:#c9a227;--dim:#6b665c;--rule:#e2ded2}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);
  font-family:"Source Han Serif SC","Noto Serif SC",Georgia,"Songti SC",serif;line-height:1.85}
.wrap{max-width:960px;margin:0 auto;padding:48px 28px 80px}
h1{font-size:30px;border-bottom:3px solid var(--ink);padding-bottom:14px}
h2{font-size:21px;margin-top:38px;border-left:5px solid var(--red);padding-left:12px}
h3{font-size:17px;margin-top:26px;color:#333}
p,li{font-size:15px}
blockquote{background:#f2efe6;border-left:4px solid var(--clay);margin:14px 0;padding:10px 16px;color:var(--dim)}
code{background:#efece2;padding:1px 5px;border-radius:3px;font-size:13px}
.tbl{width:100%;border-collapse:collapse;margin:14px 0;font-size:14px}
.tbl th,.tbl td{border:1px solid var(--rule);padding:7px 10px;text-align:left}
.tbl thead th{background:#f2efe6}
.badge{display:inline-block;background:var(--ink);color:var(--paper);font-size:12px;
  padding:2px 9px;border-radius:10px;margin-right:6px;letter-spacing:.08em}
.foot{margin-top:48px;border-top:1px solid var(--rule);padding-top:14px;color:var(--dim);font-size:12px}
"""


def render_result_html(
    result: Mapping[str, Any],
    scope: str = "all",
    *,
    title: str | None = None,
) -> str:
    """自包含单文件 HTML；只呈现 `scope` 指定的层级。"""
    if scope in ("macro", "meso", "micro"):
        body_md = render_scoped(result, scope)
        scope_label = scope
    else:
        body_md = render_markdown(dict(result), scope="all")
        scope_label = "all"
    heading = title or f"EduMatch · {scope_label}"
    body = markdown_to_html(body_md)
    return (
        "<!DOCTYPE html>\n<html lang=\"zh-CN\">\n<head>\n<meta charset=\"UTF-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\">\n"
        f"<title>{html_mod.escape(heading)}</title>\n"
        f"<style>{CSS}</style>\n</head>\n<body>\n<div class=\"wrap\">\n"
        f'<div><span class="badge">{html_mod.escape(scope_label)}</span></div>\n'
        f"{body}\n"
        f'<div class="foot">EduMatch · 单层级报告（scope={html_mod.escape(scope_label)}）'
        " · 数值由 analysis/ 确定性计算 · 缺失记 None 不记 0</div>\n"
        "</div>\n</body>\n</html>\n"
    )

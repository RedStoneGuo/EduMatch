"""Generate reference docs from code so they can never drift from the implementation.

    python scripts/gen_docs.py

Writes: docs/tsi_v2_spec.md, docs/core_tsi_spec.md, docs/mcp_tools.md, docs/skills.md
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from analysis import primary_tsi, tsi  # noqa: E402
from edumatch.tools import list_tools  # noqa: E402
from skills.registry import list_skills  # noqa: E402

DOCS = ROOT / "docs"

TSI_HEADER = """# TSI 2.0 规范

> 本文件由 `scripts/gen_docs.py` 从 `analysis/tsi.py` 生成，指标表与代码完全一致。
> 重新生成：`python scripts/gen_docs.py`

## 1. 设计原则

1. **LLM 不产生分数**：分数只由本文件的公式计算，LLM 只能解释；
2. **缺失不等于 0**：指标无证据时 `value=null`、`status=insufficient_evidence`、
   `evidence_level=E`，并从加权分母中剔除；
3. **维度覆盖率下限**：某维度可用指标权重覆盖率 < 0.34 时，整维剔除并在结果中披露；
4. **供需分离**：C 维（就业结果）只接受就业质量报告数据；D 维（市场需求）只接受招聘/产业数据；
5. **可解释**：每个指标都有 `formula`、`data_source`、`raw_field`、`method`、`direction`。

## 2. 维度与权重

| 维度 | 名称 | 权重 |
| --- | --- | --- |
"""

TSI_SECTION_SPEC = """
## 3. 指标明细（{} 项）

| 编号 | 指标 | 维度 | 维内权重 | 绝对权重 | 方向 | 方法 | 数据来源 | 原始字段 | 计算公式 | 缺失处理 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
"""

TSI_FOOTER = """
## 4. 计算方法

### 4.1 指标 → 维度

```
Dimension_d = Σ_{i∈available(d)} w_i · x_i / Σ_{i∈available(d)} w_i
coverage_d  = Σ_{i∈available(d)} w_i / Σ_{i∈d} w_i
confidence_d = (Σ_{i∈available} c_i·w_i / Σ w_i) × coverage_d
```

### 4.2 维度 → TSI

```
TSI = Σ_{d: coverage_d ≥ 0.34} W_d · Dimension_d / Σ_{d: coverage_d ≥ 0.34} W_d
```

覆盖率低于阈值的维度被**剔除**（不是记 0），并在 `excluded_dimensions` 中披露。

### 4.3 连续型映射

```
ratio = raw / benchmark
ratio ≥ 1：Score = 60 + (min(ratio,2.0) − 1.0) / 1.0 × 40      # 1×基准→60, 2×基准→100
ratio < 1：Score = 60 − (1.0 − max(ratio,0.5)) / 0.5 × 20       # 0.5×基准→40
```

### 4.4 分级型 / 语义型

- 分级型：查表（如 B3 每年 100 / 每 2 年 85 / 每 3 年 70 / 更久 50 / 无记录 → null）；
- 语义型：`S = lexical_alignment(text_a, text_b) × 100`，标注 `provider=lexical_bigram_jaccard_v1`
  与 D 级证据；可替换为 embedding / LLM 复核，但必须记录 provider 与置信度。

## 5. 分数带

| 区间 | 判定 |
| --- | --- |
| 85–100 | 高度适配 |
| 70–85 | 较适配 |
| 55–70 | 基本适配 |
| 40–55 | 适配不足 |
| 0–40 | 严重错配 |

## 6. 与旧版 TSI v1 的关系

| 项目 | 旧版 v1 | 新版 v2 |
| --- | --- | --- |
| 指标数 | 27（三三级） | 24（四维） |
| 维度 | 投入/过程/产出 | 培养基础/培养过程/培养结果/市场需求 |
| 缺失处理 | 记 0 分（占权重 39.29%） | 记 null 并从分母剔除 |
| 数值来源 | LLM 直接给分 | Python 纯函数计算 |
| 就业率来源 | 混用招聘岗位频率 | 仅就业质量报告 |
| 可复现性 | 复算 49.93，报告写 70.00 | 同一输入两次运行完全一致 |
"""


def write_tsi_spec() -> Path:
    lines = [TSI_HEADER]
    for dim, meta in tsi.DIMENSIONS.items():
        lines.append(f"| `{dim}` | {meta['name']} | {meta['weight']} |\n")
    lines.append(TSI_SECTION_SPEC.format(len(tsi.SPECS)))
    for spec in tsi.SPECS:
        abs_w = round(tsi.DIMENSIONS[spec.dimension]["weight"] * spec.weight, 4)
        lines.append(
            f"| {spec.id} | {spec.name} | {tsi.DIMENSIONS[spec.dimension]['name']} | {spec.weight} | "
            f"{abs_w} | {spec.direction} | {spec.method} | {spec.data_source} | `{spec.raw_field}` | "
            f"{spec.formula} | {spec.missing_policy} |\n"
        )
    lines.append(TSI_FOOTER)
    path = DOCS / "tsi_v2_spec.md"
    path.write_text("".join(lines), encoding="utf-8")
    return path


CORE_HEADER = """# Primary TSI 规范（Core TSI Engine）

> 本文件由 `scripts/gen_docs.py` 从 `analysis/primary_tsi.py` 生成，指标表与代码完全一致。
> 设计说明见 `docs/core_tsi_engine.md`。重新生成：`python scripts/gen_docs.py`

## 1. 定位

Primary TSI 是**唯一**对用户露出的正式主指标；TSI V1（27 三级指标）为
`historical_version`，TSI 2.0（四维 24 指标）为 `research_comparison` /
`benchmark_version`，只出现在报告 §16 与审计段落。

```
Primary TSI = 0.40·供需适配(F) + 0.20·培养基础(S) + 0.25·人才结果(O) + 0.15·需求背景(M)
Fit = Σ_s Demand(s)·min(Supply(s),1) / Σ_s Demand(s)      # analysis/fit.py，唯一实现
Gap(s) = Demand(s) − Supply(s)                            # 与 Fit 共用同一组向量
```

缺失指标记 `null` 并从加权分母剔除；维度覆盖率 < 0.34 时整维剔除并披露。

## 2. 指标明细

| 编号 | 指标 | 维度 | 维内权重 | 绝对权重 | 基础变量 | 变换 | 数据来源 | 计算公式 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
"""


def write_primary_spec() -> Path:
    lines = [CORE_HEADER]
    for spec in primary_tsi.SPECS:
        absolute = primary_tsi.DIMENSIONS[spec.dimension]["weight"] * spec.weight
        lines.append(
            f"| {spec.id} | {spec.name} | {spec.dimension} | {spec.weight} | {round(absolute, 4)} | "
            f"{', '.join(spec.primitives)} | `{spec.transform}` | {spec.data_source} | "
            f"{spec.formula} |\n"
        )
    lines.append("\n## 3. 维度权重\n\n| 维度 | 名称 | 权重 |\n| --- | --- | --- |\n")
    for dim, meta in primary_tsi.DIMENSIONS.items():
        lines.append(f"| `{dim}` | {meta['name']} | {meta['weight']} |\n")
    report = primary_tsi.dependency_graph().double_counting_report()
    lines.append(
        "\n## 4. 指标依赖图审计\n\n"
        f"- 指标节点：{report['n_nodes']}\n"
        f"- double counting 分组：{report['n_duplicate_groups']}（clean={report['clean']}）\n"
        f"- 规则：{report['note']}\n"
        "\n上游指标的完整依赖图见 `result['metric_graph']['primary']`；"
        "TSI 2.0 的重复输入审计见 `result['metric_graph']['v2_audit']`。\n"
    )
    path = DOCS / "core_tsi_spec.md"
    path.write_text("".join(lines), encoding="utf-8")
    return path


def write_mcp_docs() -> Path:
    tools = list_tools()
    groups: dict[str, list[dict]] = {}
    for tool in tools:
        groups.setdefault(tool["group"], []).append(tool)
    lines = [
        "# MCP 工具说明\n\n",
        f"> 由 `scripts/gen_docs.py` 从 `edumatch/tools/registry.py` 生成，共 {len(tools)} 个工具、"
        f"{len(groups)} 个分组。\n\n",
        "## 1. 启动方式\n\n",
        "```powershell\n",
        "python -m mcp_servers.server --all            # 暴露全部工具\n",
        "python -m mcp_servers.server --group education # 仅教育组\n",
        "python -m mcp_servers.server --selftest        # 离线协议自检\n",
        "```\n\n",
        "传输：stdio，换行分隔的 JSON-RPC 2.0；实现 `initialize` / `tools/list` / `tools/call` / `ping`。\n",
        "不依赖任何第三方 MCP SDK，可在无网络环境运行。\n\n",
    ]
    for group, items in groups.items():
        lines.append(f"## {group} 组（{len(items)}）\n\n")
        lines.append("| 工具 | 说明 | 参数 | 返回 |\n| --- | --- | --- | --- |\n")
        for tool in items:
            props = tool["inputSchema"].get("properties") or {}
            params = ", ".join(f"`{k}`" for k in props) or "—"
            lines.append(f"| `{tool['name']}` | {tool['description']} | {params} | {tool.get('returns') or '—'} |\n")
        lines.append("\n")
    lines.append(
        "## 合规声明（recruitment 组）\n\n"
        "- `crawl_jobs` 默认关闭，需显式设置 `EDUMATCH_ENABLE_CRAWLER=1`；\n"
        "- 抓取前必须通过 `robots.txt` 检查，违反即拒绝；\n"
        "- 请求间隔默认 3 秒，结果缓存到 `data/raw/cache`；\n"
        "- 禁止登录抓取、验证码绕过、反爬绕过、访问非公开数据；\n"
        "- 每条岗位保留 `source / url / crawl_time`。\n"
    )
    path = DOCS / "mcp_tools.md"
    path.write_text("".join(lines), encoding="utf-8")
    return path


def write_skills_docs() -> Path:
    skills = list_skills()
    lines = [
        "# Skills 说明\n\n",
        f"> 由 `scripts/gen_docs.py` 生成，共 {len(skills)} 个 Skill。\n\n",
        "Skill 只承载**流程与约束**，不承载业务计算；计算全部在 `analysis/`，数据访问全部在 MCP 工具。\n\n",
        "| Skill | 名称 | 文档 | 驱动工具 | 主要产出 |\n| --- | --- | --- | --- | --- |\n",
    ]
    for skill in skills:
        lines.append(
            f"| `{skill['skill_id']}` | {skill['name']} | [{skill['path']}](../{skill['path']}) | "
            f"{', '.join('`' + t + '`' for t in skill['tools'])} | {', '.join(skill['outputs'])} |\n"
        )
    lines.append(
        "\n## 执行方式\n\n"
        "```python\n"
        "from skills import list_skills        # 列出全部 Skill 及其工具绑定\n"
        "from agent.core import TalentSupplyDemandAgent\n"
        "agent = TalentSupplyDemandAgent()\n"
        "result = agent.research('分析人工智能专业与北京AI招聘市场的供需适配')\n"
        "```\n\n"
        "Agent 的 `plan.steps` 会把研究任务映射到上述 Skill 序列，并在 `result['skill_calls']` 中记录实际调用。\n"
    )
    path = DOCS / "skills.md"
    path.write_text("".join(lines), encoding="utf-8")
    return path


def main() -> int:
    DOCS.mkdir(parents=True, exist_ok=True)
    for path in (write_tsi_spec(), write_primary_spec(), write_mcp_docs(), write_skills_docs()):
        print(f"[ok] {path.relative_to(ROOT)} ({path.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

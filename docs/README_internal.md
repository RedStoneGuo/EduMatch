# EduMatch｜北京高等教育人才供需适配核心引擎（可迁移包）

> **定义与称呼**：EduMatch 是一个**可被 Agent 调用的确定性「教育—就业供需适配分析引擎」**
> （Agent-callable analysis engine / 工具系统）。**Agent 是主体**，负责问询、判断、读原文与写结论；
> 本引擎只提供确定性能力。`analyze.ps1` 与 `scripts\*.py` 是它的**调用接口（Toolchain）**；
> `analysis/` 是计算引擎、`edumatch/`+`data/` 是知识数据层、`reporting/` 是交付渲染层、
> `mcp_servers/` 是对外 MCP 服务；**只有 `vendor/edu-material-harvest/` 叫"插件"**（联网采集）。
> 详见 [AGENTS.md](AGENTS.md) §0.0。

从 `EduMatch/edumatch_agent` 提取运行与分析必需的全部代码与数据，并**连同全部原始一手材料**
（PDF / Word / Excel / TXT，除图片·视频·PPT）一起打包；所有路径均为相对路径，
复制到任意电脑/盘符即可运行。

> **接手请先读 [交接文档.md](交接文档.md)**（成果、方法、数据、验证、下一阶段对接、检查单）。
> **要在新对话窗口里直接开工**：把 [PROMPT.md](PROMPT.md) 的启动提示词整段发给 Agent，
> 它会加载 [skills/00_agent_entry/SKILL.md](skills/00_agent_entry/SKILL.md) 并按规范完成分析。
> 下一阶段需求见 [docs/下一阶段_TSI多尺度多角色应用层.md](docs/下一阶段_TSI多尺度多角色应用层.md)；
> 数据资产清单见 [data/source/README.md](data/source/README.md)；
> 数据来源（本地 / 插件联网 / 双重模式）见 [docs/data_sources.md](docs/data_sources.md)。

## 包体概况

- 规模：**5,571 个文件 / 4,716 MB**（代码约 2 MB + 数据 4,687 MB + 归档最小运行副本 26 MB + 插件 vendor 1 MB）
- 数据：课程库 28,166 条（13,415 门去重课程）/ 教育事实 6,594 条（含 305 个专业）/ 政策 145 份
  / 岗位 **35,145 条**（AI·计算机目标语料 16,161 + 68 个专业的专业作用域语料 18,931）/ 可检索正文 1,779 份 / 文献 59 篇
- 覆盖：**任意专业**（专业目录 360 个、216 个专业方案、13 所院校）+ 10 个目标岗位族 + **全国 2,952 所高校的同类校判定**
- 数据来源：`local`（本地）/ `plugin`（插件联网采）/ `hybrid`（合并），同类校可跨省取用

## 快速开始（Windows / PowerShell）

```powershell
cd EduMatch

# 0) 环境：Python 3.12 + pandas/numpy/scikit-learn/pytest/pyyaml/pypdf/streamlit
python -m pytest tests -q                       # 期望 128 passed / 3 skipped（含升级层 11 项）

# 0b) 多尺度升级层与自动质量门（新增）
python scripts\validate_edumatch.py             # 期望 0 error（数值/TSI唯一/缺失/语义/证据链）
python -m pytest tests\test_upgrade_core.py -q  # 升级层单测

# 升级层文档：docs/PROFILE_SCHEMA.md · SYSTEM_ARCHITECTURE.md · TSI_MIGRATION.md ·
#              SUPPLY_DEMAND_FRAMEWORK.md · EVIDENCE_FRAMEWORK.md · SCENARIO_FRAMEWORK.md
# 审计与迁移计划：项目根目录 audit/ 与 UPGRADE_SUMMARY.md

# 1) 核心用法：院校 + 专业 + 目标岗位 → 岗位匹配度
python -m agent.runner --list-occupations
python -m agent.runner --query "分析北京工业大学人工智能专业与大模型算法工程师岗位的匹配度" `
  --occupation "大模型算法工程师" --simulate --template

# 2) 批量（把报告与 result.json 落到 data/processed/case_reports/）
python scripts\batch_school_analysis.py --major 人工智能 --schools 北京工业大学 --occupation "大模型算法工程师"

# 2b) 任意专业（非三族）同样可用
python scripts\batch_school_analysis.py --major 机械工程 --schools 北京工业大学

# 3) MCP 服务 / 离线页
python -m mcp_servers.server --selftest
python demo\export_static.py
```

## 数据来源：本地 / 插件联网 / 双重模式

教育供给端数据支持三种来源，用 `--source-mode` 切换（详见 [docs/data_sources.md](docs/data_sources.md)）：

```powershell
# local（默认）：只用 data/source 与本地结构化库，离线可复现
python -m agent.runner --query "分析北京工业大学人工智能专业与大模型算法工程师岗位的匹配度" `
  --occupation "大模型算法工程师"

# plugin：目标院校/专业的数据完全来自 edu-material-harvest 插件，不依赖本地库
python -m agent.runner --query "…同上…" --occupation "大模型算法工程师" `
  --source-mode plugin --harvest

# hybrid：本地全量 + 插件新采，合并去重后综合分析
python -m agent.runner --query "…同上…" --occupation "大模型算法工程师" `
  --source-mode hybrid --harvest

# 大站/子域被 WAF 挡住时：先用联网搜索定位承载页，再直采（插件文档的入口 B）
python -m agent.runner --query "…" --source-mode hybrid --harvest --domain bjut.edu.cn `
  --harvest-page "https://undergrad.bjut.edu.cn/content.jsp?…&wbnewsid=3270" --harvest-kind 培养方案

# 数据侧：重组本地目录 / 清洗并建索引 / 生成已核实域名台账 / 审计利用率
python scripts\normalize_source_layout.py --check
python scripts\build_source_index.py
python scripts\build_harvest_domains.py
python scripts\audit_data_coverage.py

# 4) 同类院校（peer benchmark）：全国口径检索 + 预取
python scripts\harvest_peers.py --school 北京工业大学 --major 人工智能 --max-peers 4 --list
python scripts\harvest_peers.py --school 北京工业大学 --peers 北京邮电大学,北京航空航天大学
python scripts\resolve_school_domains.py --list peers --school 华中科技大学   # 列出待补域名
python scripts\resolve_school_domains.py --school 武汉大学 --domain whu.edu.cn  # 实测核实后入台账

# 5) 需求侧扩容：并入按专业导出的岗位表（68 个专业 / 55,620 行）
python scripts\import_job_exports.py --dry-run
python scripts\import_job_exports.py

# 离线回放插件产物（不需要网络、不需要插件在跑）
python scripts\build_harvest_replay.py
python -m pytest tests\test_supply_source.py -q
```

插件仓库随包在 `vendor/edu-material-harvest/`；`HarvestClient` 通过它自带的零依赖
stdio MCP 服务端（12 个工具）采集，产出落到 `data/harvest/<院校>/`，原始件同步进
`data/source/<数据类型>/<院校>/`。

## 目录结构

```
EduMatch/
├── agent/            主 Agent：规划 / 编排 / 报告渲染 / CLI
├── analysis/         纯函数计算层（供给·需求·匹配·缺口·岗位匹配·TSI·机制·趋势·模拟）
├── edumatch/         数据与知识层（dataset / engine / occupation / 抽取 / 工具）
├── mcp_servers/      stdio JSON-RPC MCP 服务（42 工具 / 6 分组）
├── skills/           10 个 Skill（00 总入口 / 01–08 分项 / 09 数据源与同类校）
├── vendor/           edu-material-harvest 插件（联网采集，MCP 12 工具）
├── PROMPT.md         新对话窗口的启动提示词（复制即用）
├── ontology/         技能本体（40 实体 + 层级传播）
├── config/config.yaml 全部路径为相对路径；含专业族注册表与模型参数
├── data/
│   ├── raw/          运行输入：培养方案课程库、模板课程、招聘聚合证据、归档正文
│   ├── processed/    结构化数据：事实库、岗位库、文献、运行产物
│   ├── source/       原始一手材料（Excel / 培养方案 PDF / 归档全文缓存 / 文献缓存）
│   └── db/           SQLite 运行台账
├── reference/archive/ 归档最小运行副本（政策 145 份 + 旧版过程记录）
├── evaluation/       12 案例 + 10 指标 + 阈值
├── demo/             Streamlit 界面 + 离线 HTML 导出
├── scripts/          导入 / 路径归一化 / 批量分析 / 文档生成 / 评测
└── tests/            94 项单元测试
```

## 迁移到其它电脑

1. 整个 `EduMatch` 目录复制过去即可（无绝对路径依赖）；
2. 数据文件里的来源路径已是相对写法（包内 `data/source/...` 或 `../AI竞赛数据归档/...`）；
3. 若换了盘符或目录名，用 `python scripts\relativize_paths.py --check` 复核一遍；
4. **原始归档材料已随包**：`data/source/` 现有 2,510 个文件 / 约 4.13 GB，整包拷走即可离线跑全流程。

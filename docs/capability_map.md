# EduMatch 能力清单与调用方法（当前版本）

> 本文件回答三件事：**能做哪些分析、怎么调用、哪些输入组合目前能出真结论**。
> 所有数字来自当前数据集实测；模型规范见 `docs/core_tsi_engine.md`。

## 1. 一句话结论：能否"任意院校 + 专业 + 目标岗位"

- **接口上可以**：任意校名（含数据集之外的学校）、任意岗位文本、任意专业都可提交；
- **数据上不是任意组合都能出匹配度**：只有"该院校在该专业族**同时具备可核查课程供给**"
  时才会输出岗位匹配度；否则按既定原则返回 `insufficient_evidence` 与补数步骤，
  **不会用其他院校/其他专业族/不覆盖的招聘语料顶替**；
- 未知专业（如机械工程、临床医学）直接拒绝作答并说明如何补数据。

### 1.1 输入契约

| 输入 | 必填 | 解析方式 | 缺数据时的行为 |
| --- | --- | --- | --- |
| 院校 | 否 | 数据集内校名精确匹配 → 简称（北大/清华/北工大/北交大/北邮）→ 任意"XX大学/XX学院"正则 | 校名被识别但无数据 → 该校供给记 `insufficient_evidence`，不给区域口径结论 |
| 专业 | 是 | 别名表 `FAMILY_ALIASES` → 专业族 ai/cs/econ；族注册表来自 `config.yaml::families`（可加族），`data/raw/majors_<族>.txt` 仅作可选校核金标准 | 归档无该专业族 → 拒绝作答（`X_unknown_major`）并给出补数步骤 |
| 目标岗位 | 否 | `edumatch/occupation.py` 的 10 个岗位族（关键词/标准名）；未指定但问题含"岗位/匹配度"时 ai 族默认"人工智能相关岗位（全部）" | 解析不到或该族岗位 < 30 条 → 匹配度记 `insufficient_evidence` |

一次分析一个院校 + 一个专业 + 一个岗位；多校对比用 `batch_school_analysis.py` 或分多次运行。

### 1.2 当前数据覆盖矩阵（决定哪些组合能出真结论）

| 专业族 | 教育事实 | 有事实的院校 | 可核查课程 | 有课程的院校 | 岗位语料覆盖 | 能出的结论 |
| --- | --- | --- | --- | --- | --- | --- |
| `ai` 人工智能 | 16 条 | 2 | 20 门（+18 门 E 级模板） | 11（北理工3、北师大3、北交大3、北林2、中国农大2、北体2、人大1、中央财大1、北工大1、北邮1、北航1） | 56.7% | **岗位匹配度 + Skill Fit + Gap + Primary TSI**（就业结果维度常缺） |
| `cs` 计算机 | 393 条 | 8（北交大160、中国地质70、华北电力48、北工大37…） | 3 门 | 3（北师大1、中国农大1、北体1） | 87.7% | 就业结果/趋势/机制可用；**供需适配与岗位匹配基本不可用（缺课程）** |
| `econ` 经济管理 | 837 条 | 15（北交大232、中央财大124、中国矿业99…） | 0 门 | 0 | 11.0%（低于 30% 阈值） | 仅就业侧画像；**供需适配、岗位匹配一律证据不足** |

补充：27 所院校有**校级口径**事实（北工大 309、中央音乐学院 242、中国政法 238…），
可在"同校"范围内兜底并被显式标注 `scope=school_level`。

### 1.3 目标岗位族与样本量

| 岗位族 | id | 语料岗位数 |
| --- | --- | --- |
| 大模型算法工程师 | `llm_algorithm` | 611 |
| 计算机视觉算法工程师 | `cv_algorithm` | 241 |
| 自然语言处理 / 语音算法工程师 | `nlp_voice` | 671 |
| 机器学习 / 深度学习算法工程师 | `ml_algorithm` | 2,521 |
| 大数据 / 数据工程 | `data_engineering` | 828 |
| 数据分析 / 数据挖掘 | `data_analysis` | 381 |
| AI 应用 / 工程化开发 | `ai_application` | 1,636 |
| MLOps / 平台与运维 | `mlops_platform` | 347 |
| AI 产品 / 解决方案 | `ai_product` | 1,733 |
| 人工智能相关岗位（全部） | `ai_all` | 16,161 |

岗位语料主轴为"人工智能"（各专业族关键词覆盖率 ai 56.7% / cs 87.7% / econ 11.0%），
因此面向 econ 族的需求会被判为不覆盖并返回证据不足。

## 2. 目录结构

```
EduMatch/                          # 工作区根目录（归档只读）
├─ AI竞赛数据归档/                  # 只读：795 份历史资料（教学质量/就业质量/政策/输出过程记录）
├─ 招聘数据/                        # 只读：HAR 原始抓包（自动发现，不硬编码路径）
└─ edumatch_agent/                 # 全部新代码（本目录）
   ├─ agent/                       # 主 Agent：planner / core / llm 解释层 / report 渲染 / runner CLI
   ├─ analysis/                    # 纯函数计算层（无 LLM、无网络）
   │   ├─ supply.py  demand.py fit.py skill_gap.py      # 统一主线：供给→需求→Fit→Gap
   │   ├─ primary_tsi.py  metric_graph.py               # 正式主指标 + 指标依赖/重复加权审计
   │   ├─ occupation_match.py                           # 目标岗位匹配（院校专业 × 岗位）
   │   ├─ tsi.py  tsi_v1.py                             # 历史版本（2.0 研究对照 / V1 历史）
   │   ├─ benchmark.py  mechanism.py  trend.py  simulation.py
   │   ├─ semantic.py  semantic_evidence.py  embeddings.py  confidence.py
   │   └─ matching.py                                   # 兼容包装（对外接口保持不变）
   ├─ edumatch/                    # 数据与知识层
   │   ├─ dataset.py  engine.py  evidence.py  config.py  db.py  ontology.py
   │   ├─ occupation.py                                 # 目标岗位族定义与切片
   │   ├─ ingest/  (pdf_reader, pdf_facts, pdf_major_tables, courses, education_facts, policy, legacy, docx_reader)
   │   ├─ jobs/    (har_import, normalize, dedup, demand, crawler, permitted_crawler, adapters/zhaopin)
   │   ├─ sources/education_web.py  literature.py  tools/(registry, education, recruitment, policy, analysis_tools, evidence_tools, literature_tools)
   ├─ mcp_servers/server.py         # stdio JSON-RPC MCP 服务（42 工具 / 6 分组）
   ├─ skills/                       # 10 个 Skill（00 总入口 + 01–08 分项 + 09 数据源与同类校）
   ├─ vendor/                       # edu-material-harvest 插件（联网采集，MCP 12 工具）
   ├─ ontology/skill_ontology.yaml  # 技能本体（含层级传播）
   ├─ data/
   │   ├─ raw/                      # 模板课程、HAR、PDF 文本缓存、策展文档
   │   └─ processed/                # 事实库、岗位库、运行产物、案例报告、对照结果
   ├─ demo/app.py  demo/export_static.py  demo/output/index.html
   ├─ evaluation/                   # 12 案例、10 指标、阈值、评测报告
   ├─ docs/                         # 本文件与全部规范/审计文档
   ├─ scripts/                      # 30 个可执行脚本（见第 4 节）
   ├─ tests/                        # 92 passed / 3 skipped
   ├─ run.ps1                       # 一键：test / build / run / eval / demo
   └─ README.md  AGENTS.md  requirements.txt  .env.example
```

## 3. 功能清单（按层）

### 3.1 数据层

| 功能 | 实现 |
| --- | --- |
| 归档 PDF → 文本 → A 级事实（带页码/来源） | `edumatch/ingest/pdf_reader.py`、`pdf_facts.py`、`scripts/extract_archive_pdfs.py` |
| 就业报告分专业行抽取 | `pdf_major_tables.py`、`scripts/extract_pdf_major_rows.py` |
| 培养方案课程抽取（含学分/实践标记） | `ingest/courses.py` |
| 政策文件入库 + 去重 + 产业方向/技能关联 | `ingest/policy.py` |
| 招聘 HAR 导入 → 去重 → 技能抽取 | `jobs/har_import.py`、`dedup.py`、`normalize.py` |
| 招聘 Excel 导入 | `scripts/import_job_excel.py` |
| 合规抓取（robots/黑名单/凭据拦截） | `jobs/crawler.py`、`permitted_crawler.py` |
| 文献自动检索（OpenAlex） | `literature.py`、`scripts/fetch_literature.py` |
| SQLite 落库与运行台账 | `db.py`、`scripts/build_database.py` |

### 3.2 模型层（`analysis/`，全部确定性、可复现）

| 功能 | 模块 |
| --- | --- |
| 连续型 Skill Supply（覆盖/学分/必修选修/深度/实践/培养目标六通道） | `supply.py` |
| 岗位需求向量（频率/岗位覆盖/岗位族覆盖/薪资溢价/政策相关/产业权重/趋势/稳定性） | `demand.py` |
| Skill Fit（唯一实现）+ Fit/Gap 闭合校验 | `fit.py` |
| Skill Gap（含 `absent_in_scope` 缺口语义） | `skill_gap.py` |
| **目标岗位匹配度**（岗位族切片 → 岗位需求 → 匹配度/匹配带/定义性技能缺口） | `occupation_match.py` |
| Primary TSI（四维 16 指标，去重，定义性维度不可用则不予计算） | `primary_tsi.py` |
| 指标依赖图与 double counting 审计 | `metric_graph.py` |
| 技能级 Benchmark + 目标校/同类基准/市场三角比较 | `benchmark.py` |
| 政策—产业—岗位—技能—课程 关联路径（非因果） | `mechanism.py` |
| 趋势（同年去重、≥2 个不同年份才出结论）+ 市场-培养响应分析 | `trend.py` |
| 培养方案 what-if 模拟（ΔFit / ΔGap / ΔPrimary TSI） | `simulation.py` |
| 语义证据（TF-IDF 余弦 + 可选句向量锚点） | `semantic.py`、`semantic_evidence.py`、`embeddings.py` |
| 历史版本：TSI 2.0（24 指标）/ TSI V1（27 指标） | `tsi.py`、`tsi_v1.py` |

### 3.3 Agent 与报告层

| 功能 | 实现 |
| --- | --- |
| 规则化任务规划（模式 A–H + 未知专业 X） | `engine.build_plan`、`agent/planner.py` |
| 确定型研究流水线（工具调用全记录） | `engine.ResearchEngine.run` |
| 三层报告：Executive（发现）/ Research（画像与矩阵）/ Audit（run_id/证据/公式/依赖图） | `agent/report.py` |
| 可选 LLM 解释层（不产生任何数值） | `agent/llm.py` |
| 运行落盘 `runs/<run_id>/{report.md,result.json,plan.json,evidence.json}` | `agent/core.py::save` |

### 3.4 接口层

| 接口 | 说明 |
| --- | --- |
| CLI | `python -m agent.runner`（`--occupation` / `--simulate` / `--template` / `--json` / `--save-run` / `--list-occupations`） |
| Python API | `TalentSupplyDemandAgent.research(...)`、`ResearchEngine.run(...)` |
| MCP | `python -m mcp_servers.server`（42 工具 / 6 分组，含 `supply_source`；stdio JSON-RPC，无第三方 SDK 依赖） |
| Skill | 10 个 Skill 定义研究流程与工具绑定（`skills/*/SKILL.md`）；入口见 `skills/00_agent_entry/SKILL.md` |
| 数据来源 | 三种模式 `local / plugin / hybrid`；同类校按全国名单判定，见 `docs/data_sources.md` |
| Streamlit | `streamlit run demo/app.py`（交互界面） |
| 离线页 | `python demo/export_static.py` → `demo/output/index.html` |

## 4. 调用方法（按场景）

```powershell
cd EduMatch        # 或本包所在目录

# 0) 环境自检
python -m pytest tests -q                       # 92 passed / 3 skipped
python scripts\run_evaluation.py                # 12/12 案例 + 10 项指标

# 1) 目标岗位匹配（模型主用法：院校 + 专业 + 目标岗位）
python -m agent.runner --list-occupations
python -m agent.runner --query "分析北京工业大学人工智能专业与大模型算法工程师岗位的匹配度" `
  --occupation "大模型算法工程师" --simulate --template
python scripts\batch_school_analysis.py --major 人工智能 --schools 北京工业大学 --occupation "大模型算法工程师"

# 2) 一般供需适配（不指定岗位，按专业族/区域口径）
python -m agent.runner --query "分析北京市重点高校人工智能专业与 2025 年 AI 招聘市场的人才供需适配情况，并找出最关键的技能缺口。" --simulate --template
python scripts\batch_school_analysis.py --major 软件工程 --schools 北京理工大学 北京航空航天大学

# 3) 把完整结果写成 JSON / 落库
python -m agent.runner --query "..." --json out.json --save-run

# 4) 数据侧
python scripts\archive_inventory_report.py      # 归档盘点
python scripts\build_database.py                # 建库
python scripts\import_har_jobs.py               # 导入 HAR 岗位
python scripts\import_job_excel.py --help       # 导入 Excel 岗位
python scripts\fetch_literature.py --limit 20   # 文献检索
python scripts\extract_archive_pdfs.py          # PDF → 文本 → A 级事实

# 5) 质量与审计
python scripts\core_model_upgrade_report.py     # 改造前后对照
python scripts\traceability_report.py           # 指标→依据→证据→来源
python scripts\validate_extraction.py           # 抽取校验
python scripts\gen_docs.py                      # 从代码生成规范文档

# 6) 服务与演示
python -m mcp_servers.server --selftest
python -m mcp_servers.server --all
streamlit run demo\app.py
python demo\export_static.py

# 7) 一键流水线
python scripts\auto_pipeline.py --once
python scripts\auto_pipeline.py --watch --interval 60
powershell -File .\run.ps1 all
```

Python API 示例：

```python
from agent.core import TalentSupplyDemandAgent

agent = TalentSupplyDemandAgent()
result = agent.research(
    "分析北京工业大学人工智能专业与大模型算法工程师岗位的匹配度",
    include_template=True, simulate=True, target_occupation="大模型算法工程师",
)
print(result.report)                       # Markdown 报告
print(result.data["occupation_match"])     # 岗位匹配度、匹配带、逐技能明细
print(result.data["primary_tsi"]["primary_tsi"], result.data["data_quality"]["reliability"])
agent.save(result)                         # data/processed/runs/<run_id>/
```

## 5. 结果落盘位置

| 产物 | 路径 |
| --- | --- |
| 单次运行 | `data/processed/runs/<run_id>/{report.md,result.json,plan.json,evidence.json}` |
| 指定院校专业（可带目标岗位） | `data/processed/case_reports/<学校>_<专业>[_<目标岗位>]/{report.md,result.json}` + `_comparison_<专业>.{json,md}` |
| Core Model 前后对照 | `data/processed/core_model_upgrade/{comparison.json,comparison.md}` + 每案例目录 |
| 离线演示页 | `demo/output/index.html` |
| 评测报告 | `evaluation/reports/evaluation_report.{json,md}` |
| 运行台账 | `data/db/edumatch.sqlite` |

## 6. 扩展到"任意输入"的路径

| 缺口 | 补什么 | 补完怎么跑 |
| --- | --- | --- |
| 院校无课程（本地补） | 该校培养方案 PDF（放到 `data/source/培养方案/<学校>/`） | `python scripts\import_supplementary.py --all` → `python scripts\build_source_index.py` |
| 院校无课程（联网补） | 无需预置文件：给官方域名即可（域名取自 `data/harvest/domains.json` 或显式传入，插件绝不猜） | `python -m agent.runner --source-mode hybrid --harvest --domain <校>.edu.cn` → 插件联网采集 → 自动入库解析 |
| 院校无课程（手工补录） | 课程名/学分/必修选修/实践学时 | 追加到 `data/raw/majors_<族>.txt` |
| 院校无就业数据 | 该校就业质量报告 PDF | `python scripts\extract_archive_pdfs.py` → `python scripts\reextract_pdf_facts.py` |
| 新专业族 | 新建 `data/raw/majors_<族名>.txt` | 无需改代码，重跑即可（`available_families` 自动发现） |
| 岗位语料不覆盖某族 | 按该族关键词导出 HAR | 放入 `data/raw/har/` → `python scripts\import_har_jobs.py` |
| 新目标岗位族 | 在 `edumatch/occupation.py` 增加 `OccupationFamily`（关键词 + 定义性技能） | 重跑，`--list-occupations` 即可见 |
| 多期趋势 | 按季度重复导出同类 HAR | 重新导入后趋势模块自动启用 |

## 7. 硬约束（不会因扩展而改变）

- 缺失一律 `null` + `insufficient_evidence`，不记 0、不编造、不用其他院校/专业族/语料顶替；
- 数值只来自 `analysis/` 纯函数，LLM 只做解释；
- 就业结果只取自就业质量报告，招聘数据只用于需求侧；
- 每个结论都有 `evidence_id → locator → quote → level → confidence` 证据链；
- 同一输入两次运行结果完全一致（`run_id` + 可复现命令）。

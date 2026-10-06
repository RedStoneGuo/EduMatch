# EduMatch 交接文档（阶段性交付 · 2026-10-05）

## 0. 定义与称呼（先统一术语）

**EduMatch = 一个可被 Agent 调用的确定性「教育—就业供需适配分析引擎」。**
它不是 Agent、不是插件、也不只是一个 MCP 服务；它是一个**被主体调用的工具系统**。

| 称呼 | 指什么 | 角色 |
| --- | --- | --- |
| Agent（主体） | Codex / 大模型 + `AGENTS.md` + `skills/` | 唯一决策者：问询、判断、读原文、写结论 |
| **EduMatch Engine（本系统）** | 本文件夹整体 | Agent 调用的确定性分析引擎 |
| Toolchain / CLI（工具链） | `analyze.ps1`、`scripts\*.py` | 引擎的**调用接口**，把多步流程封成一条命令 |
| Core TSI Engine（计算引擎） | `analysis/` | 纯函数计算：Supply/Demand/Fit/Gap/TSI/Simulation |
| Knowledge Base（知识/数据层） | `edumatch/` + `data/` | 数据集、技能本体、证据链、采集清洗 |
| Renderer（交付渲染层） | `reporting/` | 报告与 HTML 的唯一版式来源 |
| Skills（技能包） | `skills/` | 给 Agent 的作业指导书 |
| MCP Server（MCP 服务） | `mcp_servers/` | 把引擎工具暴露给外部调用方 |
| Plugin（插件） | `vendor/edu-material-harvest/` | **只有它叫插件**：联网采集插件（12 个 MCP 工具） |

> `.ps1` / `scripts/*.py` 不替 Agent 做判断：它们是 Agent 驱动引擎的**接口与走查清单**，
> 保证"补采 → 计算 → 渲染 → 质量门"按规范顺序、可复现地执行。

> **接手请先读 [AGENTS.md](AGENTS.md) §0**（新对话窗口会自动读取它，无需再粘贴提示词）。
> 一句话上手：
>
> ```powershell
> cd <本包目录>          # 例如 D:\Codex_project\EduMatch\EduMatch，或整包拷贝后的路径
> .\analyze.ps1 "分析北京工业大学信息管理与信息系统专业与数据分析师岗位的匹配度" `
>     -Occupation "数据分析师" -MicroFile "<个人画像.txt，可选>" -Scope all
> ```
>
> 系统会自动完成：**插件补采 → 引擎分析 → 分层报告（Markdown + HTML）→ 质量门**。

---

## 1. 系统是什么

**面向政府、高校专业负责人和学生的多尺度「高等教育—就业市场」供需适配分析与决策支持系统。**

它回答的问题链是：

```
高校培养了什么 → 市场真正需要什么 → 二者在哪里匹配 → 哪里出现 Knowledge/Skill/
Capability/Practice Gap → Gap 是结构性的、阶段性的还是实践性的 → 不同干预可能带来什么变化
→ 政府 / 高校 / 学生分别该做什么
```

模型主线（唯一正式总分）：

```
Primary TSI = 0.40·F_供需适配 + 0.20·S_培养基础 + 0.25·O_人才结果 + 0.15·M_需求背景
Fit = Σ_s Demand(s)·min(Supply(s),1) / Σ_s Demand(s)；Gap(s) = Demand(s) − Supply(s)
```

`Match / Skill Fit` 是子指标；缺失一律记 `None`（不记 0），并在覆盖率/置信度里披露。

## 2. 一条命令怎么跑（唯一推荐入口）

| 方式 | 命令 |
| --- | --- |
| PowerShell | `.\analyze.ps1 "<自然语言问题>" [-Occupation 岗位] [-MicroFile 画像.txt] [-Scope all\|macro\|meso\|micro] [-OfferUrl "校名=URL"] [-PeerMax 3] [-Offline]` |
| Python | `python scripts\analyze.py --query "<问题>" [--occupation …] [--micro-file …] [--scope …] [--domain-candidate "校名=URL"] [--auto-harvest/--no-auto-harvest] [--offline]` |

产出默认落在 `..\分析产物\<院校>_<专业>_<岗位>\`：

```
报告_all.html   三视角完整版（唯一正式总分 + TSI Tree + 检索台账 + 来源交叉引用）
报告_macro.html / 报告_meso.html / 报告_micro.html   分层版（补做只新增，不覆盖）
报告_*.md       与 HTML 同源的 Markdown 版本
result.json     引擎结构化结果（含 retrieval_ledger / auto_harvest / conflict_resolution）
```

## 3. 目录与模块地图

```
EduMatch/
├── AGENTS.md            ← §0 自动执行指引；§3–§10 硬约束与坑位
├── PROMPT.md            ← 短版启动提示词（正常情况无需复制）
├── 交接文档.md          ← 本文件（阶段性交付）
├── analyze.ps1          ← 一条命令入口（PowerShell）
├── agent/               planner / core / llm(解释层) / report(18 节) / findings / scope / scoped_report / html_report / runner
├── reporting/           ★ 报告交付层：theme.py(CSS/JS) + components.py(构件) + render.py(任意院校专业入口) + templates/(零数据模板)
├── analysis/            确定性计算：supply / demand / fit / matching / skill_gap / occupation_match /
│                        primary_tsi / tsi(v2) / tsi_v1 / mechanism / trend / simulation /
│                        objective_alignment(S1) / capability / micro / evaluation / conflict_resolution /
│                        tsi_tree / scenario / decision_support / metric_graph / semantic*
├── edumatch/            数据与知识层：dataset / engine / occupation / ontology / evidence / profiles /
│                        personal_extract / vocab / major_demand / retrieval_sweep / pdf_text /
│                        domain_discovery / auto_harvest / coverage_state / coverage_pipeline /
│                        peers / sources / harvest / jobs / ingest
├── skills/              00 入口 / 01–09 分项 / 10 分层交付 / 11 全面检索
├── scripts/             analyze(新入口) / auto_harvest / discover_school_domain / validate_edumatch /
│                        audit_course_coverage / audit_university_coverage / import_supplementary /
│                        batch_school_analysis / harvest_peers / resolve_school_domains / …
├── data/                raw(运行输入) / processed(结构化) / source(一手材料) / harvest(采集产物) / db
├── demo/ evaluation/ mcp_servers/ ontology/ reference/ tests/ vendor/
└── docs/                TSI_MIGRATION / SYSTEM_ARCHITECTURE / PROFILE_SCHEMA / SUPPLY_DEMAND_FRAMEWORK /
                         EVIDENCE_FRAMEWORK / SCENARIO_FRAMEWORK / core_tsi_spec / data_sources …
```

## 4. 数据现状与边界（务必照实使用）

| 数据 | 量级 | 口径 |
| --- | --- | --- |
| 招聘原始/去重 | 128,379 / 35,145 条 | AI·计算机目标语料 16,161 + 68 个专业作用域语料 18,931 |
| 本地全量招聘语料 | 72,759 条 | 非覆盖专业的**兜底需求口径**（`major_demand.py`，命中率与关键词全披露） |
| 培养方案课程库 | 29,187 条（13+ 所院校） | 由 `scripts/import_supplementary.py` 从 PDF/正文解析 |
| 教育事实 / 政策 / 文献 | 6,594 / 145 / 59 | 一手材料 + 归档 |
| 院校域名台账 | 32 所已核实 | `data/harvest/domains.json`；**可被大模型检索到的 URL 扩充** |

**边界（不得越界表述）**：

- 招聘记录只能写成 **Observed Job Posting Demand（可观察岗位招聘记录）**，不是社会岗位总需求；
- 课程池只能写成 **覆盖院校培养能力供给**，不是区域总供给；
- 学历=资格约束、薪资=市场切片，均不进 TSI 主体；政策/产业只输出**关联路径**，不做因果断言。

## 5. 十三批改造摘要（本次阶段内）

| 批次 | 内容 |
| --- | --- |
| 1 | 审计包 `audit/`：架构 / TSI / 数据 / Prompt / Skill / 报告 / 迁移计划 |
| 2 | 统一对象层：`profiles.py`（四层能力 + Supply/Demand/Gap Schema + 旧字段兼容）、`capability.py`、`tsi_tree.py`、`scenario.py`、`coverage_state.py`、`semantics.py`、`validate_edumatch.py` |
| 3 | S1 修复：`objective_alignment.py`（需求加权覆盖 + 目标有效性校验），修掉"假 0" |
| 4 | 三尺度 API `evaluation.py`、Conflict Resolver 接入引擎、Micro 接入（`analysis/micro.py` + `--micro-text`）、Simulation 重定位 `decision_support.py`、Finding 驱动 `agent/findings.py` |
| 5 | 按层级交付 `scope.py` / `scoped_report.py` / `html_report.py`，并追问是否补三视角 |
| 6 | 全面检索台账 `retrieval_sweep.py` + `pdf_text.py`（PDF 按需抽正文缓存） |
| 7–8 | 零数据模板 `reporting/templates/`；路由/条宽/微观结构修复；**课程解析缺陷修复**（拉丁课程名 + 适配器合并），课程库重生 |
| 9 | 岗位名泛化（同义词表 + `title_variants`）、宏观改用区域池、`--out-dir` 分层文件、`vocab.py` 词表清洗、runner 补采提示 |
| 10 | 检索台账加「院校/专业/文件」列；宏观列出**区域池由哪些院校组成**（`supply.peer_by_school`） |
| 11 | **自动补采** `auto_harvest.py`：本校 + 同类院校 × 全部材料类型；runner 交互默认开启；采到自动切 hybrid |
| 12 | **域名发现→核验→入库** `domain_discovery.py`：大模型联网检索 URL，系统按「官方教育域 + HTTP 200 + 页面含校名」核验后写入台账 |
| 13 | **报告信息密度层**：宏观逐校**信息源台账** + 需求侧画像（学历/行业/技能热度/薪资多条形图）+ **目标校×同类校×市场基准** + 多校就业结果对比 + 政策产业方向；中观**课程×技能矩阵**与同类院校基准；微观**个人缺口条形图**；来源页**数据资产总览** |
| 14 | **可用性修复**：微观四层缺口表重做为「汇总 + 按层展开（补回项目名）」；封面门卡去掉「（子指标）」不再换行；顶栏副标题动态化为本次院校/专业/岗位/证据分层；**招聘薪资打通**（`summarize_salaries`：月薪中位 / P25 / P75 / 分档，日薪剔除）；**补采本地优先 + 入口 B 自动重试**（`run_plugin_entry_b` / `carrier_pages_from`）；联网检索默认开启 |
| 15 | **展示定型**：顶栏删掉上下文小字、CSS 锁死单行省略号（不再顶高/顶宽）；三层子页大标题改为按当次分析生成（`_scale_titles`，如「软件工程相关培养能力 · 覆盖 7 所院校 · 921 门课程池 × AI 应用 / 工程化开发 可观察岗位招聘记录 1,636 条」），中观边界句写本校本专业；修掉顶栏校名未转义导致占位 `<院校>` 被吞的缺陷 |
| 16 | **通用性交叉验证（换院校/换专业/换岗位）**：修 `_school_records` 非三族专业按专业名匹配（此前「信息与计算科学」的多校就业结果整块消失）；**维度不许消失**——多校就业/中观缺口/微观缺口图与优先行动在缺数据时都渲染「未获取 + 怎么补」；新增封面「本轮数据不足 · 先看这里」横幅与 `_demand_label`（岗位族未命中但走专业导出语料要说清口径，不能误报"需求没获取"） |
| 17 | **补采清单 v2 + 去掉自建维度自检**：新增 `scripts\build_crawl_request_v2.py`，把"没数据"拆成**四类缺口**（岗位族未定义 / 岗位语料缺口 / 就业质量报告缺口 / 培养方案课程表解析缺口）并给出量化现状与建议动作；删除 `scripts\audit_report.py` 与 `scripts\selftest_crosscheck.py`——字符串级自检无法证明"数据用全了"，验证改为照真实流程跑通后逐页看最终报告 |
| 18 | **data/source 全量入库**：移植回三个缺失的入库脚本（`reextract_pdf_facts.py` / `extract_pdf_major_rows.py`，并让 `import_extra_text.py` 支持 .docx）；课程库 32,076 → **42,401 门**、教育事实 → **7,890 条**、分专业就业行 823 → **972 条**、材料利用率 **96.4%**；新增两类课程表适配器（北理工竖排展开表、北交大名先行）+ 课程代码放宽到字母数字混排；新增 `scripts\find_source.py` 让 Agent 能按院校专业定位原文与解析状态；**岗位需求不再依赖岗位族**（`_occupation_title_search` 用岗位名在全量招聘表直搜）。北理工会计学 × 会计：TSI 由「无法计算」变为 **61.16**、课程 0 → **61 门**、岗位匹配 **51.78** |
| 19 | **需求端全量合并**：新增 `scripts\merge_job_exports.py`，把 `data/source/招聘数据` 下**各张岗位表**合并成 268,196 条（通用语料 `jobs.json` 16,387 + 专业作用域 `major_jobs/<专业>.json` 251,809，按 274 个专业分文件惰性加载），简历表显式排除；岗位名直搜改为「通用表 + 本专业表」并级联 position → 映射列 → 子词 → 职责整词（≥3 倍门槛），大盘/大类岗位都能检索到；同城薪资基线改用 2 万条全量抽样并在 meta 披露。实测：会计 × 会计学 236 条、结构工程师 × 工程力学 161 条、翻译 × 英语 192 条；北理工会计学 × 会计 TSI 58.25、岗位匹配 53.3。补采清单 v2：岗位语料缺口 228 → **86** |

## 6. 验证基线（接手时可复跑）

```
python -m pytest tests -q                  # 196 passed / 3 skipped
python scripts\validate_edumatch.py        # 0 error / 0 warning（12 项检查）
python -m reporting.render --result r.json --scope all --out-dir out   # 分层 HTML
python scripts\build_crawl_request_v2.py                              # 重新生成「四类缺口」补采清单 v2
python scripts\find_source.py --school <校> --major <专业>             # 定位原文与解析状态（Agent 用）
python scripts\audit_data_coverage.py                                 # data/source 材料利用率审计
python scripts\merge_job_exports.py                                   # 合并 data/source/招聘数据 全部岗位表
python reporting\templates\build_page_template.py                     # 重建零数据模板
python EduMatch-演示页面\_build\build_page.py --scope all              # 标准演示页 + audit_page.py
```

实测样例：北工大信管 × 数据分析师 → Primary TSI 55.66、目标岗位匹配 56.18、个人适配 70.00；
自动补采北工大 **350 份材料**；hybrid 后本校课程 64 → 73 门；区域池 3 所（清华 205 / 中国地质 20 / 北理工 6）。

## 7. 已知缺陷与未完成项（如实交接）

1. **课程解析仍会漏行**：北工大信管 2024 原表 85 门、课程库 73 门（差 13 门，多为体育/军事理论/
   高等数学/实践环节）。已修好"拉丁课程名被丢弃"这个主因，其余漏行用
   `scripts/audit_course_coverage.py` 逐校核对；**供给为 0 前必须先跑它**。
2. **`--occupation` 的需求走岗位族切片**（AI/计算机语料）；全量语料兜底只在"一级专业分析"
   路径生效，因此"信管 × 数据分析师"这类组合的需求仍偏 AI 味，需继续做岗位族内的全量切片。
3. **S1 的培养目标原文**：多数院校的培养方案正文只有课程表；找不到本专业目标时用**校级代理**
   并明确标注、不计入 Primary TSI。补采到正文即可自动升级为专业级。
4. **Capability / Practice 需求侧数据**仍缺（微观以"证据不足"呈现）。
5. **入口 B（承载页直采）尚未自动化**：目前对 `empty/error` 的院校给出命令与 URL 参数，
   需要 Agent 先联网定位承载页。
6. **自动补采依赖网络与已核验域名**：离线/沙箱环境只出计划与缺口，不发请求。
7. **宏观"只有 1 所高校"的两类成因**：① 渲染层（旧版手写页 / 未走 `reporting.render`）；
   ② 数据层（`supply.peer_by_school` 为空）。数据层要靠 `-HarvestMode region` 分批补采，
   报告已把「目标池 / 已完成 / 待采」写进台账；两类都只能靠**跑一遍真实流程后看最终报告**确认。
   另外自动补采的同类校排序（可比院校）与宏观课程池院校（有本地材料的院校）目前**不是同一批**，
   待收敛为"先用区域池院校、再补可比院校"。

## 8. 接手第一小时建议

1. `python -m pytest tests -q` 跑基线；
2. 用 `.\analyze.ps1 "…"` 跑一个你关心的院校专业，打开 `报告_all.html` 看结构；
3. 跑 `python scripts\audit_course_coverage.py --school <校> --major <专业>`，
   若报"未入库课程"，先决定是补解析规则还是接受现状（不要直接把 0 当结论）；
4. 需要更多院校数据时：先联网检索官网 URL → `.\analyze.ps1 … -OfferUrl "校名=URL"`；
5. 交付前跑 `validate_edumatch.py`，并把"发现了什么 / 改了什么 / 还缺什么 / 下一步"写进结论。

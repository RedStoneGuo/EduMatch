# EduMatch

> **教育—就业供需适配分析引擎**：可被任意 Agent 调用的、确定性的、带证据链的多尺度分析系统。
> 输入「院校 + 专业 + 目标岗位」，输出宏观/中观/微观三层报告与单文件 HTML。

```
高校培养了什么？ → 市场需要什么？ → 在哪里匹配？ → 哪里出现缺口？ → 该补什么？
```

它不只给一个分数，而是回答：**区域高校培养能力与岗位需求的结构性差异在哪、差异长在专业层面还是个人层面、每一处结论能否反查到一手材料。**

---

## 这是什么 / 不是什么

| 是 | 不是 |
| --- | --- |
| **Agent 调用的确定性引擎**：Agent 是主体（问询、判断、读原文、写结论），引擎提供可复现的计算与渲染 | 不是自动下结论的黑箱；引擎不做价值判断 |
| **统一模型**：知识/技能/能力/实践四层 + 宏观/中观/微观三尺度，共用同一套技能本体 | 不是三个独立模型拼在一起 |
| **证据可反查**：每个数字挂来源等级 A 官方原文 / B 权威文献 / C 平台语料 / D 弱信号 / E 暂无 | 不用"缺失"冒充 0 分，也不用别的学校/专业数据顶替 |

---

## 工作原理

```
                  ┌────────────── 数据层 data/ ──────────────┐
 用户提问 ─► Agent │ 培养方案→课程库   就业质量报告→就业事实      │
                  │ 课程大纲/专业介绍→正文   招聘岗位表→需求语料   │
                  │ 政策文件→政策库        文献→方法论依据        │
                  └───────────────────┬──────────────────────┘
                                      ▼
 ① 取证       edumatch/retrieval_sweep.py   本地→归档→采集→联网，逐条留痕（命中/未命中+原因）
 ② 归一       ontology/ + edumatch/         课程名 / JD 文本 → 统一技能本体
 ③ 供给向量   analysis/supply.py            课程×技能矩阵（学分权重归一）
 ④ 需求向量   analysis/demand.py            岗位族 → 按专业导出语料 → 全量语料兜底（三级，逐级披露）
 ⑤ 匹配缺口   analysis/matching.py, micro.py  需求加权匹配、四层缺口、个人 L0–L4 证据分层
 ⑥ 总分解释   analysis/primary_tsi.py        Primary TSI（唯一正式总分）= 0.40F+0.20S+0.25O+0.15M
                                      ▼
 ⑦ 交付       reporting/render.py           三视角报告 + 分层单文件 HTML（可离线打开）
```

**决定结论可信度的六条设计**：

1. 数值只由 `analysis/` 的确定性函数产出；LLM 只做解释，不改数字。
2. 缺失记 `null` 并标注**「未获取」**，不参与加权分母——"没数据"和"0 分"永远分开。
3. **三层隔离**：目标校课程池 / 区域同类校课程池 / 招聘语料互不顶替；点名院校时目标校供给只取该校本专业培养方案。
4. **Primary TSI 是唯一正式总分**，Match / Skill Fit 一律标为子指标。
5. **F 维（供需适配）是定义性维度**：缺需求或供给就不出总分，不用剩余维度拼分。
6. **联网只走插件** `vendor/edu-material-harvest`，域名须"官方教育域 + HTTP 200 + 页面含校名"核验；红线是**绝不猜域名**。

---

## 快速开始

要求 Python 3.12 + `pandas / numpy / scikit-learn / pytest / PyYAML / pypdf`（见 `requirements.txt`）。

```powershell
cd EduMatch
pip install -r requirements.txt

# 1) 自检：数值范围 / TSI 唯一性 / 缺失语义 / 证据链
python scripts\validate_edumatch.py          # 期望 0 error

# 2) 跑第一份报告（离线；联网补采默认开启，见下方开关）
python scripts\analyze.py --query "分析北京工业大学信息管理与信息系统专业与数据分析师岗位的匹配度" `
    --occupation "数据分析师" --scope all --offline
```

产物落在 `分析产物\<院校>_<专业>_<岗位>\`：

| 文件 | 内容 |
| --- | --- |
| `报告_all.html` / `.md` | 三视角完整版（封面 + 总览 + 宏观 + 中观 + 微观 + 来源与复现） |
| `报告_macro.html` / `.md` | 只含宏观层（政府 / 区域视角） |
| `报告_meso.html` / `.md` | 只含中观层（专业 / 教师视角） |
| `报告_micro.html` / `.md` | 只含微观层（学生个人视角） |
| `result.json` | 引擎结果：所有数字的唯一出处，报告与 HTML 都由它渲染 |

HTML 是**单文件自包含**页面（内联 CSS/JS、无外链），双击即可离线阅读。

---

## 从 Agent 里调用（推荐）

仓库自带 `AGENTS.md`，**新开一个 Codex 对话窗口只需说一句**：

```
用 EduMatch（本包目录）分析 <院校><专业> 与 <目标岗位> 的匹配度。
```

Agent 会自动读 `AGENTS.md §0` 与 `skills/00_agent_entry/SKILL.md`，按「问询 → 补采 → 计算 → 渲染 → 自检」执行，**不需要复制任何长提示词**。

等价的一条命令：

```powershell
.\analyze.ps1 "分析北京工业大学软件工程专业与AI应用开发工程师岗位的匹配度" `
    -Occupation "AI应用开发工程师" -Scope all
```

| 开关 | 作用 |
| --- | --- |
| `-Occupation "<岗位>"` | 目标岗位（不填时引擎按语料推断，建议显式给出） |
| `-Scope all\|macro\|meso\|micro` | 交付层级（默认三视角；补做只新增不覆盖） |
| `-MicroFile "<个人画像.txt>"` | 微观层输入：课程 / 成绩 / 项目 / 实习（自然语言即可） |
| `-NoHarvest` / `-Offline` | 关闭联网补采（离线复现） |
| `-HarvestMode region -HarvestBatch 3` | 区域分批补采：一次一所、多轮累积，把区域采厚 |
| `-OfferUrl "校名=https://..."` | 你检索到的官网 / 承载页 URL，交给系统核验后入库 |

| 配套工具 | 用途 |
| --- | --- |
| `python scripts\find_source.py --school <校> --major <专业>` | 定位本地原始材料、解析状态与下一步动作（Agent 用） |
| `python scripts\build_crawl_request_v2.py` | 生成「四类缺口」补采清单（岗位族 / 岗位语料 / 就业报告 / 课程表解析） |
| `python scripts\audit_data_coverage.py` | `data/source` 材料利用率审计 |
| `python scripts\merge_job_exports.py` | 合并 `data/source/招聘数据` 下的全部岗位表 |
| `python scripts\relativize_paths.py --check` | 可迁移性检查（期望 0 处绝对路径） |

---

## 目录结构

```
EduMatch/
├── AGENTS.md                ★ Agent 作业规程（§0 自动执行指引 + 红线 + 已知坑位）
├── PROMPT.md                一句话启动说明
├── analyze.ps1              一条命令跑完整流程（Windows）
├── 交接文档.md              阶段性交付说明（成果 / 方法 / 数据 / 验证 / 待办）
│
├── agent/                   Agent 编排：问询、场景、Finding、报告
├── analysis/                ★ 确定性计算层：供给 / 需求 / 匹配 / 缺口 / TSI / 微观 / 机制
├── edumatch/                数据与知识层：dataset、课程解析、岗位归一、采集、证据链
│   ├── ingest/              培养方案 / 课程大纲 / 就业报告 / 政策 的解析器
│   └── jobs/                招聘岗位归一化、去重、需求向量
├── reporting/               ★ 交付渲染层：theme（CSS/JS）+ components + render
│   └── templates/           零数据模板（生成页面时对照结构与维度）
├── skills/                  给 Agent 的作业指导书（00–11）
├── ontology/                技能本体（课程 ↔ 岗位 统一词表）
├── mcp_servers/             把引擎能力以 MCP 工具对外暴露
├── vendor/edu-material-harvest/   联网采集插件（12 个 MCP 工具）
├── scripts/                 调用接口与工具链（analyze / 入库 / 审计 / 补采清单）
├── demo/                    静态页导出
├── tests/                   196 项单测
├── docs/                    方法论文档（数据源、可迁移性、升级计划…）
│
├── data/                    数据层（详见 DATA_MANIFEST.md）
│   ├── raw/                 课程库、模板、正文缓存
│   ├── processed/           需求语料、就业事实、索引、覆盖审计
│   └── source/              规范化原始材料（按"类型 → 院校"分层）
└── DATA_MANIFEST.md         ★ 本仓库带了哪些数据、缺哪些、怎么补回全量
```

---

## 报告长什么样

三视角 HTML 共用同一套版式（`reporting/theme.py` 是唯一版式来源）：

| 层 | 内容 |
| --- | --- |
| 封面 | 宏观-政府 / 中观-专业 / 微观-个人 三张入口卡（各带分数与点击跳转） |
| 总览 | 三尺度阶梯 + 证据等级图例 + 同一技能在三层的读数对照 |
| 宏观 | 区域课程池（**逐校信息源台账**）× 岗位需求、需求侧画像（学历 / 行业 / 技能热度 / 薪资分档）、目标校×同类校×市场基准、多校就业结果对比、政策与产业方向 |
| 中观 | 课程 × 技能矩阵（逐门可核查）、能力缺口明细、同类院校基准、证据冲突消解 |
| 微观 | 个人证据画像 L0–L4、四层缺口（知识 / 技能 / 能力 / 实践）、优先行动 |
| 来源与复现 | 编号来源可点回跳 + 运行编号 + 复现命令 + 数据资产总览 + 自动补采台账 |

> **缺数据的维度一律显示「未获取」并说明怎么补，而不是删掉。**

---

## 数据说明（重要）

为了让仓库 `git clone` 后**立刻能跑**，本仓库只带"跑得起来的最小充分集"（约 200 MB）：
全库课程库、通用招聘语料、就业事实派生物、**全量招聘语料紧凑索引**（任意专业需求兜底）、
同城薪资基线样本、政策文件。

**原始 PDF（约 4.5 GB，其中 6 个 >100 MB）不在仓库内**——GitHub 单文件上限 100 MB。
把原始材料放回 `data/source/` 后，按 `DATA_MANIFEST.md` 的命令重建派生物即可恢复完整能力。
含真实个人履历的简历数据**不入库**。

---

## 验证

```powershell
python -m pytest tests -q                  # 196 passed / 3 skipped
python scripts\validate_edumatch.py        # 0 error / 0 warning（12 项检查）
python scripts\check_portability.py        # 整包复制到任意路径 / 电脑可运行
python scripts\relativize_paths.py --check # 0 处绝对路径
```

---

## 常见问题

**能分析任意院校专业吗？**
可以。课程与就业事实按院校+专业作用域取数；需求侧有三级口径（岗位族 → 按专业导出语料 → 全量语料关键词切片），每级都在报告里披露口径与命中率。库外岗位（如"会计""结构工程师"）会用**岗位名在全量招聘表直搜**，不依赖预定义岗位族。

**为什么有的指标是「未获取」？**
因为本地确实没有该证据，而本项目**不允许估算或顶替**。报告会说明缺什么、去哪补。

**不看代码能直接用吗？**
能。把整个文件夹交给你的 Agent，说一句"用 EduMatch 分析 X 校 Y 专业与 Z 岗位的匹配度"即可。

**联网做什么？**
补齐目标院校/同类院校的公开材料（培养方案、专业介绍、课程大纲、年度报告、就业质量报告、教学质量报告）。多轮调用可把区域采厚；离线时只出计划与缺口，不假装采到。

---

## 许可与第三方

| 范围 | 许可 |
| --- | --- |
| 本仓库（EduMatch）自身代码与文档 | **MIT**，见 [LICENSE](LICENSE) |
| `vendor/edu-material-harvest/`（联网采集插件） | **第三方组件**，来源 <https://github.com/shoucunren-tsy/edu-material-harvest>，授权以**上游仓库**为准；本仓库的 MIT 不覆盖该目录 |
| 数据（各高校公开材料、招聘平台岗位导出） | 版权归原始发布方；本仓库保留出处字段，转载与再分发请遵守原始来源条款 |

详见 [docs/THIRD_PARTY.md](docs/THIRD_PARTY.md)。

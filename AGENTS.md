# EduMatch 工作约定（核心包）

> 本包是从 `EduMatch/edumatch_agent` 提取的**可运行核心系统**：只保留分析必需的代码与数据，
> 剔除全部过程缓存与历次产物。完整交接说明见 `交接文档.md`。

## 0. 首次进入请先看这里（新对话窗口无需粘贴任何提示词）

### 0.0 术语与角色（先统一称呼，避免用词混乱）

| 称呼 | 指什么 | 角色 |
| --- | --- | --- |
| **Agent（主体）** | Codex / 大模型 + `AGENTS.md` + `skills/` | **唯一的决策者与执行者**：跟用户问询、判断该采什么、读原始材料、下结论、决定交付层级 |
| **EduMatch Engine（本系统）** | 本 `EduMatch` 文件夹整体 | Agent **调用的确定性分析引擎**（工具系统），本身不做判断、不写结论 |
| **Toolchain / CLI（工具链）** | `analyze.ps1`、`scripts\*.py` | **引擎的调用接口**：把多步流程封成一条命令，供 Agent 调用（不是 Agent，也不代替 Agent） |
| **Core TSI Engine（计算引擎）** | `analysis/` | 纯函数计算层：Supply/Demand/Fit/Gap/TSI/Simulation |
| **Knowledge Base（知识/数据层）** | `edumatch/` + `data/` | 数据集、本体、证据链、采集与清洗 |
| **Renderer（交付渲染层）** | `reporting/` | 报告与单文件 HTML 的唯一版式来源 |
| **Skills（技能包）** | `skills/` | 给 Agent 的作业指导书（02–09 分项 + 10 分层交付 + 11 全面检索） |
| **MCP Server（MCP 服务）** | `mcp_servers/` | 把引擎能力以 MCP 工具暴露给外部调用方 |
| **Plugin（插件）** | `vendor/edu-material-harvest/` | **"插件"专指它**：外部联网采集插件（12 个 MCP 工具），引擎通过 `run_plugin_harvest` 调用 |

一句话：
> **Agent 是主体；EduMatch 是被它调用的确定性分析引擎；`.ps1` / `scripts/*.py` 是这个引擎的调用接口；只有 `vendor/edu-material-harvest` 叫插件。**

### 0.1 入口：谁调用谁

```text
用户 ──自然语言──► Agent（问询 / 判断 / 读原文 / 写结论）
                        │  调用
                        ▼
              EduMatch Engine
                 ├── Toolchain：analyze.ps1 / scripts\analyze.py（一条命令的流水线接口）
                 ├── Core TSI Engine：analysis\（确定性计算）
                 ├── Knowledge Base：edumatch\ + data\
                 ├── Renderer：reporting\（报告 / HTML）
                 └── Plugin：vendor\edu-material-harvest（联网采集，经 run_plugin_harvest）
```

`analyze.ps1` / `analyze.py` 的定位是**接口 + 走查清单**：它们不替 Agent 判断，只保证
"补采 → 计算 → 渲染 → 质量门"这几步按规范、按顺序、可复现地执行完；
Agent 需要单点能力时（核对课程覆盖、核验域名、跑质量门）也可以只调对应的单个脚本。

### 0.2 首轮先问询，不要带着默认专业/岗位就开跑

用户第一句往往只有方向（"帮我做个就业匹配分析"）。这时**不要**直接跑分析——先按
`skills/00_agent_entry/SKILL.md` §2 的多轮问询把下面几项问清楚：

1. 尺度与对象：宏观（区域/政府）· 中观（院校+专业/教师）· 微观（个人/学生）；
2. 院校 + 专业；不知道目标岗位时先做**岗位探索**（给 3–5 个候选含要求与薪酬区间）；
3. 微观补充：课程/成绩/项目/实习（自然语言即可，可分批给）；
4. 交付层级：第一版只要一层，还是直接三视角。

系统会在目标不明确时**拒绝直接执行**并打印问询清单：

```powershell
.\analyze.ps1 "帮我做个就业匹配分析"     # → 只输出问询清单，不跑分析
.\analyze.ps1 "…" -Ask                   # 同上（显式）
```

### 0.3 目标确认后：调用引擎（一句话即可）

用户说一句"用 EduMatch 分析 <院校/专业> 与 <岗位> 的匹配度"即可：

1. **跑这一条命令**（系统会自动：插件补采 → 引擎分析 → 分层报告 MD+HTML → 质量门）：

   ```powershell
   cd <本包目录>            # 例如 D:\Codex_project\EduMatch\EduMatch，或整包拷贝后的任意路径
   .\analyze.ps1 "分析北京工业大学信息管理与信息系统专业与数据分析师岗位的匹配度" `
       -Occupation "数据分析师" -MicroFile "<个人画像.txt，可选>" -Scope all
   ```

   等价写法：`python scripts\analyze.py --query "…" [--occupation …] [--micro-file …] [--scope …]`。
2. **需要更多同类院校数据时**：先自己联网检索目标院校官网/承载页 URL，再交给系统核验
   （官方教育域 + HTTP 200 + 页面含校名）：

   ```powershell
   .\analyze.ps1 "…" -OfferUrl "北方工业大学=https://www.ncut.edu.cn/" -PeerMax 3
   ```
3. **交付物**默认落在 `..\分析产物\<院校>_<专业>_<岗位>\`：`报告_all.html` 为三视角完整版，
   `报告_macro/_meso/_micro.html` 为分层版（补做只新增、不覆盖），同名 `.md` 为文字版。
4. **交互问询仍保留**：需要和用户多轮确认时按 `skills/00_agent_entry/SKILL.md` §2 执行；
   数据/口径/红线见本文件 §3–§10。

5. **宏观/中观要"多校采全"，允许多次调用**：一次调用默认只采一所目标校 + 2 所同类校。
   要把区域采厚，用**区域分批模式**，每调一次采一批，台账会累积、自动跳过已采成功的院校：

   ```powershell
   .\analyze.ps1 "分析北京市人工智能相关专业与 AI 岗位的匹配情况" -HarvestMode region -HarvestBatch 3
   # 重复执行同一命令即可继续采下一批；输出会提示"区域池还剩 N 所"
   ```

   采到满意覆盖率（或 `region_progress.remaining = 0`）后再出宏观/中观结论；
   累计台账在 `data/harvest/auto_harvest_ledger.json`。

> 一句话总结：**新窗口只需说清楚"分析谁 × 什么岗位"，然后跑 `analyze.ps1`。**
> 具体规则不用再复制 PROMPT.md；`PROMPT.md` 只是同样内容的对外短版。

## 1. 运行环境

- Windows / macOS / Linux 均可；Python 3.12（本项目验证环境示例：`D:\Miniconda\Data\Envs\Pytorch`，
  换机器时用 `EDUMATCH_PYTHON` 环境变量指定解释器，**不要依赖某个固定盘符**）；
- 依赖：pandas / numpy / scikit-learn / pytest / PyYAML / pypdf / streamlit；
- 不需要网络（可选：句向量模型、OpenAlex 检索、合规抓取）。

## 2. 常用命令

```powershell
python -m pytest tests -q                                     # 117 passed / 3 skipped
python scripts\run_evaluation.py                              # 12 案例 + 10 指标
python -m agent.runner --list-occupations
python scripts\batch_school_analysis.py --major 人工智能 --schools 北京工业大学 --occupation "大模型算法工程师"
python scripts\import_supplementary.py --all --families ai,cs,econ   # 培养方案 → 课程库
python scripts\relativize_paths.py --check                    # 路径可迁移性检查
python -m mcp_servers.server --selftest
python demo\export_static.py
```

## 3. 硬性约束（改代码前先读）

1. **数值只由 `analysis/` 计算**；`agent/llm.py` 只做解释，禁止产出或修改数字。
2. **缺失必须 `value=None` + `evidence_level='E'`**，禁止记 0；缺失不参与加权分母。
3. **就业结果只接受就业质量报告**（可回退同校校级口径并标注）；招聘数据只用于需求侧。
4. **三层隔离**：课程池按 `family` / `major` / `school` 过滤；点名院校时目标校供给只用该校
   本专业培养方案；E 级模板课程只进区域池。
5. **岗位需求只取该岗位族**；语料不覆盖该专业族（关键词覆盖率 < 30%）→ `insufficient_evidence`。
6. **报告保留 18 个编号章节**；正式主指标只有 `primary_tsi`，V1/V2 仅作历史与研究对照。
7. **`F_供需适配` 是 Primary TSI 的定义性维度**，不可用时不予计算（不用其它维度拼分）。
8. 因果表述受 `analysis/mechanism.guard_causal_language` 约束：只输出"关联路径"，不做因果断言。

## 4. 路径与迁移

- `config/config.yaml` 内全部为**相对路径**（`workspace: "."`、`archive: "reference/archive"`）；
- 数据文件中的来源路径：包内材料写作 `data/source/...`，包外归档写作 `../AI竞赛数据归档/...`；
- 换电脑/盘符后跑一次 `python scripts\relativize_paths.py --check`，期望输出 0 处待改写；
- **原始归档材料已随包**：`data/source/` 有 2,510 个文件 / 约 4.13 GB（培养方案/年度报告/专业介绍/
  课程大纲/政策等）；包外 `../AI竞赛数据归档` 只是历史补充源，缺失不影响主流程。

## 5. 已踩过的坑（避免重复）

1. **表头驱动解析培养方案**：不同学校版式不同（学分/总学时顺序、名先行/码先行）；
   ≥20 行才认为版式被识别，否则整份返回 0（宁缺勿造）；名先行版式暂不支持。
2. **课程主键必须含专业**：`plan:<学校>:<专业>:<年份>:<课程号>`，不同专业共用课程号，
   缺专业会互相覆盖。
3. **专业族映射只用 `major_family()`**：不得用"含智能即 ai"这类宽口径
   （智能制造工程曾被误并入人工智能）。族注册表在 `config.yaml::families`，
   不依赖 `data/raw/majors_*.txt`（那三份策展文档仅占课程 0.7%，可选）。
4. **检索缓存**：`Dataset._course_cache` 与 `ResearchEngine._skill_name_cache` 在进程内复用；
   改 `course_set` 后确认缓存键含 family/major/school/include_template。
5. **单位正则陷阱**：`unit in "万wW"` 对空字符串恒为真，必须写 `unit in ("万","w","W")`。
6. **供给量纲**：供给不能按"占总学分比例"算，用 `Supply = min(Σw / C_ref, 1)`，`C_ref=6`。
7. **引擎课程池可能不是你分析的那一版**：点名院校专业时，若本地有多版培养方案，引擎只装入其中少数几份
   （实测 北京工业大学软件工程 → 2019 版 68 门 + 2025 版 22 门，共 90 门，**未装 2024 版**）。
   做"个人/在校生"分析时，先用 `result["courses"]` 核对 `year`/`major` 分布；正文结论一律以学生
   实际所在版本的方案原文为准（`data/raw/pdf_text/<校>/培养方案/<年>_<专业>.txt`），引擎课程池只作参照。
8. **技能本体是 AI 向，非 AI 岗位的技术栈会被折叠或漏抽**：`ontology/skill_ontology.yaml` 里没有
   Hive / Spark / Flink / Kafka / ClickHouse / Doris，这些需求要么并入"数据工程"节点、要么抽不到；
   同一条 `course_skill_rules` 还把"程序设计/面向对象"类课名统一映射到 `编程 + Python`，导致
   《JAVA程序设计》存在却记 `Java` 供给 = 0。结论：算"数据开发/数据平台"类岗位时，
   工具栈需求一律按 JD 原文正则统计，不要采信引擎的"供给充足/过匹配"判定。

## 6. 数据来源层（新增，改这块前必读）

1. **`data/source` 是供给端原始材料的唯一规范位置**，结构固定为「数据类型 → 院校」；
   禁止把包外目录（`../数据整理与补采/...`、`../AI竞赛数据归档/...`）再当作分析数据源。
   重组脚本 `scripts/normalize_source_layout.py` 幂等，`--check` 返回 0 才算规范。
2. **院校名一律过 `edumatch.local_supply.canonical_school()`**：PDF 抽取会把
   "中国矿业大学（北京）"写成"中国矿业大学"，不归一会导致按校检索命中 0。
3. **插件红线：绝不猜域名**。域名只能来自 `data/harvest/domains.json`（由本项目采集台账
   生成）或调用方显式传入；无域名时如实报错，不联网试探。
4. **收割件即使与本地同名同内容也要解析进收割库**（`data/harvest/<校>/`）。只做原件去重、
   不做解析去重，否则 `plugin` 模式（不依赖本地库）会缺这批课程。重复导入必须幂等。
5. **三模式切换只走 `Dataset._apply_source_mode(mode, harvest_schools)`**：它按首次装配前
   保存的本地快照重建，直接改 `ds.courses/facts` 会让模式叠加。`plugin` 模式不得读本地
   课程/事实/正文（`text_roots()` 在 plugin 下只返回收割正文根）。
6. **需求侧不随模式改变**：招聘语料始终取本地 `jobs.json` 并按岗位族切片。
7. 报告仍保留 **18 个编号章节**；数据来源信息写进 `result["data_source"]` 与 §18
   定点检索清单，不新增章节。

## 7. 本轮新增的历史坑位

1. **插件 MCP 服务端把真正的 stdout 用来写 NDJSON 协议**（fd1 先被指向 devnull）。
   客户端必须用 `subprocess` 管道 + 读线程配对请求，不能假设 stderr 有日志；
   也不要往插件的 stdout 打任何调试输出。
2. **经代理访问国内高校站点会触发校方 IP 认证**（302 → `ipauth.htm`），表现为"反爬拦截"。
   采集国内 *.edu.cn 一律直连，不要设 `HTTP_PROXY/HTTPS_PROXY`。
3. **全站爬不等于采到**：北工大培养方案挂在 `undergrad.bjut.edu.cn`，全站爬 0 命中；
   用采集台账里的承载页走 `harvest_pages` 一次拿到 350 份。遇到 0 命中先换入口 B，
   不要反复爬。
4. **`data/source` 里的 `.doc`/`.xls` 拿不到文本层**，如实记 `extractor_unavailable`，
   不要为了让覆盖率好看而猜测内容。

## 8. 同类院校与需求侧语料（2026-10-04 新增）

1. **同类院校判定走 `edumatch/peers.py`，全国口径**，用插件下发的教育部全国名单
   （2,952 所）+ 985/211；排序必须可解释（层次/地域/校型/可采集性），每个候选都要有
   `reasons`。**这不是排行榜**，不得改造成打分排名对外发布。
2. **域名只能"候选 + 实测确认"**：`scripts/resolve_school_domains.py` 要求 HTTP 200 且页面
   出现校名才写入 `data/harvest/domains.json`。禁止把未核实的域名直接塞进台账。
3. **插件采回来的材料要过类型闸门**：`HarvestImporter._suspect_reason` 会把"培养方案/课程大纲
   却是 .doc/.xls"的站点表格页隔离到 `data/source/非分析归档/疑似误判/`。
   这是插件文档里的"类型假"陷阱，站点栏目名（如"本科生院下载"）不等于材料本体。
   大站/被拦站点走入口 B（承载页直采），别反复全站爬。
4. **按专业导出的岗位语料（`corpus="major_export"`）与既有 AI/计算机语料物理隔离**：
   `target_jobs()` / `baseline_jobs()` 必须排除它，否则会稀释 AI 口径；
   分析某专业时优先用它的 `major_scopes`（专业作用域），不要再退回"关键词恰好出现"。
5. 一条岗位可同时属于多个专业（如建筑学 / 建筑环境与能源应用工程），
   并表时**合并进 `major_scopes` 列表**，不要按指纹把后来的专业丢掉。

## 9. 多尺度升级层（2026-10-05 新增，改这块前先读）

1. **统一对象层**：`edumatch/profiles.py`（`SupplyProfile` / `JobProfile` /
   `PersonalEvidenceProfile` / `Gap` / `apply_legacy_compat`）。四层固定为
   `knowledge / skill / capability / practice`；`JobProfile` 的学历是约束、薪资是切片，
   **都不进入匹配主体**。旧字段（match / tsi_score / matching_score）不删除，只加规范别名。
2. **能力推断**：`analysis/capability.py`。能力 = 规则化的知识+技能+实践组合，
   缺失分量不进分母、不记 0。需求侧 Capability/Practice 数据尚未补齐。
3. **冲突消解**：`analysis/conflict_resolution.py`。引擎结果与 A/B 级原始证据冲突时
   只修正并重算受影响技能，记录 original/reconciled/evidence_source/mapping_reason/
   recalculation_scope/run_id/timestamp；**禁止**因此重跑全系统。
4. **TSI Tree**：`analysis/tsi_tree.py`，只分解不重算；`fit` 参数可传 fit 结果或
   `{primary/peer/target: {...}}` 捆绑。
5. **场景**：`analysis/scenario.py` 按目标动态选维度并封顶（`max_scenarios`），
   禁止指数爆炸。
6. **数量口径护栏**：`edumatch/semantics.py` + `edumatch/coverage_state.py`。
   招聘记录只能叫 **Observed Job Posting Demand**；高校课程池只能叫"覆盖高校培养能力供给"；
   否定语境（"不是…总需求"）不算违规。**只有到 `READY_FOR_ANALYSIS` 的院校才算覆盖。**
7. **自动质量门**：改完模型 / 报告 / 页面后必须跑
   `python scripts\validate_edumatch.py`（期望 0 error）；它检查数值范围、权重和、
   TSI 唯一性、缺失语义、证据链与报告口径。演示页面另跑
   `_build\audit_page.py`。
8. **已知待办**：S1（培养目标—岗位一致性）目前是 D 级 bigram 代理，
   两侧词表不相交时合法返回 0 并计入 S 维（实测把该维从 ~77 拉到 50.22）。
   治理必须走显式版本升级（primary-3.1），**不得静默改公式**。

## 10. 课程解析与渲染的坑（2026-10-05 新增，改前必读）

1. **以拉丁字母为主的课程名会被 `_clean_name` 整体丢弃**（历史缺陷）：
   `NAME_OK` 要求以汉字开头、且"汉字<3 且无提示词"直接拒绝，导致
   《Python语言》《Java语言II》《C语言程序设计》这类课进不了课程库，
   下游把 Python/Java/C 供给记成 0，看起来像"专业没教"。
   现已加 `TECH_NAME_HINTS` 白名单放行；**新增课程名清洗规则时必须回归这一点**。
2. **适配器不能"先达标就 break"**：`parse_plan_text` 现在把
   `parse_rows_by_header` 与 `parse_rows_bjut` 的结果**按课程代码合并**
   （表头驱动字段更全、编码驱动行更全）。历史上因为先达标就 break，
   表头适配器识别不到的行被整行漏掉。
3. **改动解析器后必须重跑课程库**：`python scripts\import_supplementary.py --school <校> --force`
   （按校 force 会保留其它院校记录）。课程库是派生件，但**报告用的是它**，
   不重跑则修复不生效。实测北工大信管 2024：61 → 64 门，Python 供给 0 → 1.0。
4. **核对工具**：出结论前跑
   `python scripts\audit_course_coverage.py --school <校> --major <专业>`
   对比培养方案原表与课程库，列出未入库课程（含语言类漏行）。
5. **HTML 交付只能用 Core 渲染器** `python -m reporting.render`；
   所有页面区块必须包在 `<section class="view" id="…">` 里，且**只有 `#cover` 带 `on`**
   ——否则内容会在每个子页重复出现、顶栏跳转失效。
   零数据模板见 `reporting/templates/page_template.html`，改版式后重跑
   `python reporting/templates/build_page_template.py` 并跑渲染测试。
6. **岗位名必须泛化检索**：`occupation.py::title_variants` 去前缀（高级/资深/应届…）
   与后缀（工程师/分析师/师/员…），同义词表把「算法分析师」归到数据分析族。
   `match_scope` 保持 `position` / `position+description` 契约，泛化信息放
   `generalized` / `matched_terms` / `expansion`。**原词零命中不等于检索不到。**
7. **宏观用 peer（区域同类专业课程池）、中观用 target（本校）**：渲染器
   `_tree_adapter(result, "macro"|"meso")` 已按层取向量，不要用同一份供给画两层。
8. **分层交付是"新增"语义**：`python -m reporting.render --out-dir <目录>` 产出
   `报告_macro/_meso/_micro/_all.html`；补做单层再跑一次即可，**不得覆盖已有交付物**。
9. **词表噪声统一由 `edumatch/vocab.py` 清洗**：通用词（问题/场景/制定…）与
   "算法 / 算法分析"这类包含项在**展示层**合并/剔除，匹配口径不变；新增词表相关逻辑时走这里。
10. **自动补采是默认动作**（`edumatch/auto_harvest.py`）：交互调用自动开启
    （`--auto-harvest` 强制、`--no-auto-harvest` 关闭），目标 = 点名院校 + 同类院校，
    材料 = `ALL_KINDS` **全部类型**（培养方案/专业介绍/课程大纲/年度报告/就业质量报告/教学质量报告），
    **禁止"抓到一个教学计划就收手"**。域名走**发现→核验→入库**：
    大模型自己联网检索官网/承载页 URL，交给 `edumatch/domain_discovery.py` 核验
    （官方教育域后缀 + HTTP 200 + 页面含校名），通过后写入 `data/harvest/domains.json`；
    本地台账与存档只作交叉验证，**不是唯一来源**，未核验的域名不得用于采集；
    失败要走入口 B 重试；采完必须复核覆盖并把
    「采了什么/没采到什么/为什么/下一步」写进报告自动补采台账；采到后自动切 hybrid。
    单个院校失败不抛异常，只记录 `status/reason`——分析照常进行并如实披露。

## 11. 报告信息密度规范（2026-10-05 新增，渲染器已内建，禁止删块）

用户反复反馈的两个问题：**宏观看不出用了哪些高校的信息源**、**报告维度比演示页薄**。
渲染器 `reporting/render.py` 已内建下列区块——**缺数据要显示「未获取」，不能整块删掉**。

1. **宏观必须逐校回答"用了谁的数据"**：`_macro_source_html` 用
   `supply.target_by_school` + `supply.peer_by_school` + `coverage` +
   `benchmark.education_background` + `auto_harvest.attempts` 拼出
   「宏观信息源 · 覆盖院校台账」（院校 / 角色 / 可核查课程 / 材料类型·状态 /
   该校就业结果 / 来源渠道 / 状态），并配「各校课程供给贡献」条图。
   **统计卡口径必须是「区域课程池院校 N 所」，目标校单列且不合入区域池**；
   出现「本地入库覆盖高校 = 1 所」这种写法即为回归缺陷（`coverage.n_schools`
   只统计目标校，不代表区域池）。
2. **宏观页必含（多条形图语言，对齐 `EduMatch-演示页面/index.html`）**：
   需求侧画像（学历结构 / 行业分布 / 技能热度 / 薪资）、宏观信息源台账 + 各校课程贡献、
   目标校 × 同类校 × 市场三角对照、技能级三方对照、同类高校就业结果对比（逐校条形）、
   政策与产业方向。对应函数：`_macro_market_html` / `_macro_source_html` /
   `_macro_benchmark_html` / `_macro_outcome_html` / `_macro_policy_html`。
3. **中观页必含**：培养方案解剖（课程 × 技能矩阵，逐门可核查 + 未映射课程清单，
   `_meso_course_skill_html`）、同类院校基准（逐技能本校 vs 同类校 vs 市场，
   `_meso_peer_bench_html`）。**不允许只留一句「同类院校基准 · 口径 X」**。
4. **微观页必含**：个人缺口条形图（需求 vs 个人供给，未出现记证据不足，
   `_micro_gap_chart`）、L0–L4 证据分层口径说明、四层缺口全量明细、优先行动。
5. **来源与复现页必含**：数据资产总览（本地文档 / 课程 / 政策 / 采集入库规模 +
   证据等级分布）、编号来源清单（可点进可回跳）、自动补采台账、复现命令。
6. **多校采全是常态，不是可选项**：宏观只出现 1 所高校不是正常结果。默认覆盖
   「目标校 + 同类校若干」；要采厚用 `-HarvestMode region -HarvestBatch N` 重复调用累积，
   报告要写清区域补采进度（目标池 / 已完成 / 待采）。
7. **排查"宏观只有 1 所高校"**：先看 `result["supply"]["peer_by_school"]`。
   有值 → 渲染问题（确认用的是 `python -m reporting.render`，不是旧版手写页）；
   为空 → 该专业 `family`/`major` 的 peer 课程池为空，需先补采或核对 `course_set` 过滤。
8. **改渲染器后的回归**：跑 `python -m pytest tests -q`（含
   `tests/test_reporting_render.py` 的逐校台账 / 需求画像 / 课程矩阵断言），并重跑
   `python reporting/templates/build_page_template.py` 更新零数据模板。
9. **Markdown 与 HTML 同源**：分层 Markdown 由 `agent/scoped_report.py` 渲染
   （`_sources_block` / `_demand_profile_block` / `_benchmark_block` / `_outcome_block` /
   `_policy_block` / `_curriculum_block` / `_micro_gap_block` / `_assets_block`），
   与 HTML 共用同一份 `result.json` 与 `school_ledger()`。改了一侧就要同步另一侧，
   别让"报告和网页两版内容"再次分叉。
10. **封面的分数单位不许换行**：门卡只写 `/100 目标岗位适配`、`/100 个人岗位适配`，
    **不要带「（子指标）」**（正文统计卡里保留"（子指标）"标注，Primary TSI 唯一性不受影响）。
11. **顶栏必须单行、简短，且不再有上下文小字**：由 `_nav_subs()` 生成——
    宏观＝`区域 · N 所高校`、中观＝`<院校> · <专业>`、微观＝`证据分层 L<n>`；
    其余项沿用"入口 / 阶梯与对照 / 数据与复现"。**已删掉**
    `院校 · 专业 · 岗位 · scope=…` 那行小字（它会把顶栏顶宽、顶高）；
    院校/专业/岗位在封面与各层页头里给全。CSS 已锁 `.sn-links a span`
    单行 + `text-overflow:ellipsis`（`max-width:150px`）。**禁止改回长文案**（回归测试已锁）。
12. **微观四层缺口表必须可读**：`_micro_layers_html` 先给汇总
    （需求项 / 已覆盖 / 有缺口 / 证据不足 / 最紧迫缺口），再按层展开
    **项目名 + 需求 + 个人供给 + 缺口**；证据不足的项按需求强度列前 12 并写明"≠0 分"，
    其余只报数量。**曾经把 40 行 `知识 Knowledge | 0.34 | — | — | 未在个人证据中出现`
    铺满一屏、还漏了项目名——不要再犯**。优先行动同理由 `_micro_actions_html` 归并。
13. **三层子页大标题必须按当次分析生成**：由 `_scale_titles(result)` 产出——
    宏观＝`<专业>相关培养能力 · 覆盖 N 所院校 · M 门课程池 × <岗位> 可观察岗位招聘记录 K 条`、
    中观＝`<院校> · <专业> 培养方案 · T 门可核查课程 × <岗位> 能力要求`、
    微观＝`个人证据画像（L<n>）→ <岗位> 补齐建议`；中观边界句同样写本校本专业名称。
    **禁止回退成 `区域供给（覆盖高校样本） × 可观察岗位招聘记录` 这类死模板句**（回归测试已锁）。
    校名/专业名一律过 `C.e()` 转义——零数据模板的占位是 `<院校>`，不转义会被浏览器当标签吞掉。

## 12. 数据获取与薪资口径（2026-10-05 新增）

1. **联网检索是默认动作**：`scripts/analyze.py` / `agent/runner.py` 的自动补采默认开启，
   只有显式 `--no-auto-harvest` / `--offline` 才关闭；未点名院校时改走**区域口径**而不是跳过。
2. **先本地、后联网**：`auto_harvest.local_material_counts()` 先统计
   `data/source/<类型>/<院校>/` 已有多少份，**只对本地为空的材料类型**调插件
   （`attempt.local_materials` / `attempt.kinds` 记录在台账里）。
3. **入口 B 自动重试**：入口 A（全站/栏目）没采到材料时，系统自己调
   `run_plugin_entry_b()` → `HarvestClient.discover()` 定位承载页（`jobs.json` 的
   `page`、退回 `discover_report.json` 的 `pages`）→ `harvest_pages` 直采下载。
   **不要再让用户/上层 Agent 手工去找承载页 URL**；`carrier_pages_from()` 取不到就如实报原因。
4. **招聘薪资必须可用**：`dataset.summarize_salaries()` 是唯一薪资口径——
   月薪（HAR 岗位常只有 `salary_min/max`，`*_norm` 为 null 也要认）→ 中位数 / P25 / P75 /
   分档分布；`salary_is_daily()` 用 `salary_detail` 文本与量级剔除"元/天"实习报价
   （否则中位薪资会被拉到几百元）。`occupation.requirements.median_salary` 与
   `market.median_salary_target` 都走这条路径，报告用条图展示分档分布。
5. **需求口径要说实话**：`demand_scope.coverage` 记录本轮到底用了哪套需求
   （岗位族 / 按专业导出语料 / 全量兜底）。岗位族没解析成功 ≠ 没有需求：
   `_demand_label()` 会退回「<专业> 专业需求语料 N 条」，标题与封面提示都必须按这个真实口径措辞。
   岗位级 Match 不可算时，要说清"F 维照常计算、Match 不可计算"，不能说成"需求没获取"。
6. **维度不许消失（验收标准）**：任何一块在缺数据时必须渲染成「未获取 + 怎么补」，
   **不能整块 return ""**。已加固的几处：多校就业结果（`_macro_outcome_html`）、
   中观能力缺口（无缺口行时输出"无显著缺口"或"需求证据不足"）、
   微观个人缺口条形图 / 优先行动（无个人画像时输出获取路径）、封面「本轮数据不足 · 先看这里」横幅
   （`_data_gap_banner`，与 `_demand_label` 配合，避免把"换口径"误报成"没数据"）。
7. **非三族专业的多校就业事实**：`_school_records` 在 `plan.family` 为空时改按
   **专业名**匹配（`major_matches`）。历史缺陷是一律按 family 过滤，
   导致「信息与计算科学」这类通用专业的「同类高校就业结果对比」整块消失（数据其实存在）。
8. **验证只认「真实流程跑出来的报告」**：不要用自建清单脚本宣称"维度齐全"——
   脚本只能证明某段字符串出现过，证明不了最终报告真的把数据用全了。
   正确做法是照 `analyze.py` 的真实流程跑一遍（补采 → 引擎 → 渲染 → 质量门），
   然后**逐页看最终 HTML/MD**：数字是否有来源、维度是否有读数、缺的地方有没有写明"未获取 + 怎么补"。

## 13. `data/source` 全量入库与原始文件可检索（2026-10-06 新增）

**目标：4 GB 本地数据要真正进模型，解析不了也要让 Agent 能检索到原文自行补齐。**

1. **四类缺口分开处理**（`scripts\build_crawl_request_v2.py` → `数据补采需求清单_v2.csv`）：
   ① 岗位族未定义（可选精度项）/ ② 岗位语料缺口 / ③ 就业质量报告缺口 /
   ④ 正文**有**课程表但版式未识别（先修解析，别重复采）/ ⑤ 正文**不含**课程表（材料不完整，去补采）。
   **"没数据"和"没解析"是两件事**，混在一起会让人去补本来已有的数据。
2. **原始文件检索入口**：`python scripts\find_source.py --school <校> --major <专业>`
   ——列出该院校专业在 `data/source` 有哪些材料、正文抽了没有、正文里有没有课程表/就业表、
   结构化入库了多少、下一步该读原文/修解析/补采。**Agent 拿不到数据时先用它定位原文**。
3. **课程表适配器（`edumatch/ingest/plan_tables.py`）现在覆盖四类版式**，改之前先读它们的实测背景：
   * `parse_rows_by_header`：代码 + 名称 + 数值**同行**（北工大/北大/清华/地大/民族）；
   * `parse_rows_exploded`：**代码单独成行**、名称/英文名/数值逐格换行（北理工 96 个专业）；
   * `parse_rows_name_first`：**名称在前、代码在后**（北交大 `结构有限元分析 30L134Q 选 理 2 32 32`）；
   * `parse_rows_bjut`：北工大严格结构兜底。
   四者按优先级 `setdefault(code, row)` 合并，**不要改回"先达标就 break"**。
4. **课程代码正则**：`COURSE_CODE` 放宽为"5–14 位字母数字"，但必须再过
   `_looks_like_course_code()`（≥4 位数字）。**踩过的坑**：只放宽成"字母数字"后，
   `Business` / `Simulation` 这类英文课程名被当成代码行，把竖排表的缓冲截断，
   北理工会计学课程数从 47 掉到 13。`CODE_ONLY` 同理，必须配 `_is_code_line()`。
5. **三个入库脚本缺一不可**（从旧 `edumatch_agent` 移植回来，路径已按本包结构改写）：

   ```powershell
   python scripts\import_extra_text.py            # PDF/docx → data/raw/pdf_text 正文缓存
   python scripts\import_supplementary.py --all --force --max-mb 80   # 培养方案 → 课程库
   python scripts\reextract_pdf_facts.py          # 正文 → pdf_facts.json（校级事实）
   python scripts\extract_pdf_major_rows.py       # 就业质量报告 → pdf_major_rows.json（分专业就业行）
   python scripts\audit_data_coverage.py          # 覆盖率审计（当前 96.4%）
   python scripts\relativize_paths.py             # **必跑**：把派生件里的绝对路径改回相对路径
   ```

   改完解析规则必须**重跑对应入库脚本**，否则报告读到的还是旧派生件。
   入库脚本会把本机绝对路径写进课程库/事实库（便于溯源），跑完**务必再跑
   `relativize_paths.py`** 并 `--check` 到 0 处，否则整包没法迁移到别的电脑/路径。
6. **岗位需求不完全依赖岗位族**：`dataset._occupation_title_search()` 在岗位族未登记时，
   用**岗位名 + 去后缀变体**在全量招聘表直搜（position → position+description），
   命中够门槛就照常出岗位级 Match，并把检索词与命中数写进 `demand_note`。
   实测：会计 237 条、结构工程师 223 条、护士 106 条——本地语料本来就有，
   缺的只是"登记"，不是数据。**任何"岗位族未定义"的报错都不该直接变成"无法分析"。**
7. **需求端要把 `data/source/招聘数据` 全用上**（`scripts\merge_job_exports.py`）：
   该目录下有多张表（`全部招聘数据汇总.csv` 7 万行、`招聘岗位数据_v2总表.csv` 21.8 万行…），
   合并后 **268,196 条**：通用语料 `jobs.json`（16,387，AI/计算机关键词 + 同城基线）
   + 专业作用域语料 `data/processed/major_jobs/<专业>.json`（251,809，**按专业分文件、惰性加载**）。
   * 简历表（`北京人工智能简历数据.xlsx`）**不是岗位表**，归微观求职侧基线，导入时显式跳过；
   * 去重键＝`fingerprint`（公司+岗位+城市+薪资），专业行再叠加专业名——**不要用 `content_key`**，
     它不含公司，会把不同公司的同薪同名岗位合并（实测 21.8 万行只剩 5 千）；
   * 通用语料的 `search_keyword` **只从来源表推**（`北京人工智能招聘数据`/`北京计算机领域招聘数据`）：
     汇总表的「来源检索词」列常填行业名，拿它当检索词会把 target/baseline 划分搞错；
   * 读写 JSONL 用 `split("\n")` 而不是 `splitlines()`——岗位描述里的 U+2028 会被当换行劈开。
8. **岗位名直搜的级联顺序（改之前先读）**：① 完整岗位名匹配 `position` →
   ② 数据自带的 `岗位-映射后`/`岗位类型-映射后` → ③ **子词**放宽（只允许落在岗位名/映射列）→
   ④ 最后才允许 `position+job_description` 整词匹配，且要求 ≥3 倍门槛。
   **禁止用"取末尾 N 字"这类启发式**：「航天器总体设计」会被截成「总体设计」，
   在职责里匹配到一堆无关岗位 = 编造需求（实测踩过，回归测试已锁）。
   大类岗位（技术岗/管理岗）由 `title_variants` 去后缀处理，已经覆盖。
9. **同城薪资基线的口径变了要披露**：合并后通用语料里不再有"不带关键词"的行
   （旧 HAR 的 53 条源文件不在包内），基线改用 `jobs_baseline_sample.json`
   （从全量招聘表抽样 2 万条非 AI 岗位）。这是**已被披露的口径替换**，不是静默换数。

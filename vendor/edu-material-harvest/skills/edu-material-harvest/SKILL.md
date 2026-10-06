---
name: edu-material-harvest
description: |
  Harvest publicly available Chinese university materials from official *.edu.cn sources — 培养方案 (curriculum
  plans), 专业介绍 (major introductions), 课程大纲 (course syllabi) and 年度报告 (employment-quality /
  undergraduate-teaching-quality reports) — downloading each file and recording every source URL in a
  traceable ledger (直链 + 承载页).
  Use when the user asks to 采集/下载/补采 某校或某批高校的 培养方案、专业介绍、课程大纲、教学大纲、就业质量报告、教学质量报告,
  or to build/refresh a 高校资料出处台账 for analysis. Works for any *.edu.cn university, not only Beijing 211s.
  Trigger keywords: 高校资料采集, 培养方案, 专业介绍, 课程大纲, 教学大纲, 就业质量报告, 教学质量报告, 本科教学质量, 补采, 出处台账.
  Not for: 学术文献题录（走文献数据库）、竞赛原始数据盘点（走盘点脚本）、需登录才能看的教务系统内材料（本 skill 只采免登录公开源）。
---

# 高校公开资料采集

给定一批院校，从**官方免登录公开源**采集高校的培养方案 / 专业介绍 / 课程大纲 / 年度报告，逐份落盘、逐条登记来源直链与承载页，产出可溯源、可复现的台账。

## 核心原则

**来源可溯源第一。** 每条记录必须同时有**下载直链**与**承载页**（挂链接的那个网页）。死链、纯首页链接、"搜索结果里的摘要"一律不算数。用户的原话：「来源一定要清晰」「链接一定要准确、可以溯源」，这是这个 skill 存在的全部理由。

**下载不是目的，链接台账才是。** 用户后续要做分析，需要能一键跳回官方页面核对。所以**没有文件本体、只有 HTML 页面的**（如不少学校的专业介绍、通识课大纲），**只登记链接、不下载 HTML**；有 PDF 的才下 PDF。

**先侦察、后采集；穷举靠多路并行。** 单个搜索引擎/一次搜索必然漏。先花一轮把"哪些学校有、挂在哪个页、是 PDF 还是 HTML、要不要登录"摸清，再统一下载。侦察用服务端 WebSearch + curl 实测（百度/搜狗 curl 会触发验证码，别用）+ **并行子代理分工**。

**只采官方 `*.edu.cn`，只采免登录。** 登录后才可见的一律放弃（用户明确「不登录，没账号」）。**绝不编造 URL**——给出的每条链接必须实际访问过、确认返回真实内容。

## 工作流程

### Phase 0：准备

1. 明确三件事：**院校名单**、**材料类型**（培养方案 / 专业介绍 / 课程大纲 / 年度报告）、**交付目录**。
2. 交付目录按 `<交付根>\新增数据\<校>\<材料类型>\` 组织；**原始数据目录只读，禁删改移名**。
3. 若本项目之前采过，先读 `references/07-来源清单与模板.md` 看有没有现成来源，别重复侦察。
4. **换新校时第一个动作**：解析该校官方 `*.edu.cn` 域名（WebSearch，**绝不猜**），
   然后跑 `discover.py` 自动发现（见 Phase 1）——别再从零手工摸。

### Phase 1：侦察与枚举（只读，不下载）

**两条入口，按站点情况选。** 判据：全站能爬通、关键词能定位到承载页 → 走 A（一键）；
站内爬不动（子域被 WAF 挡）或爬出来一堆假货（新闻/通知/招生页误命中）→ 走 B（精准）。

**入口 A · 全站自动发现**（省事，适合结构规整的站）：

```bash
python scripts/discover.py --school <校名> --domain <域名>          # 只侦察（默认 dry-run）
python scripts/discover.py --seeds schools_seed.json               # 批量（名单自备）
python scripts/region_seeds.py --province <省> --preset 985        # 地区批量：先生成名单（详见 references/10；名单仅普通高校，成人高校/军校口径见 §3.1）
```

**入口 B · 指定承载页直采**（Agent 定位 + 脚本执行，等价手工 `enum_helpers` 路线）：
**大站的最可靠做法**——把"找承载页"交给会搜索的 Agent，把"枚举附件+实探+落盘"交给脚本，
避免纯站内爬把新闻/招生页的正文措辞误当成材料。

```bash
# 先由上层（你/Agent）用 WebSearch 定位到承载页 URL，再交给脚本：
python scripts/discover.py --school <校名> --domain <域名> \
    --page "<承载页 URL>" --page "<另一个承载页>" --kind 培养方案
# --kind 省略=auto：按页面标题/URL 自动判类；一页一类就分别跑
```

> **为什么要有 B**：`discover.py` 的全站爬只在**站点自身导航把关键词带出来**时才有效；
> 一旦目标材料挂在一个爬不到的子系统（如教务 `jwb`、信息公开 `xxgk` 被 WAF 挡），
> 或站点把关键词塞在新闻列表里导致误命中，A 就会"零命中 / 一堆假货"。
> 这时**不要**让脚本硬爬——先 WebSearch 定位承载页，再 `--page` 交给它枚举。

两条入口都产出 `candidates.md`（人眼确认表，每条带 HTTP/ctype/字节）、`jobs.json`、
`html_links.json`、`unverified.json`、`discover_report.json`。算法、判据与防假货规则见
`references/08-自动发现逻辑.md`。

**真·手工兜底**（连承载页都没有索引、只能靠编号直链）：

1. 按材料类型读对应 reference（见下方"材料类型路由"），拿到该类型的**来源形态**与**枚举手法**。
2. 用 WebSearch + curl 逐校定位承载页与直链；大批量**并行派 3-6 个 `general-purpose` 子代理**，每校实测可达性（HTTP 200 / PDF 魔数 `%PDF`），回传"校名→有/无→类型→实测 URL"。
3. 把候选整理成 **jobs JSON**：`[{school, kind, desc, url, page, ext, pack}]`（`pack=true` 表示 RAR/ZIP 打包件）。
4. **过滤假链**：路径含中文的 `*.pdf` 直链多为页面 JS 数组里的假文件名（见常见陷阱 1）。

### Phase 2：下载（幂等、断点续跑）

用 `scripts/download.py` 跑 jobs JSON：
- 校验魔数 → sha1 与**既有存量 + 批内**去重（重复者回收）→ 按 `<校>/<材料类型>/` 落盘 → 登记 `records.json`。
- RAR/ZIP 打包件先解压再逐个登记（`common.extract_rar`）。
- 重复跑不会重复下载（断点续跑）。

### Phase 3：校验与命名

- 抽查魔数、页数、首页文本；PDF 无文字层的记入"需 OCR"清单。
- 命名：培养方案/专业介绍按 `<年份>_<专业/说明>.pdf`；课程大纲按 `<课程号>_<课程名>.pdf`（课程名取自 PDF 首页首行）。
- 聚合式文件（某学院把整批大纲合成一个 PDF）**不要拆**，按整份登记。

### Phase 4：台账（交付核心）

用 `scripts/report.py` 出 **xlsx（5 张表：总览 / 按院校汇总 / 明细 / 链接台账 / 未成功入库）+ 2 个 CSV（采集清单 / 链接台账）**，列结构见 `references/06-去重与台账.md`。台账必须逐条含：学校 / 材料类型 / 专业或说明 / 年份 / 文件名 / 大小 / **来源直链** / **承载页** / 采集日期。

### Phase 5：收尾

1. 合并写一份 Markdown 汇总说明：补了哪些校、对应哪些材料、来源链接。
2. 临时文件（下载暂存、解压目录）**走回收站**清理。
3. 把新发现的院校来源**回填** `references/07-来源清单与模板.md` 的 B 段模板，下次不用重找。

## 材料类型路由

| 材料类型 | 是什么 | 读哪个 reference |
|---|---|---|
| 培养方案 | 某专业的培养目标+课程体系+学分要求+教学计划进程表 | `references/01-培养方案.md` |
| 专业介绍 | 院校级专业总览/招生类材料（专业目录、设置表、报考指南、招生简章） | `references/02-专业介绍.md` |
| 课程大纲 | **单门课**的大纲本体（教学目标/内容与学时/考核/教材），比培养方案深一层 | `references/03-课程大纲.md` |
| 年度报告 | 就业质量报告、本科教学质量报告、研究生质量报告 | `references/04-年度报告.md` |
| 通用 | 纪律、检索反爬、去重台账 | `00 / 05 / 06` |

## 常见陷阱

1. **页面 JS 数组里的中文文件名 ≠ 直链。** 北理工培养方案页混出 79 条 `.../<中文名>.pdf` 假链，每个卡满超时。**枚举后必须按路径是否非 ASCII 过滤。**
2. **脚本重跑会与自身上一轮记录"自比"。** 补漏脚本若把本脚本上轮写入的 sha 一起建 `got_sha`，会全判"已下"→ `added` 为空 → 该校记录被清空。**解法：开头先 `res=[r for r in res if r["school"]!=本校]` 再建去重集。**
3. **大量文件下到一半卡死。** 高校附件服务器会中途停传（农大 `downfile.jsp` 停在 5MB/12.5MB）。curl 必须加 `--speed-time 30 --speed-limit 20480`（<20KB/s 持续 30 秒即中止）。**重下前必须回收旧半截文件**——只查文件头（`%PDF`）会把半截当完整而跳过。
4. **标题/文件名写"培养方案"≠培养方案本体。** 中传"数字经济专业2025"实为辅修招生简章（含课程设置表）→ 按口径归**专业介绍**。**判类型要读全文，别信标题。**
5. **"课程大纲"常常是纯 HTML 正文页、没有附件。** 民大通识核心课大纲即如此 → **只登记链接，不下载**。
6. **每校只扫一次目录。** 若在 job 循环里"对每个 job 扫整个输出目录"，会平方级重复计数（北工大 42 个 job × 42 个文件 = 1764）。按学校聚合、按文件名匹配来源。
7. **回收站删除**：统一用 `common.recycle()`（PowerShell `SendToRecycleBin`）；无 PowerShell 时降级为隔离到临时目录并 WARN，**绝不静默 no-op**，禁用 `rm`/`os.remove`。
8. **控制台中文乱码**：Windows 终端 GBK → `common.py` 导入时已自动 `sys.stdout.reconfigure(utf-8)`；自建脚本用 `reconfigure`（别用 `io.TextIOWrapper`，重复包裹会让底层缓冲被 GC 关闭）。
9. **RAR 解压**：解压器由 `scripts/env.py` **自动探测**（`7z`/`7za`/`bz`/`unrar`，或 `EDU_7Z` 覆盖），**别写死路径、别装新软件**。缺失抛 `DepError`，`download.py` 记「缺解压器」后**继续后续项**（不整批中止）。
10. **假货分两种，都要防。** ①**链接假**：路径含中文的 `*.pdf`（陷阱 1）；②**类型假**——页面/附件**本身是真的、类型判错**：新闻页正文写了"我校发布培养方案"，页内所有附件就被整片**继承**成培养方案；招生网 `newsCenter/article` 里的"招生简章"被当成专业介绍。`discover.py` 已内置三重防线：**栏目黑名单**（新闻/通知/科研公开/党建/招生宣传路径整页丢弃）、**弱信号降级**（仅 URL 碰巧含词不算材料，须锚文本或标题强命中）、**逐页重判**（HTML 材料页按自身标题判类，不整列继承；首页/栏目根一律不当材料）。**判据永远是"这一页/这一条自身"是不是材料，不是它挂在哪。**

## 设计教训（来自实战踩坑）

### 教训 1：先侦察再采集，别边搜边下

培养方案补采时第一批"边搜边下"，下到的 11 条里有 9 条 sha1 与已有完全相同、2 条 URL 失效指向错文件——白下。先花一轮侦察确认"该校到底有没有、挂在哪、是不是真文件"，再统一下载，命中率才高。

### 教训 2：口径要读全文，别信标题

把"辅修招生简章"当培养方案、把"模板/规范"当大纲收进来的错，都源于信了标题。**判类型读全文。**

### 教训 3：链接台账和文件同等重要

用户要的是"AI 能直接点击跳转"的页面级链接。有 PDF 的下 PDF，纯 HTML 的登记链接——两条腿走路，别只做一条。

### 教训 4：全站爬不动的站，靠"Agent 定位 + 脚本枚举"，别硬爬

北理工测试：全站爬 **0 真料 + 26 条假货**（新闻页措辞被当材料、招生简章被当专业介绍）；而人工"定位承载页 → 枚举"拿到 **96 份真培养方案**。差在**找页**这一步——搜索是 Agent 的强项，站内爬不是。于是 `discover.py` 加了 `--page` 入口：**Agent 用 WebSearch 定位承载页 URL，脚本只负责枚举附件 + 实探确认 + 落盘**。纯站内爬永远可能被"关键词出现在错误语境"骗到；把定位交给会搜索的 Agent，才能同时要**准**和**全**。

## MCP 接入（跨 Agent：Claude Code / Codex / WorkBuddy / 千问办公）

本 skill 的采集内核可经 **MCP** 暴露，让任何支持 MCP 的客户端都用同一套能力——**内核不改，MCP 只透传**。

```bash
python scripts/env.py                       # 先看本机依赖（也可用 MCP 的 env_check 工具）
python scripts/mcp_server.py                # 以 stdio 起 MCP 服务端（客户端来调）
python scripts/mcp_server.py --print-config # 打印可粘贴的客户端连接信息（Python 绝对路径版）
python scripts/mcp_server.py --install claude   # 一键写 Claude Code 配置（或 codex）
```

- **工具**：`env_check` / `region_seeds`（地区名单）/ `harvest_school`（一键）/ `harvest_many`（批量多校）/
  `harvest_pages`（承载页直采）/ `discover_school` / `discover_pages_dry` / `download_materials` /
  `build_ledger` / `read_artifacts` / `job_status` / `job_wait`。
  长任务**异步**：工具立即回 `job_id`，用 `job_wait` 等终态摘要；`env_check`/`region_seeds`/`build_ledger` 等**同步**即返。
- **Resources/Prompts**：把手册（`edu://manual`、`edu://ref/*`）与"照念即用的调用配方"
  直接投喂给**模型更弱**的通用 Agent。
- **DeepSeek Harness（DSH）**：DSH 里 skill 与 plugin 是两套——skill 靠**目录发现**（拷进
  `~/.dsh/skills/`，不能用「添加插件」装），plugin 才走「添加插件」（仓库根已带 DSH bundle
  三件套：`package.json` + `cordis.patch.yml` + `lib/index.js`）。DSH 只桥 MCP 的 **tools**、
  不认 resources/prompts（边界文字已内嵌在 `region_seeds` 工具输出）。见 `references/11-DeepSeek-Harness接入.md`。
- 技术/逻辑/思路（含 stdout 屏蔽的承重设计、后台任务模型、四个客户端的接入法）：
  见 `references/09-Agent接入与MCP.md`。

## 文件结构

```
edu-material-harvest-高校公开资料采集（自己创作）/
├── SKILL.md
├── README-安装与接入.md          # 前置/依赖/安装 drop-in/接入新校三步/故障对照表/客户端接入
├── 使用教程_高校公开资料采集.docx
├── .claude-plugin/               # 附形态：plugin.json + marketplace.json（分发为插件时用，见 README 六）
├── references/
│   ├── 00-通用纪律.md            # 只采官方源·免登录·回收站·编码·原始数据只读
│   ├── 01-培养方案.md
│   ├── 02-专业介绍.md
│   ├── 03-课程大纲.md
│   ├── 04-年度报告.md
│   ├── 05-检索与反爬.md
│   ├── 06-去重与台账.md
│   ├── 07-来源清单与模板.md      # 示例表 + 空白模板 + 新增一校四步 + 省级线索
│   ├── 08-自动发现逻辑.md        # discover.py 的设计思路、判据、边界（"逻辑与技术"）
│   ├── 09-Agent接入与MCP.md      # 跨 Agent 接入与 MCP：架构/协议/工具/排障（"怎么让别的 Agent 也用"）
│   ├── 10-地区批量.md            # 省份/985·211 → 逐校：三层职责 + 两路域名 + 溯源 schema
│   ├── 11-DeepSeek-Harness接入.md # DSH：skill vs plugin 两套装法 + MCP（只桥 tools）
│   ├── data/                     # 地区批量数据：univ_list_2026-06-17.json + 985.json + 211.json
│   └── schools_seed.example.json # 批量种子模板（复制成 schools_seed.json）
└── scripts/
    ├── env.py                      # 外部工具唯一解析入口（7z/curl/powershell + 库探测）
    ├── common.py                   # 通用：下载/回收站/sha1/魔数/命名/编码/RAR（经 env）
    ├── region_seeds.py             # 地区名单生成器（①层：省/城市/层次/985·211 → seeds，确定性、零依赖）
    ├── discover.py                 # 【核心】全自动发现：域名→子域→爬→枚举→实探确认→jobs
    ├── download.py                 # jobs.json → 下载+解压+去重 → records.json（幂等）
    ├── enum_helpers.py             # 抽页面链接 / 链式爬取 / 二级解析
    ├── report.py                   # records.json → xlsx(5表) + 2 CSV 台账
    ├── mcp_server.py               # 【跨 Agent】零依赖 stdio MCP 服务端（透传内核 + 后台任务）
    ├── generate_tutorial.py        # 生成使用教程 docx
    ├── requirements.txt            # pymupdf / openpyxl / python-docx（各注降级行为）
    └── selftest.py                 # 自检（改动后跑一遍，全 PASS 才算无回退）
```

> **仓库根另含**：`.mcp.json`（Claude Code 插件形态声明内置 MCP 服务端，`${CLAUDE_PLUGIN_ROOT}` 展开，
> `/plugin install` 时自动挂载）、`.claude-plugin/`、`.codex-plugin/` + `.agents/plugins/`（Codex 插件形态），
> 以及 **DSH bundle 三件套** `package.json` + `cordis.patch.yml` + `lib/index.js`（DeepSeek Harness 插件形态，见 `references/11`）。

> **全自动闭环**：`python scripts/discover.py --school <校> --domain <d> --auto`
> （发现 → 下载 → 台账一条龙）。只侦察去掉 `--auto`；**指定承载页直采**加 `--page <URL>`（可重复）+ 可选 `--kind`。
> **手工链**：`enum_helpers.py <栏目页>`（侦察）→ jobs.json → `download.py` → `report.py`。
> **跨 Agent（MCP）**：`python scripts/mcp_server.py`（stdio 服务端）；
> `--print-config` 出连接信息；`--install claude|codex` 一键接入。见 `references/09`。
> **DeepSeek Harness**：拷进 `~/.dsh/skills/`（skill 形态，热重载）或在「添加插件」填本仓库（GitHub bundle 形态）。见 `references/11`。
> **诊断**：`python scripts/env.py` 打印本机工具/库探测结果。
> **自检**：`python scripts/selftest.py`（全 PASS 才算改动无回退）。

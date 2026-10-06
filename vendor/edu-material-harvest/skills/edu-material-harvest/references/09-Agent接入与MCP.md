# 09 · 跨 Agent 接入与 MCP（技术 / 逻辑 / 思路）

本文件回答一个问题：**同一套采集能力，怎么让不同厂商的 Agent 都用起来，而且用对。**

采集内核（`scripts/discover.py`、`download.py`、`report.py`）是纯 Python + curl，
谁都跑得动；但**原包装只有 `SKILL.md`，只有 Claude Code 认**。要在 Codex / WorkBuddy /
千问办公里也用，就得加一层所有客户端都认的**共同分母**——MCP。

---

## 0. 一句话总纲

> **MCP 只做透传，不改内核。** 采集质量由引擎决定（与手跑北京高校那批数据同一口径）；
> MCP 层负责：把引擎包成"粗粒度工具"、把长任务变成"后台任务 + 轮询"、
> 把判断逻辑沉到代码、把操作步骤写死成 prompt 喂给弱模型。

三条硬要求与之对应：

| 要求 | 落点 |
|---|---|
| 效果要和手跑差不多 | 内核不动；A（全站）/B（承载页）两条入口都保留 |
| 通用 Agent 模型弱，要赋能它 | 粗粒度一键工具 + 丰富工具描述 + Resources/Prompts 直接投喂 |
| 技术/逻辑/思路写清楚 | 就是本文 |

---

## 1. 架构：谁负责什么

```
┌──────────────────────────────────────────────────────────────┐
│  客户端模型（Claude Code / Codex / WorkBuddy / 千问办公）        │
│  · 会联网搜索 → 定位「挂着材料的那一页」（承载页）              │
│  · 决定采哪所学校、哪类材料（范围由人/模型定）                  │
└───────────────▲───────────────────────────┬──────────────────┘
                │ MCP（stdio + NDJSON）        │ 工具结果 / 产物
┌───────────────┴───────────────────────────▼──────────────────┐
│  scripts/mcp_server.py  （本层，零依赖）                        │
│  · 协议解析（JSON-RPC 子集）  · 工具编排  · 后台任务/轮询       │
│  · stdout 屏蔽         · Resources/Prompts 投喂                │
└───────────────┬───────────────────────────────────────────────┘
                │ 同进程直接函数调用（不经 shell、不经子进程 stdout）
┌───────────────▼───────────────────────────────────────────────┐
│  采集内核：discover.py（发现+防假货） → download.py（下载去重）  │
│            → report.py（台账）                                  │
└───────────────────────────────────────────────────────────────┘
```

**关键分工（与 SKILL 教训 4 一致）：**

- **「找承载页」不放进 server。** 那是**联网搜索**的活，是客户端模型的强项。
  纯站内爬会被"关键词出现在新闻/招生语境"骗到；让会搜索的模型先定位承载页，
  server 只负责**枚举附件 + 实探确认 + 落盘台账**。
- **server 不做任何"判断材料类型"的新逻辑**——判据全在 `discover.py`（见 `08`）。
  server 只透传，保证"用 MCP 采"与"手跑脚本采"产出**同一套台账**。

---

## 2. 传输与协议子集

- **传输**：`stdio`。**NDJSON**——每行一条 JSON-RPC 2.0 消息，**不用 `Content-Length` 头**。
- **协议版本**：支持 `2025-06-18` 与 `2024-11-05`；`initialize` 回协商后的版本。
- **方法**（实现子集）：

| 方法 | 作用 | 备注 |
|---|---|---|
| `initialize` | 握手、能力/版本协商 | 回 `tools`/`resources`/`prompts` 能力 |
| `notifications/initialized` | 客户端就绪通知 | **不回**（通知无 id） |
| `ping` | 存活探测 | 回 `{}` |
| `tools/list` / `tools/call` | 列工具 / 调工具 | 主力 |
| `resources/list` / `resources/read` | 列/读上下文资源 | 投喂手册 |
| `prompts/list` / `prompts/get` | 列/取提示词配方 | 投喂步骤 |

- **错误码**：`-32700`（JSON 解析）/`-32601`（未知方法）/`-32602`（参数错）/
  `-32603`（内部错）/`-32000`（其它）。
- **纪律：工具的业务失败不抛 JSON-RPC error。** 缺 curl、缺 openpyxl、目录里没文件
  这类，一律返回 `{content:[{type:"text"}], isError:true}`，把**可读原因 + 安装提示**
  写进文本。这样弱模型能"读着话自己补救"，而不是只看到一个冷冰冰的 error code。

---

## 3. stdout 屏蔽 —— 承重设计（最容易踩死的地方）

**问题**：本仓库的代码**大量往 stdout 写**：

- `common.py` / `env.py` **在 import 时**就 `sys.stdout.reconfigure(...)`；
- 所有长任务默认 `log=print`（写 stdout）；
- `discover.step6_auto` 还会 `sys.stdout.write(子进程输出)`。

**一旦这些写进 stdout，就毁掉 JSON-RPC 流**，客户端直接解析崩溃。

**解法**（顺序不能变）：在 `mcp_server.py` **最顶部、任何 repo import 之前**：

1. `real = os.dup(1)` —— 保存**真 stdout** 的 fd。
2. `os.dup2(os.devnull, 1)` —— 此后 fd1 指向 **/dev/null**；任何 `print`、
   C 层 `printf`、子进程继承 fd1 的杂散输出**直接丢弃**。**为什么是 devnull 而不是
   stderr**：devnull 永不写满，故客户端即使把 stdout/stderr 开成 PIPE 又**不排空**，
   也不会因写满管道把服务端阻塞死（对任意客户端都安全）。
   （本地排障设 `EDU_MCP_LOG=1`，此时改指 stderr，杂散输出与日志都看得见。）
3. 把 `sys.stdout` 重绑到 fd1 —— 此后再 `reconfigure`/`print` 只作用于
   "已指向 devnull（或 stderr）"的流，无害。
4. 协议出口：`proto = os.fdopen(real, "wb")`，每条消息写一行 UTF-8 NDJSON 并 `flush()`。
5. 子进程一律 `capture_output=True`；若将来有子进程读 stdin，须显式 `stdin=DEVNULL`。

**承重的两个推论：**

- **MCP 工具不走 `step6_auto`**（它会 `sys.stdout.write` 子进程输出）。
  改为直接调 `download.run(...)` + `report.build_ledger/写 CSV/写 xlsx`，
  并把 `log` 收进**任务环形缓冲**——日志因此也能被 `job_status` 回看。
- **自检用"首行断言"兜住**：`selftest.py` 起 server 后，断言
  **stdout 第一行就是 `initialize` 结果**（`mcp_first_line_is_initialize`）。
  只要有人在屏蔽之前 `print` 了一句，这条立刻红。

---

## 4. 工具表（粗粒度给弱模型，细粒度留给强客户端）

| 工具 | 入参 | 返回 | 说明 |
|---|---|---|---|
| `env_check` | — | 依赖探测表 | 只读，**第一个该调的**；缺依赖当场说清 |
| `region_seeds` | `province?, city?, level?, preset?, names_file?, domains?, data?, csv?, out?` | 文本 + `structured` | 同步；**地区批量第一步**：省/985·211 或自定义名单 → `seeds.json`（纯本地、不联网、不猜域名）。输出内嵌**名单口径边界**与「待补域名」清单 |
| `harvest_school` | `school, domain, kinds?, auto?, no_subdomains?, max_pages?, workers?, out?` | `job_id` | **一键**：发现→(auto)下载→台账。= 官方推荐整跑 |
| `harvest_many` | `schools:[{school,domain,kinds?},…], kinds?, auto?, …` | `job_id` | **批量多校**：逐校发现→(auto)下载→台账，各校产出到 `<out>/<校名>/` |
| `harvest_pages` | `school, domain, pages:[{url,kind?}], auto?, out?` | `job_id` | **承载页直采**（WAF 挡/假货多时用） |
| `discover_school` | 同 `harvest_school`，强制只侦察 | `job_id` | 只侦察 |
| `discover_pages_dry` | 同 `harvest_pages`，强制只侦察 | `job_id` | 只侦察 |
| `download_materials` | `out, exclude_school?, existing_sha?, resume?, csv_only?` | `job_id` | 读 `out/jobs.json` → 下载 |
| `build_ledger` | `out, csv_only?, date?` | 文本 | 同步；重新出台账 |
| `read_artifacts` | `out, which` | 文本/JSON | 同步；让 Agent"看见"结果，不必开 shell |
| `job_status` | `job_id` | 状态+日志尾 | 非阻塞轮询 |
| `job_wait` | `job_id, timeout_s` | 终态摘要 | **给不会循环的弱模型** |

设计取舍：

- **`region_seeds` 是同步快工具**（纯本地、毫秒级，不返 `job_id`）：它是**唯一**把「名单口径边界」
  写进**工具输出**的地方——供**只认 tools、不读 resources** 的客户端也能拿到边界与配方
  （配 `edu://ref/10` 双保险）。
- **一键工具（`harvest_*`）是给弱模型的主路径**——少决策、少出错。
- **所有 `harvest_*` / `discover_*` / `download_materials` 都是异步的**，立即回 `job_id`；
  摘要经 `job_wait` 取。这样无论站点多慢，客户端都不会因超时把任务掐断。
- **细粒度工具**（`discover_school` + `build_ledger` + `read_artifacts`）留给会编排的强客户端做"先侦察、人工过目、再下载"。

---

## 5. 后台任务模型（长任务不被掐断）

**为什么**：全站爬几分钟是常态，MCP 客户端调用通常有超时。同步返回必被掐。

**结构**：

- `threading.Thread` 跑任务；`job_id → {state, log 环形缓冲(800 行), result, error}`
  存于 `threading.Lock` 保护的表。
- `state ∈ queued → running → done | error`。
- **同一 `out` 目录串行**（`_out_lock`）：避免 `_discover_tmp` / `jobs.json` /
  `records.json` 竞争。并发的两个任务写同一个 `out` 会排队，而不是互相踩。
- 日志**只进环形缓冲**（供 `job_status`/`job_wait` 回看）。**默认不写 stderr**——
  若客户端把 stderr 开成 PIPE 却不排空，持续写会写满管道、把任务线程阻塞死；
  为对所有客户端都安全，默认静默。本地排障要实时日志时设 `EDU_MCP_LOG=1`
  （此时杂散输出转 stderr、日志同步 stderr）。
- **已完成的旧任务会按上限淘汰**（`_JOBS_KEEP=200`），运行中的不动；对应的
  `_out_lock` 在无存活任务引用时一并回收 —— 长命服务端不会无限增长。

**弱模型照念的三步**（prompt 里也写了）：

```
1) harvest_school {school, domain}            → 得到 job_id
2) job_wait {job_id, timeout_s: 600}          → 等到跑完，拿摘要
3) read_artifacts {out, which: "candidates"}  → 看人眼确认表，向用户汇报
```

---

## 6. Resources / Prompts —— 赋能弱模型的核心杠杆

弱模型**不会自己记住规则**。把它们**塞进客户端上下文**才靠谱：

- **Resources**（`resources/list` 可被客户端自动加载）：
  `edu://manual`（SKILL.md）、`edu://ref/00`（纪律）、`edu://ref/05`（检索反爬）、
  `edu://ref/07`（来源清单）、`edu://ref/08`（引擎逻辑）、`edu://ref/01..04`（四类材料）、
  `edu://ref/09`（本文）、`edu://ref/10`（地区批量 + 名单口径边界）。
- **Prompt `edu:harvest-school`**：入参 `{school, domain, kinds?}`，直接返回**有序调用配方**
  （"先 env_check → harvest_school/harvest_pages → job_wait → read_artifacts('candidates'）"）。
  弱模型照念即可，不必理解引擎。

> 原则：**把"判断"沉到代码，把"步骤"写死成 prompt。** 代码负责正确，prompt 负责顺序。

---

## 7. 两条入口怎么映射（沿用 SKILL Phase 1 的判据）

| 情形 | 用哪个工具 |
|---|---|
| 站点导航规整、全站能爬通 | **A**：`harvest_school` / `discover_school` |
| 子域被 WAF 挡（零命中）；或爬出一堆假货（新闻/通知/招生页误命中） | **B**：`harvest_pages` / `discover_pages_dry` |

走 B 时，**承载页 URL 由客户端模型联网搜出来**（例："XX大学 培养方案"），再传给 server。
这正是本 skill 实战里最靠谱的做法——**"找页"交给会搜索的模型，"枚举+下载+台账"交给脚本**。
两条入口共用 `_finalize()`，**产出同一套 `candidates.md` / `jobs.json` / `records.json` / 台账**。

---

## 8. 客户端接入（四个）

先拿到本机连接信息（绝对路径版，最稳）：

```bash
python scripts/mcp_server.py --print-config
```

它输出 `command`（Python 解释器绝对路径）与 `args`（`mcp_server.py` 绝对路径），
以及一段可粘贴的 `mcpServers` JSON。

### Claude Code
```bash
python scripts/mcp_server.py --install claude
# 等价于：claude mcp add -s user edu-material-harvest -- <python> <mcp_server.py>
claude mcp list        # 看到 edu-material-harvest 即成功
```

### Codex
```bash
python scripts/mcp_server.py --install codex
# 等价于：codex mcp add edu-material-harvest -- <python> <mcp_server.py>
codex mcp get edu-material-harvest   # 一律以此为准（Codex 读两份 config.toml，别只看文件）
```

### WorkBuddy
在 **「连接器（MCP）」** 里新建一个 stdio 服务器，`命令 / 参数` 填 `--print-config`
给出的 `command` / `args`。

### 千问办公（QwenWork）
桌面端左侧「**扩展 → 连接器**」→ 右上「**+ 添加**」，两个选项任选：
「**填写/粘贴 JSON 配置**」贴上 `--print-config` 给的 `mcpServers` JSON；
或「**手动添加配置**」，服务器类型选 **STDIO**，填 `command` / `args`。**添加后须新建任务才生效**——老对话不会自动拿到新工具；
验证看「**连接器 → 已安装 → 自定义**」：开关打开 **≠** 连上，要能展开出工具列表才算真挂上。

> ⚠️ **Python 路径坑**：`command` 要么是 PATH 里的 `python`，要么是**绝对路径**。
> 客户端通常不继承你终端的 PATH——**最稳是直接用 `--print-config` 的绝对路径**。

### 插件形态（Claude Code 专属，自动挂载）
本仓库根放了 `.mcp.json`（`${CLAUDE_PLUGIN_ROOT}` 展开）。走
`/plugin install` 装插件时，**MCP 会自动挂上**，无需手动 `mcp add`。
（`SKILL.md` 本身不能声明 MCP——MCP 是**插件级**的，只能在仓库根 `.mcp.json` 或
`.claude-plugin/plugin.json` 里声明。）

---

## 9. 排障对照表

| 现象 | 原因 | 解决 |
|---|---|---|
| 客户端里工具列表为空 | `command` 路径错 / Python 不在 PATH | 用 `--print-config` 的**绝对路径**重填 |
| 客户端报"无效 JSON / 连接断开" | stdout 被污染（屏蔽顺序被破坏） | 不要在 `mcp_server.py` 里"先 import repo 再屏蔽"；屏蔽必须最先 |
| 工具返回 `isError` 说缺 curl/openpyxl | 本机缺依赖 | 先 `env_check`；装依赖，或 `csv_only=true` 只出 CSV |
| 任务一直 `running` | 站点慢 / 被 WAF 拖 | `job_status` 看日志尾；必要时改走承载页直采 |
| 同 `out` 起两个任务 | 串行锁排队（**设计如此**） | 换不同 `out` 可并行 |
| 采到"看起来不像材料"的页 | 关键词出现在错误语境 | 改 `harvest_pages` 指定真承载页（引擎已内置栏目黑名单兜底） |
| 结果很多 `blocked` | 站点有 WAF / JS 挑战 | **真实边界**，非 bug；换承载页或子域 |

---

## 10. 红线与边界

1. **内核不因 MCP 改动**：判据、防假货、实探口径全在 `discover.py`；MCP 只透传。
2. **零依赖**：只用标准库实现协议子集——**用户不必 `pip install`**（这正是选它而非官方
   `mcp` SDK 的理由：绕开装包，降低上手门槛）。
3. **server 不做联网搜索**：定位承载页是客户端模型的活。
4. 沿用内核红线：**不跨 apex、不猜域名、只采官方免登录 `*.edu.cn`**。
5. **范围由人定**：全自动只授权"怎么跑"，不授权"跑什么"（换校/换材料类型须点名）。
6. 边界：WorkBuddy / 千问办公的**真机入口以各自 UI 为准**；本文给的是通用连接信息。

---

## 11. 代码索引

- `scripts/mcp_server.py`
  - stdout 屏蔽块（文件顶部，任何 import 之前）
  - `_send / _result / _error`（协议出口）
  - `_start_job / _job_wait / _out_lock`（任务模型）
  - `_download_and_ledger`（不走 `step6_auto` 的下载+台账）
  - `TOOLS / TOOL_FUNCS / _RESOURCES / _PROMPTS`（工具/资源/提示词表）
  - `_dispatch`（协议分发）、`serve`（stdio 主循环）
  - `print_config / install`（客户端自助接入）
- `scripts/selftest.py`：`mcp_*` 断言段（离线起 server、握手、断言行级纯净）
- 引擎逻辑（判据 / 三重防线 / 边界）：见 `08-自动发现逻辑.md`

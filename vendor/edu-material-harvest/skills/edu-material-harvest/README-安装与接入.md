# 安装与接入 · 高校公开资料采集

把本 skill 装进**你自己的 Claude Code**，然后用它采集**任何一所** `*.edu.cn` 高校的
培养方案 / 专业介绍 / 课程大纲 / 年度报告，逐份落盘并登记可溯源台账。

> 不需要编程。你只需要会：把文件夹放进指定位置、照着命令敲、看输出。

---

## 一、它做什么

给定 `{学校名, 官方域名}`，一条命令：

1. **自动发现**：摸清该校材料挂在哪些栏目页、附件直链是什么（每条都实探过 HTTP / 内容类型 / 文件头）；
2. **下载 + 校验 + 去重**：只下真文件，重复的剔除，按「学校 / 材料类型」分目录存好；
3. **出台账**：Excel（逐文件明细 + 页面级链接台账）+ CSV，每行含**下载直链**与**承载页**。

你后续做分析时，能一键跳回学校官网核对原文。

**两种发现方式**（都产出同一套台账）：

- **全站自动爬**（省事）：给个域名，脚本自己爬遍主站和子域找材料。适合导航规整的站。
- **指定承载页直采**（精准）：**先让 Claude 用联网搜索定位到"挂着材料的那一页"**，
  再把那一页的网址交给脚本去枚举、下载。适合大站、或"全站爬出来一堆不是材料的页"的情况
  （详见第四节第 2′ 步）。

---

## 二、前置条件

| 需要 | 说明 | 没有会怎样 |
|---|---|---|
| **Claude Code** | 本 skill 跑在它里面 | —— |
| **Python 3.9+** | 建议 3.10+；本 skill 在 3.12 上跑通 | 脚本跑不了 |
| **curl** | Windows 10 1803+ **自带** | 无法下载/探测（会报 `缺少依赖：curl`） |
| **解压器**（可选） | 7-Zip 或 Bandizip（命令行）；采 RAR/ZIP 打包件时才需要 | 打包件那几项记「缺解压器」并跳过，其余照常 |
| **PowerShell**（可选） | Windows 自带；用于"删到回收站" | 删除降级为"隔离到临时目录"（文件不丢） |

**外部工具全部自动探测**（PATH → 常见安装位置），也可用环境变量覆盖：
`EDU_7Z` / `EDU_CURL` / `EDU_POWERSHELL`。

**Python 库**（建议装进你的项目 venv）：

```bash
python -m pip install -r scripts/requirements.txt
```

| 库 | 用途 | 缺失行为 |
|---|---|---|
| `pymupdf` | PDF 取词（课程名/专业名命名） | 文件名退化为通用名（打 WARN，不崩） |
| `openpyxl` | 生成 Excel 台账（**核心产物**） | **报错退出**；或 `report.py --csv-only` 降级只出 CSV |
| `python-docx` | 生成使用教程 docx | 报错退出（仅在跑 `generate_tutorial.py` 时） |

> 缺依赖本 skill **要吵不要哑**：不会静默降级到"看起来成功"。

---

## 三、安装（drop-in，零配置）

**主形态 = 扁平文件夹**。整目录丢进 Claude Code 的 skills 目录即可：

```bash
# 把整个 edu-material-harvest-高校公开资料采集（自己创作） 文件夹复制到：
<你的 CLAUDE_CONFIG_DIR>/skills/
```

- 默认 skills 目录一般是 `~/.claude/skills/`。
- 若你设过环境变量 `CLAUDE_CONFIG_DIR`（本机就是），skills 目录在
  **`<CLAUDE_CONFIG_DIR>/skills/`**——照着放即可。
- 放好后**新开一个 Claude Code 会话**，说「帮我采集 XX 大学的培养方案」即触发。

> 为什么是"扁平文件夹"而不是"插件"？因为 Claude Code **不支持嵌套 SKILL.md**——
> `SKILL.md` 必须在本文件夹根目录。整文件夹既可直接 drop-in，也可作为 npm/plugin 的一部分
> （见第六节），**同一份文件两种用法**。

---

## 四、接入新学校：三步

以"湖南大学"为例（换成你的学校，域名换成实测的）：

### 第 1 步 · 解析域名（关键，别猜）

用 WebSearch 搜 `"<校名> 教务处"` 或 `"<校名> 信息公开"`，**确认官方 `*.edu.cn` 域名**。
- 认准 `edu.cn` 后缀；别把独立学院 / 分校 / 培训机构当主校。
- 教务子域不一定是 `jwc.`（有的校是 `jw.`）。

### 第 2 步 · 只侦察（默认，不下载）

```bash
python scripts/discover.py --school 湖南大学 --domain hnu.edu.cn
```

产出在 `discover_out/`：

| 文件 | 看什么 |
|---|---|
| `candidates.md` | **人眼确认表**：命中的栏目页、确认的附件（带 HTTP/ctype/字节）、被拦的页 |
| `jobs.json` | 确认可下载的清单（喂给 download.py） |
| `html_links.json` | 纯 HTML 材料页（只登记，不下载） |
| `unverified.json` | 没通过探测的候选（不自动下载） |
| `discover_report.json` | 过程统计（可达主机、扫描页数、拦截数、耗时） |

### 第 3 步 · 拍板 + 采集

看完 `candidates.md` 没问题后，一键下载 + 出台账：

```bash
python scripts/discover.py --school 湖南大学 --domain hnu.edu.cn --kinds 年度报告 --auto
```

得到 `<out>/新增数据/湖南大学/年度报告/*.pdf` 与 `<out>/采集台账.xlsx`。
**再跑一遍是幂等的**（已存在即跳过，不重复下载、不丢记录）。

### 第 2′ 步（当第 2 步"零命中 / 一堆假货"时）· 指定承载页直采

若第 2 步的结果是**什么都命中不到**（目标材料挂在被 WAF 挡的教务/信息公开子系统上），
或者**命中的都不是材料**（爬到的是新闻页、招生简章），这时**别让脚本硬爬**，改走这条：

**先让 Claude 联网搜索，找到"挂着材料的那一页"**（承载页），例如：
「北京理工大学 培养方案」「XX 大学 就业质量年度报告」。确认那页网址后，交给脚本：

```bash
python scripts/discover.py --school 湖南大学 --domain hnu.edu.cn \
    --page "<承载页网址>" --kind 培养方案
# --kind 省略=auto（脚本按页面标题自动判断材料类型）
# --page 可以写多个、重复写，一次枚举多页
```

看 `candidates.md` 拍板后同样加 `--auto` 一键下载出台账：

```bash
python scripts/discover.py --school 湖南大学 --domain hnu.edu.cn \
    --page "<承载页网址>" --kind 培养方案 --auto
```

> 这条路线正是本 skill 实战里最靠谱的做法：**"找页"交给会搜索的 Claude，"枚举+下载+台账"
> 交给脚本**。纯靠脚本瞎爬，容易被"关键词出现在新闻/招生语境里"骗到。

> 批量：把学校写进 `references/schools_seed.example.json`（复制成 `schools_seed.json`），
> 然后 `python scripts/discover.py --seeds schools_seed.json`。

---

## 五、故障对照表

| 现象 | 原因 | 解决 |
|---|---|---|
| `缺少依赖：curl` | 无 curl | Windows 装 curl 或设 `EDU_CURL` 指向可执行文件 |
| `缺少依赖：解压器…` | 无 7z/Bandizip | 采打包件才需要；装 7-Zip 或设 `EDU_7Z`。不影响其余项 |
| 报错 `未安装 openpyxl…` | 缺 Excel 库 | `pip install openpyxl`，或加 `--csv-only` 只出 CSV |
| 域名被拒 `不是 *.edu.cn` | 传了非 edu 域名 | 核对域名，必须是官方教育域名 |
| `apex、www 及已知子域均不可达` | 域名错 / 网络到不了 | 核对官方域名；`--no-subdomains` 试试；换网络 |
| 结果里很多 `blocked` | 站点有 WAF / JS 挑战 | **真实边界**，不是 bug；换子域或手动补 |
| `candidates.md` 里某些行没确认 | 返回 HTML 或状态异常 | 正常——它们只登记不下载；确认真文件才下 |
| **一个材料都没命中** | 目标栏目的子域被 WAF 挡，爬不到 | 改走第四节**第 2′ 步**：先搜索定位承载页，再 `--page` 直采 |
| **命中的一堆都不是材料**（新闻页、招生简章） | 关键词出现在错误语境的页面上 | 同上——用 `--page` 指定真承载页；引擎已内置栏目黑名单，但指定页更稳 |
| 下载中途卡死 | 高校附件服务器中途停传 | curl 已带 `--speed-time 30 --speed-limit 20480` 自动中止 |
| 中文输出乱码 | Windows GBK 终端 | `common.py` 已自动 utf-8；自建脚本用 `sys.stdout.reconfigure` |
| 重复跑没新增 | 幂等生效 | 正常；已存在即跳过 |
| MCP：客户端里工具列表为空 | `command` 路径错 / Python 不在 PATH | 用 `--print-config` 的**绝对路径**重填 |
| MCP：客户端报"无效 JSON/断开" | 服务端 stdout 被污染 | 见 `references/09` §3，屏蔽顺序须最先 |

---

## 六、分发形态（可选）

**主形态（推荐）**：整文件夹丢进 `skills/`，如上。

**附形态（插件 marketplace）**：本文件夹自带 `.claude-plugin/plugin.json` 与
`.claude-plugin/marketplace.json`（**可直接抄用**）。但插件对目录层级有硬要求：
`SKILL.md` 必须在 `<插件仓库根>/skills/<名>/SKILL.md`，而 `.claude-plugin/` 必须在**仓库根**。

所以发布成插件的正确布局是：

```
<插件仓库根>/                     ← 一个 git 仓库
├── .claude-plugin/
│   ├── plugin.json              ← 本文件夹 .claude-plugin/ 里的两个文件
│   └── marketplace.json         ← 复制到仓库根
└── skills/
    └── edu-material-harvest/    ← 把本 skill 文件夹整个放这里（可改名，但 plugin.json 的 name 要对上）
        ├── SKILL.md
        └── ...
```

然后他人：

```
/plugin marketplace add <git-url 或本地路径>
/plugin install edu-material-harvest@edu-material-harvest
```

> ⚠️ 两点：
> 1. 插件**必须经 marketplace 分发**，不能凭空下载——需要你把仓库托管到 Git（GitHub 等）或给出本地路径。
> 2. 本文件夹的 `.claude-plugin/` 是**给仓库根用的模板**；放在 skill 文件夹里只是"随包携带"，不影响
>    drop-in 使用（drop-in 形态不读它）。
> 3. 插件形态与 drop-in 形态**父目录不同、子目录相同**（都是 `skills/<名>/SKILL.md`），
>    同一份 `SKILL.md` 与 `scripts/` 直接复用，无需改动。

---

## 七、在别的 Agent 里用（MCP）

不只 Claude Code 能用。本 skill 带一个**零依赖**的 MCP 服务端，把同一套采集能力
暴露给 **Codex / WorkBuddy / 千问办公** 等任何支持 MCP 的客户端——**你不需要 `pip install` 任何东西**。

先看本机连接信息（**绝对路径版最稳**）：

```bash
python scripts/mcp_server.py --print-config
```

它会打印 `command`（Python 解释器绝对路径）与 `args`（脚本绝对路径），
以及一段可直接粘贴的 `mcpServers` JSON。

**要粘的 JSON 长这样**（下面这份是**已经填好的样子**，照着换成你自己的路径即可；只有两处要改）：

```json
{
  "mcpServers": {
    "edu-material-harvest": {
      "command": "python",
      "args": [
        "D:/github/edu-material-harvest/skills/edu-material-harvest/scripts/mcp_server.py"
      ]
    }
  }
}
```

- **`command`**：写 `python` 就行；只有客户端报「找不到 python」时才改成解释器**绝对路径**（如 `C:/Python312/python.exe`）。
- **`args` 里那条路径**：改成你本机 `mcp_server.py` 的绝对路径 = 本仓库所在文件夹往下接 `skills/edu-material-harvest/scripts/mcp_server.py`。
  Windows 建议用**正斜杠** `/`；用反斜杠也行，但 JSON 里每个 `\` 要写成 `\\`。
- ⚠️ 路径里若带 `< >` 那是**占位符**，要连尖括号一起换成真路径；拿不准就直接用 `--print-config` 打印的那份，它不会错。

下面说的「那段 JSON」= 上面那个 `mcpServers` 代码块。照着做，两列：**你要做的** / **装好怎么看**：

| 客户端 | 你要做的 | 装好怎么看 |
|---|---|---|
| **Claude Code** | 在仓库目录跑 `python scripts/mcp_server.py --install claude`（它自动写配置）。若用 `/plugin` 装插件，**MCP 已自动挂上，什么都不用做**。 | `claude mcp list` 里出现 `edu-material-harvest` |
| **Codex** | 跑 `python scripts/mcp_server.py --install codex` | `codex mcp get edu-material-harvest` 能打印出配置 |
| **WorkBuddy** | 打开「连接器（MCP）」→ 新建一个服务器，类型选 **stdio**（本地进程）；把 `command` 填到「命令」栏、`args` 填到「参数」栏。 | 连接器列表里能看到它，并能展开出工具列表 |
| **千问办公（QwenWork）** | 桌面端「**扩展 → 连接器 → + 添加**」→ 选「**填写/粘贴 JSON 配置**」，把**那段 JSON 整段**粘进去；或选「**手动添加配置**」，类型选 **STDIO**，再分开填 `command`/`args`。**加完必须新建一个任务**才生效。 | 在「连接器 → 已安装 → 自定义」里能**展开出工具列表**才算真连上（开关是开的 ≠ 已连接） |
| **Claude Desktop / Cursor / Cline** | 打开它各自的 MCP 配置文件，把**那段 JSON** 粘进去，重启该客户端。 | 客户端里出现这批工具 |

装上后，客户端里会出现这些工具：`env_check`、`harvest_school`（一键）、`harvest_many`（批量多校）、
`harvest_pages`（承载页直采）、`discover_school`、`read_artifacts`、`job_wait` 等。**长任务自动转后台**，不会把客户端憋超时。

> 两条入口在 MCP 里一样：`harvest_school` 走全站爬，`harvest_pages` 走承载页直采
> （承载页网址由**客户端模型联网搜出来**再传进去）。原理与排障见 `references/09-Agent接入与MCP.md`。

> ⚠️ `command` 要么是 PATH 里的 `python`，要么是**绝对路径**——客户端通常不继承你终端的 PATH，
> 所以直接用 `--print-config` 给的绝对路径，别手写成 `python` 赌运气。

---

## 八、红线（本 skill 的底线，别改坏）

1. **只采官方 `*.edu.cn` 免登录公开源**；登录墙后的一律放弃。
2. **绝不猜域名、绝不编 URL**——每条链接都实测过。
3. **原始数据目录只读**：不删、不改、不移、不改名；产物一律另存新文件。
4. **删除一律走回收站**（无 PowerShell 时隔离到临时目录，**绝不永久删除**）。
5. **全自动只授权"怎么跑"，不授权"跑什么"**——扩大采集范围（换校 / 换材料类型）须用户点名。

# edu-material-harvest · 高校公开资料采集

给定「学校名 + 官方域名」，从**官方免登录 `*.edu.cn` 公开源**自动发现并采集高校的
**培养方案 / 专业介绍 / 课程大纲 / 年度报告**，逐份落盘并登记**可溯源台账**（下载直链 + 承载页）。
适用于**任意中国高校，不限地域**。

## 安装

**前置**：本机要有 **Python 3**（采集引擎是 Python 脚本；Windows **不自带**，需先单独安装）和 **curl**
（Win10 / 11 一般已自带）。

### Claude Code（插件形态，最省事）

```
/plugin marketplace add shoucunren-tsy/edu-material-harvest
/plugin install edu-material-harvest@edu-material-harvest
```

装完即可用——**MCP 会自动挂上**，无需再配。

### Codex（插件形态）

```
codex plugin marketplace add git@github.com:shoucunren-tsy/edu-material-harvest.git
codex plugin add edu-material-harvest@edu-material-harvest
```

> 这里用 SSH 地址，是因为国内直连 GitHub 的 HTTPS 常不稳；需本机已配好 GitHub SSH key。
> 也可以用 MCP 方式接（见下），二选一。

### 其它客户端（WorkBuddy / 千问办公 / Cursor / Cline / Claude Desktop …）

下载或克隆本仓库后，按下面「跨 Agent 可用（MCP）」一节，跑一条命令拿到配置 JSON，粘进客户端的
MCP 设置即可。

## 用法

在 Claude Code 里**直接说需求**即可——它会先联网核实每所学校的**官方域名**（绝不猜域名），再自动发现、逐份下载并出台账。例如：

- 单校 · 某类材料：`帮我采集华中科技大学的年度报告`
- 单校 · 四类全采：`把北京大学的培养方案、专业介绍、课程大纲、年度报告都采下来`
- 承载页直采（站点栏目乱、全站爬容易采到假货时）：`只采这几个页面：<承载页 URL1> <承载页 URL2>`
- 地区批量：`把湖南的 985 高校（中南大学、湖南大学、国防科技大学）的培养方案都采了，各校分开存`
- 地区批量（211 / 双一流同理）：把名单换成你要的学校即可，不限省份

⚠️ 三点如实说：① 能采到什么取决于该校是否有**官方免登录公开源**（站点被拦截或不可达时可能无果）；
② 批量是**按你给的名单逐校做**，每校都会先核实域名——请先给出具体名单，别写"某地区所有高校"；
③ 只采官方免登录源，不碰需要登录/付费的内容。

也可直接跑脚本：

```
# 单校
python skills/edu-material-harvest/scripts/discover.py --school <校名> --domain <域名>          # 只侦察
python skills/edu-material-harvest/scripts/discover.py --school <校名> --domain <域名> --auto   # 采集 + 出台账

# 批量（自己给名单）：照 skills/edu-material-harvest/references/schools_seed.example.json 写 schools_seed.json
python skills/edu-material-harvest/scripts/discover.py --seeds schools_seed.json --auto         # 逐校采集，各出到子目录

# 地区批量（内置教育部高校名单，按 省/城市/层次/985·211 生成名单；域名由你上传或由 Agent 现搜）
python skills/edu-material-harvest/scripts/region_seeds.py --province 湖北 --preset 985 --out seeds.json
python skills/edu-material-harvest/scripts/discover.py --seeds seeds.json --auto
```

## 跨 Agent 可用（MCP）

采集内核带一个**零依赖** stdio MCP 服务端（纯 Python，**不用 `pip install` 任何东西**），
除 Claude Code 外，Codex / WorkBuddy / 千问办公 / Claude Desktop / Cursor / Cline 等任何支持
MCP 的客户端都能挂上**同一套采集能力**（工具、Resources、Prompts 齐全；长任务自动转后台，不会憋超时）。

### 安装：给支持 MCP 的客户端挂上这段配置

**最省事的做法**：在本仓库根目录里跑一次下面这条命令，它会**打印一段已经填好你本机绝对路径的配置**，
把打印出来的那段**整段复制、粘到客户端里**即可，不用自己改：

```
python skills/edu-material-harvest/scripts/mcp_server.py --print-config
```

---

**如果你想自己写**，配置就长下面这样（下面这份是**已经填好的样子**，照着换成你自己的路径即可）：

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

只有**两处**需要按你的机器改：

- **`command`**：写 `python` 就行。只有当客户端报「找不到 python」时才改——客户端通常不继承你终端的
  PATH，改成 Python 的**绝对路径**，例如 `C:/Python312/python.exe`。
- **`args` 里那条路径**：改成你本机 `mcp_server.py` 的绝对路径，也就是**你把本仓库下载/克隆到的那个
  文件夹**，往下接 `skills/edu-material-harvest/scripts/mcp_server.py`。
  Windows 建议用**正斜杠** `/`（像上面示例那样）；用反斜杠也行，但 JSON 里每个 `\` 都要写成 `\\`，容易写错。

> ⚠️ 两个常见的坑：① 如果你手上的版本里路径带 `< >`，那是**占位符**，要**连尖括号一起换成真路径**，
> 别把尖括号留在 JSON 里；② 路径写错会让客户端「连上却列不出工具」——**拿不准就直接用 `--print-config`
> 打印的那份**，它不会错。

下面表格里说的「**那段 JSON**」= 上面那个 `mcpServers` 代码块（自己写、或复制 `--print-config` 打印的那份都行）。

各客户端怎么装——照着做，两列：**你要做的** / **怎么确认装好了**：

| 客户端 | 你要做的 | 装好怎么看 |
|---|---|---|
| **Claude Code** | 在仓库目录里跑一条命令：`python skills/edu-material-harvest/scripts/mcp_server.py --install claude`（它自动帮你写好配置）。若你是用 `/plugin` 装的插件，**MCP 已自动挂上，什么都不用做**。 | 跑 `claude mcp list`，列表里出现 `edu-material-harvest` 即成功。 |
| **Codex** | 同样跑一条命令：`python skills/edu-material-harvest/scripts/mcp_server.py --install codex` | 跑 `codex mcp get edu-material-harvest`，能打印出配置即可。 |
| **WorkBuddy** | 打开「连接器（MCP）」→ 新建一个服务器，类型选 **stdio**（本地进程）；把**那段 JSON** 里的 `command` 填到「命令」栏、`args` 填到「参数」栏。 | 连接器列表里能看到它，并能展开出工具列表。 |
| **千问办公（QwenWork）** | 桌面端「扩展 → 连接器 → + 添加」→ 选「**填写/粘贴 JSON 配置**」，把**那段 JSON 整段**粘进去；或选「**手动添加配置**」，类型选 **STDIO**，再分开填 `command`/`args`。**加完必须新建一个任务**才生效。 | 在「连接器 → 已安装 → 自定义」里能**展开出工具列表**才算真连上（右边的开关是开的 ≠ 已连接）。 |
| **Claude Desktop / Cursor / Cline** | 打开它各自的 MCP 配置文件，把**那段 JSON** 粘进去，然后重启该客户端。 | 客户端里出现这批工具（`env_check`、`harvest_school` 等）。 |

挂上后客户端里会出现 `env_check`、`region_seeds`（地区名单）、`harvest_school`（一键）、
`harvest_many`（批量多校）、`harvest_pages`（承载页直采）、`build_ledger`、`read_artifacts`、
`job_wait` 等工具。原理与四客户端接入法见：
`skills/edu-material-harvest/references/09-Agent接入与MCP.md`

## DeepSeek Harness（DSH）

DSH 里 **skill 和 plugin 是两套东西**：skill 靠**目录发现**（不能用「添加插件」装），plugin 才是「添加插件」里那种包。本仓库两种形态都备好了：

- **当 skill（最快、最稳）**：把 `skills/edu-material-harvest/` 复制到 `~/.dsh/skills/`（或跨 Agent 共享的 `~/.agents/skills/`）即可——**热重载、免重启**。规则：必须放在技能根**直属一层**、目录名 kebab-case。
- **当 plugin（GitHub 一键）**：仓库根已带 DSH bundle 三件套（`package.json` + `cordis.patch.yml` + `lib/index.js`）。桌面版走**设置 → 插件 → 添加插件**填本仓库 GitHub 地址；CLI 可 `dsh plugin --profile web add "github:<用户>/edu-material-harvest"`（装完重启 profile）。
- **走 MCP**：把上面的 `mcpServers` JSON 贴进 DSH 的 MCP 配置，工具以 `mcp__edu-material-harvest__*` 出现（DSH 只桥 **tools**，不认 resources/prompts）。

详见：`skills/edu-material-harvest/references/11-DeepSeek-Harness接入.md`

## 详细文档

- 安装接入与故障对照：`skills/edu-material-harvest/README-安装与接入.md`
- 自动发现逻辑（设计思路 / 判据 / 边界）：`skills/edu-material-harvest/references/08-自动发现逻辑.md`
- 跨 Agent 接入与 MCP（架构 / 协议 / 工具 / 排障）：`skills/edu-material-harvest/references/09-Agent接入与MCP.md`
- 地区批量（省份/985·211 → 逐校，两路域名 + 溯源）：`skills/edu-material-harvest/references/10-地区批量.md`
- 使用教程：`skills/edu-material-harvest/使用教程_高校公开资料采集.docx`

## 红线

只采官方 `*.edu.cn` 免登录公开源；绝不猜域名、绝不编造 URL；每条链接都实测过。

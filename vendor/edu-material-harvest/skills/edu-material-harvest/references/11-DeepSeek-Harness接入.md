# 11 · DeepSeek Harness（DSH）接入

本文件回答：**同一套采集能力，怎么装进 DeepSeek Harness（DSH）用。**

DSH 是 DeepSeek 开源的、**插件化**（跑在 Cordis 内核上）的 Agent 运行时，有桌面版与 CLI。
它和 Claude Code 不一样：**Claude Code 认 `SKILL.md` 文件夹，DSH 认「skill 目录」与「plugin 包」两套东西。**
搞混了就会「装了却用不上」，所以先分清这两个概念。

---

## 0. 一句话总纲

> **DSH 里 skill ≠ plugin。** 本仓库两样都备好了：
> **① 当 skill**——把 `skills/edu-material-harvest/` 丢进 DSH 的技能目录，免打包、热重载；
> **② 当 plugin**——仓库根已带 DSH bundle 三件套，在桌面版「添加插件」里填 GitHub 地址即可一键装。
> 还能 **③ 走 MCP**——把自带的 `mcp_server.py` 挂上，工具以 `mcp__…` 出现。

---

## 1. 先分清：skill vs plugin（DSH 特有）

| | **skill** | **plugin（bundle）** |
|---|---|---|
| 是什么 | Markdown 指令集（`SKILL.md`，或扁平 `.md`） | 代码包（npm 包 + Cordis 插件） |
| 怎么装 | **放进技能目录**（本地扫描发现） | **「添加插件」**（GitHub / npm / 本地目录） |
| 能否用「添加插件」装 | ❌ **不能** | ✅ 能 |
| 生效方式 | 目录被 watch，**热重载、免重启** | 改 bundle 后**需重启 profile** |
| 我们对应 | ✅ 主形态 | ✅ 已打包（本仓库根三件套） |

> 关键：**skill 靠目录发现，`dsh plugin add` 装不了 skill。** 下面方式 A/B 分别对应这两条路。

---

## 2. 方式 A｜装成 DSH skill（最快，推荐）

DSH 按固定顺序扫描**技能根目录**（rank 越小越优先）：

| Rank | 来源 | 根目录 |
|---|---|---|
| 100 | project-dsh | `<项目根>/.dsh/skills` |
| 200 | project-agents | `<项目根>/.agents/skills`（与 Cursor / Copilot 共享） |
| 300 | custom | `Config.customSkillDirs` |
| 400 | user-dsh | `<DSH_HOME>/skills`（默认 `~/.dsh/skills`） |
| 500 | user-agents | `<AGENTS_HOME>/skills`（默认 `~/.agents/skills`） |
| 600 | bundled | `Config.bundledSkillDir` |

### 步骤

把整个 skill 文件夹复制进**任一**技能根，目录名保持 `edu-material-harvest`：

```
# Windows 用户级（对你所有项目生效）
C:\Users\<你>\.dsh\skills\edu-material-harvest\SKILL.md
#   或跨 Agent 共享根
C:\Users\<你>\.agents\skills\edu-material-harvest\SKILL.md
```

（macOS / Linux 同理：`~/.dsh/skills/edu-material-harvest/`。）

项目级则放在**项目根**下：`<项目>\.dsh\skills\edu-material-harvest\`。

### 四条硬规则（踩了就不被发现）

1. **只扫一层**：必须是 `<根>/edu-material-harvest/SKILL.md`。放到更深一层（如 `…/skills/edu-material-harvest/子目录/SKILL.md`）**不会被发现**。
2. **目录名必须 kebab-case**（`^[a-z0-9]+(-[a-z0-9]+)*$`）——`edu-material-harvest` ✅。
3. **项目根 = 含 `.git` 的最近祖先**。在仓库子目录里放 skill 不算数，要在根直属位置。
4. **热重载**：放好即生效，**不用重启**；改 frontmatter 也会自动重建。

### 用法

DSH 里直接说需求即可（模型先读 `name`/`description` 目录，按需再读正文）：
「采集华中科技大学的年度报告」；也可用 `/edu-material-harvest` 显式调用。

> `.claude/skills` **不在** DSH 的技能根列表里——从 Claude Code 迁移时，**优先用 `.agents/skills`**（最不绑产品）。

---

## 3. 方式 B｜装成 DSH 插件（GitHub 一键）

在「添加插件」里填**本仓库的 GitHub 地址**，DSH 按 bundle 安装。适合「想用界面一键装、不想手动拷目录」。

### 桌面版（推荐，你的场景）

**设置 → 插件 → 添加插件** → 填 GitHub 仓库地址（或本地目录路径）→ 安装 → **重启 profile**。

> ⚠️ 桌面版走**自己的**插件管理器（profile 名通常为 `desktop`）。
> CLI 的 `dsh plugin --profile web add …` **只写 web profile**，改不到桌面版。

### CLI 版（web / 其它 profile）

```bash
# GitHub 源
dsh plugin --profile web add "github:<用户名>/edu-material-harvest"
# 本地目录源（开发/调试）
dsh plugin --profile web add "file:<绝对路径>/edu-material-harvest"
# 装完重启 profile，并验证
dsh --profile web --dump-config      # 输出里应出现 edu-material-harvest
```

### 本仓库已带的 bundle 三件套

DSH 规定：**只有声明了 `dsh.bundle.patch` 的包才会被激活**（光装包不激活＝插件是死的）。本仓库根已备：

```
package.json        → "dsh": { "bundle": { "patch": "./cordis.patch.yml" } }
cordis.patch.yml    → - insert: [{ id: edu-material-harvest, name: 'edu-material-harvest-dsh' }]
lib/index.js        → Cordis 插件：把本包 skills/ 目录注册进宿主技能表
skills/             → 就是 skill 本体（SKILL.md + references + scripts）
```

`lib/index.js` 用 `import.meta.url` 定位**自己包内**的 `skills/` 目录，**不依赖任何用户配置**——所以无论包被装到哪个 profile 的 `node_modules` 下都能找到 skill 本体。

> ⚠️ **诚实说明**：方式 B 的 bundle 依据 DSH 官方插件规范与一个公开的同类插件（`superpowers-dsh`）结构编写，`lib/index.js` 的解析/发现逻辑已在本机用 Node 实测通过；但**在 DSH 真机上的「添加插件 → 生效」这一步尚未实测**。若装后没出现，优先改走方式 A（skill 目录，机制确定）。

---

## 4. 方式 C｜走 MCP（复用现成的 `mcp_server.py`）

DSH 支持**标准 `mcp.json`**（`mcpServers` 键，与 Claude Desktop / Cursor 同格式）。把本仓库 README 里那段 JSON 贴进 DSH 的 MCP 配置即可：

```json
{
  "mcpServers": {
    "edu-material-harvest": {
      "command": "python",
      "args": [
        "<仓库绝对路径>/skills/edu-material-harvest/scripts/mcp_server.py"
      ]
    }
  }
}
```

挂上后工具以 **`mcp__edu-material-harvest__harvest_school`** 形式出现（前缀 `mcp__<serverName>__<tool>`）。

> ⚠️ **DSH 目前只桥接 MCP 的 tools，Resources 与 Prompts 还没有消费者。**
> 意味着 `edu://manual`、`edu://ref/*` 这些手册**在 DSH 里读不到**。
> 好在我们的 `region_seeds` 工具**把「名单口径边界」写进了工具输出**——只认 tools 的客户端也漏不掉。
> 这正是当初做「工具输出内嵌边界 + resource 双保险」的原因。

---

## 5. 三种方式怎么选

| 你的目标 | 选 |
|---|---|
| 最快、最稳、只要能用 | **A**（拷进 `~/.dsh/skills/`） |
| 想用界面「添加插件」一键装、跟仓库同步 | **B**（GitHub bundle） |
| 只想让它当工具被调用、不掺 skill | **C**（MCP） |

三者可并存；同时装也不冲突（skill 名与 MCP serverName 不同域）。

---

## 6. 前置依赖（DSH 自带什么）

- DSH 桌面版自带 **Python 3.12**，已含 `openpyxl`（出台账要用 ✅）。
- **不含 `pymupdf`** → 从 PDF 取名会退化为通用名（打 WARN，不崩），台账照常出。
- RAR/ZIP 打包件需要 **7-Zip**；本 skill 会自动探测（`scripts/env.py`）。
- 缺依赖本 skill **要吵不要哑**，不会假装成功。

---

## 7. 排障

| 现象 | 原因 | 解决 |
|---|---|---|
| 方式 A：DSH 里看不到 skill | 没放在技能根**直属一层** / 目录名非 kebab-case | 确认 `<根>/edu-material-harvest/SKILL.md` |
| 方式 A：在仓库子目录放，没被发现 | 项目根=含 `.git` 的最近祖先 | 放到项目根直属的 `.dsh/skills/` |
| 方式 B：「添加插件」成功但不激活 | 包未声明 `dsh.bundle.patch`，或少了 `cordis.patch.yml` | 本仓库已带；确认装的是本仓库 |
| 方式 B：装了不动 | bundle 变更未重启 | **重启 profile** |
| 方式 B：桌面版装 CLI 命令没反应 | CLI 只写 web profile | 桌面版请用**设置 → 插件** |
| 方式 C：工具列表为空 | `command` 路径错 / Python 不在 PATH | 用解释器**绝对路径**；先跑 `env_check` |
| 方式 C：手册 / prompts 读不到 | DSH 只桥 tools | 正常边界；边界文字已内嵌在 `region_seeds` 输出 |

---

## 8. 红线不变

沿用内核红线：**只采官方免登录 `*.edu.cn`**；**不猜域名、不编 URL**；原始数据只读；删除走回收站；
**全自动只授权「怎么跑」，不授权「跑什么」**（换校 / 换材料类型须点名）。

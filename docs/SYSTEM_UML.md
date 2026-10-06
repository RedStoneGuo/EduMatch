# EduMatch 系统 UML 图（Core 大系统全景）

> 定位：把整个 `EduMatch` 文件夹当作**一个大系统**，按 `PROMPT.md` 与 `AGENTS.md §0`
> 的真实工作路径，补齐**调用的东西（组件/参与者）→ 方法（入口命令与函数）→ 产物（落盘文件）**。
>
> 画法：采用 UML **组件图**约定（`«system»` 系统边界、`«component»` 组件、`«actor»` 参与者、
> `«artifact»` 产物），用 Mermaid `flowchart` 渲染；编号 ①–⑫ 即一次分析的执行顺序。

## 1. 系统 UML 图

```mermaid
flowchart TD
    %% 定义节点样式 (UML 规范配色)
    classDef actor fill:#f9f9f9,stroke:#333,stroke-width:2px;
    classDef component fill:#e1f5fe,stroke:#0288d1,stroke-width:2px;
    classDef data fill:#e8f5e9,stroke:#388e3c,stroke-width:2px;
    classDef artifact fill:#fff3e0,stroke:#f57c00,stroke-width:2px;

    %% ============ 外部参与者 ============
    User["🧑 用户（政府 / 专业负责人 / 学生本人）\n一句话：分析 [院校][专业] 与 [岗位] 的匹配度"]:::actor
    Agent["🤖 Agent（主体）\nCodex / 大模型 + AGENTS.md + skills/\n问询 · 判断尺度 · 读原文 · 写结论"]:::actor
    ExtNet["🌐 外部数据源\n高校官网 · 就业质量报告 · 招聘语料 · 政策文件"]:::data

    %% ============ 系统边界 ============
    subgraph SYS["«system» EduMatch · 可被 Agent 调用的确定性「教育—就业供需适配分析引擎」"]
        direction TB

        Toolchain["«component» 入口 · Toolchain\nanalyze.ps1 / scripts/analyze.py\n方法：analyze(query, occupation, micro_file, scope)"]:::component
        AutoHarvest["«component» 自动补采\nedumatch/auto_harvest.py · domain_discovery.py\n方法：run_plugin_harvest() · verify_domain()"]:::component
        Plugin["«component» Plugin 插件\nvendor/edu-material-harvest\n方法：harvest_school / harvest_pages / job_wait / read_artifacts"]:::component
        KB["«component» Knowledge Base 知识数据层\nedumatch/ + data/\n方法：Dataset.course_set() · facts() · profiles · evidence\n数据来源三模式：local / plugin / hybrid"]:::component
        Engine["«component» Core TSI Engine 计算层\nanalysis/（纯函数，无 LLM）\n方法：build_supply_vector · build_demand_vector · skill_fit\nskill_gap · primary_tsi · tsi_tree · mechanism · trend · simulation"]:::component
        Renderer["«component» Renderer 交付渲染层\nreporting/\n方法：python -m reporting.render --result r.json --scope all"]:::component
        Gate["«component» 质量门与审计\nscripts/validate_edumatch.py · audit_report.py\naudit_course_coverage.py · pytest tests -q"]:::component
        Mcp["«component» MCP Server\nmcp_servers/server.py\n方法：42 工具 / 6 分组（stdio JSON-RPC）"]:::component
    end

    %% ============ 产物 ============
    HarvestStore["«artifact» 补采入库产物\ndata/harvest/[院校]/courses.json · facts.json · texts/ · manifest.json"]:::artifact
    Ledger["«artifact» 台账与数据库\ndata/harvest/auto_harvest_ledger.json · domains.json\ndata/db/edumatch.sqlite"]:::artifact
    RunSnapshot["«artifact» 运行与证据快照\ndata/processed/runs/[run_id]/\nreport.md · result.json · plan.json · evidence.json"]:::artifact
    Deliverable["«artifact» 分层交付物\n分析产物/[院校]_[专业]_[岗位]/\n报告_all.html · 报告_macro/_meso/_micro.html · 报告_*.md · result.json"]:::artifact
    DemoPage["«artifact» 离线演示页\ndemo/output/index.html"]:::artifact

    %% ============ 调用关系（工作路径） ============
    User -->|自然语言| Agent
    Agent -->|"① 读 AGENTS §0 / skills/00，先问询：尺度·院校·专业·岗位·交付层级"| Toolchain
    Toolchain -->|"② 触发自动补采（默认开启）"| AutoHarvest
    AutoHarvest -->|"③ 域名发现 → 核验 → 入库"| Ledger
    AutoHarvest -->|"④ 调用插件"| Plugin
    Plugin -->|"⑤ 联网采集官方材料"| ExtNet
    Plugin -->|"⑥ 采回原件与正文"| HarvestStore
    HarvestStore -->|"⑦ 解析入库（课程 / 事实 / 正文）"| KB
    KB -->|"⑧ 装配 Supply / Demand / Evidence"| Engine
    Engine -->|"⑨ Fit → Gap → Primary TSI"| Renderer
    Renderer -->|"⑩ 生成分层报告（MD + HTML）"| Deliverable
    Engine -->|"⑪ 运行快照落盘"| RunSnapshot
    Gate -.->|"⑫ 质量门：数值 / TSI 唯一 / 缺失 / 语义 / 证据链"| Deliverable
    Gate -.->|"质量门复核"| RunSnapshot
    Mcp -->|对外暴露工具| KB
    Mcp -->|对外暴露工具| Engine
    Renderer -->|离线导出| DemoPage
    Deliverable -->|交付| Agent
    Engine -->|决策辅助（LLM 只解释，不产数值）| Agent
```

## 2. 图例

| 记号 | 含义 | 对应实物 |
| --- | --- | --- |
| `«actor»` | 参与者和主体 | 用户、Agent（Codex / 大模型） |
| `«system»` | 系统边界 | 整个 `EduMatch` 文件夹 |
| `«component»` | 系统内被调用的组件 | Toolchain、AutoHarvest、Plugin、Knowledge Base、Core TSI Engine、Renderer、质量门、MCP Server |
| `«artifact»` | 产物（落盘文件） | 报告、result.json、运行快照、台账、采集入库件、演示页 |
| `-->` | 调用 / 数据流 | 编号 ①–⑫ 为一次分析的执行顺序 |
| `-.->` | 校验 / 非破坏性动作 | 质量门与审计 |

## 3. 工作路径（对应 `PROMPT.md` / `AGENTS.md §0`）

1. 用户一句话提出需求；Agent 先读 `AGENTS.md §0` 与 `skills/00_agent_entry/SKILL.md`，按 §2 多轮问询
   （尺度与对象 / 院校 + 专业 / 目标岗位 / 微观补充 / 交付层级）；目标不明确时只输出问询清单，不跑分析。
2. 目标确认后，Agent 调用**唯一入口**：`.\analyze.ps1 "<问题>" -Occupation "<岗位>" -Scope all`
   （等价 `python scripts\analyze.py --query "…"`）；这一条命令封装了补采 → 计算 → 渲染 → 质量门。
3. 系统默认开启**自动补采**：`edumatch/auto_harvest.py` 驱动 `vendor/edu-material-harvest` 插件
   （12 个 MCP 工具）采集本校 + 同类院校的全部材料类型；域名走「发现 → 核验 → 入库」，绝不猜域名。
4. 采集件落到 `data/harvest/[院校]/`，原件同步进 `data/source/`，由 `HarvestImporter` 解析入库。
5. `edumatch/` 装配 Knowledge–Skill–Capability–Practice 四层对象与 A–E 级证据链，供 `analysis/` 调用。
6. `analysis/` 是唯一产数值的地方：Supply → Demand → Fit → Gap → Primary TSI，并做 TSI Tree 分解。
7. `reporting/` 用 `python -m reporting.render` 生成分层交付物：`报告_all.html` 与
   `报告_macro/_meso/_micro.html`、同名 `.md`、`result.json`（补做只新增、不覆盖）。
8. 收尾跑质量门：`python scripts\validate_edumatch.py`（0 error）、`python scripts\audit_report.py`
   （维度自检，缺块返回 2），以及必要时的 `python -m pytest tests -q` 与课程覆盖核对。
9. 交付后 Agent 说明「发现了什么 / 改了什么 / 还缺什么 / 下一步」；需要更多同类校时按
   `-OfferUrl` 或 `-HarvestMode region -HarvestBatch N` 分批补采，台账累积在
   `data/harvest/auto_harvest_ledger.json`。

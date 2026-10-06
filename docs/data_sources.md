# 数据来源层：本地数据 / 插件联网 / 双重模式

> 适用版本：Core TSI Engine v3.0（数据来源扩展）
> 相关代码：`edumatch/local_supply.py`、`edumatch/harvest/`、`edumatch/source_modes.py`

本文件回答三个问题：**供给端数据从哪来、怎么切换、怎么验证**。
需求端（招聘岗位语料）本轮保持本地口径不变。

---

## 1. 三种模式

```powershell
# 本地数据（默认，离线可复现）
python -m agent.runner --query "分析北京工业大学人工智能专业与大模型算法工程师岗位的匹配度" `
  --occupation "大模型算法工程师" --source-mode local

# 插件联网数据：目标院校/专业的数据完全来自 edu-material-harvest，不掺本地库
python -m agent.runner --query "分析北京工业大学人工智能专业与大模型算法工程师岗位的匹配度" `
  --occupation "大模型算法工程师" --source-mode plugin --harvest

# 双重模式：本地全量 + 插件新收割，合并去重后综合分析
python -m agent.runner --query "分析北京工业大学人工智能专业与大模型算法工程师岗位的匹配度" `
  --occupation "大模型算法工程师" --source-mode hybrid --harvest

# 大站/子域被 WAF 挡住时（插件文档的推荐入口 B）：先用联网搜索定位承载页，再直采
python -m agent.runner --query "…" --source-mode hybrid --harvest `
  --domain bjut.edu.cn `
  --harvest-page "https://undergrad.bjut.edu.cn/content.jsp?...&wbnewsid=3270" --harvest-kind 培养方案
```

Python API：

```python
from agent.core import TalentSupplyDemandAgent

agent = TalentSupplyDemandAgent()
result = agent.research(
    "分析北京工业大学人工智能专业与大模型算法工程师岗位的匹配度",
    target_occupation="大模型算法工程师",
    source_mode="hybrid",     # local | plugin | hybrid
    harvest=True,             # 是否联网跑插件采集
    harvest_domain="bjut.edu.cn",
    harvest_pages=[{"url": "https://…", "kind": "培养方案"}],
)
print(result.data["data_source"])   # 本次供给端实际来源与规模
```

| 模式 | 目标校课程 | 校内事实 | 正文检索 | 需求侧 | 典型场景 |
| --- | --- | --- | --- | --- | --- |
| `local` | 本地库 | 本地库 | 本地库 | 本地招聘语料 | 27 所已有院校、离线复现 |
| `plugin` | 插件收割 | 插件收割 | 插件收割 | 本地招聘语料 | 任意院校、脱离本地库 |
| `hybrid` | 插件 + 本地 | 插件 + 本地 | 两者 | 本地招聘语料 | 同一院校"补采 + 已有"合并 |

规则：

1. **需求侧不因模式改变**：招聘数据仍取本地 `data/processed/jobs.json`，并按岗位族切片；
2. `plugin` 模式**不读本地课程/事实/正文**（`text_roots()` 返回空），没有收割数据时
   目标校供给如实记 `insufficient_evidence`，不挪用其它院校；
3. 模式可反复切换而不叠加：`Dataset` 首次装配前保存本地快照，切换时按快照重建；
4. 采集失败（无公开源、被 WAF 挡、域名未核实）**不中断分析**，写进
   `result["data_source"]["error"/"notes"]` 并在报告 §18 披露。

---

## 2. 本地数据层（`edumatch/local_supply.py`）

### 2.1 规范目录

`data/source` 按「数据类型 → 院校」组织（详见 `data/source/README.md`）。
`scripts/normalize_source_layout.py` 负责一次性重组，幂等且可回滚：

```powershell
python scripts\normalize_source_layout.py --dry-run   # 看迁移计划
python scripts\normalize_source_layout.py             # 执行（写 source_layout_map.json）
python scripts\normalize_source_layout.py --check     # 0 = 已规范
```

### 2.2 清洗（本轮修复的真实缺陷）

| 缺陷 | 影响 | 修复 |
| --- | --- | --- |
| 院校名被 PDF 抽取截断（`中国矿业大学`） | 按校检索命中 0 | 别名归一 → `中国矿业大学（北京）`（547 条） |
| 53 条事实 `school` 为空但来源路径可判校 | 事实挂在无主名下 | 由来源路径回填（74 条，含 pdf_index） |
| 政策 PDF 只登记不解析 | 11 份政策原文未进入分析 | `ingest_policy_dir` 增加 PDF 文本抽取（可读 144/147） |
| 政策目录指向包外/副本 | data/source 未被真正消费 | `config.yaml::ingestion.policy_dir` → `data/source/政策文件` |
| 同内容副本散落多处 | 重复占用体积、口径不清 | 逐字节去重后移入 `非分析归档/_重复件/`（40 份，不删除） |

### 2.3 索引与定点检索

```powershell
python scripts\build_source_index.py            # 清洗 + 建索引 + 审计
python scripts\build_source_index.py --check    # 只审计
```

产物：

* `data/processed/source_inventory.json` —— 逐份材料清单（类型/院校/专业/年份/关联产物/未解析原因）
* `data/raw/local_supply_index.json` —— 模型可直接调用的索引
* `data/processed/source_cleaning_log.json` —— 清洗日志

查询接口：

```python
from edumatch.local_supply import LocalSupplyIndex

index = LocalSupplyIndex.load()                 # 读落盘索引
index.coverage()                                # 利用率审计
index.school_profile("北京工业大学")            # 该校有哪些材料/专业/年份
index.materials(school="北京工业大学", material_type="培养方案", major="人工智能")
```

对应工具（MCP 组 `supply_source`）：`query_local_supply`、`local_supply_coverage`、
`harvest_status`、`harvest_school_materials`。

---

## 3. 插件接入层（`edumatch/harvest/`）

### 3.1 插件位置与后端

插件仓库随包放在 `vendor/edu-material-harvest/`（`git clone` 一份即可）。
`HarvestClient` 有三条后端：

| 后端 | 做什么 | 用途 |
| --- | --- | --- |
| `mcp`（默认） | 启动插件自带的零依赖 stdio MCP 服务端，走 NDJSON JSON-RPC 调 `harvest_school` / `harvest_pages` / `job_wait` / `read_artifacts` | 正式联网采集 |
| `script` | 调插件文档化 CLI（`discover.py --auto`） | MCP 不可用时的降级 |
| `replay` | 直接读一个既有产出目录，不启动插件、不联网 | 离线演示与单元测试 |

```python
from edumatch.config import load_settings
from edumatch.harvest import HarvestClient, HarvestConfig, HarvestImporter

config = HarvestConfig.from_settings(load_settings())
with HarvestClient(config) as client:
    print([t["name"] for t in client.list_tools()])     # 12 个工具
    print(client.env_check())                            # 依赖探测
    outcome = client.harvest("北京工业大学", "bjut.edu.cn", kinds=["培养方案"])
    result = HarvestImporter(load_settings().project_root).import_outcome(outcome)
```

### 3.2 域名：绝不猜

插件红线是「只采官方免登录 `*.edu.cn`、绝不猜域名」。本项目据此提供**已核实域名台账**：

```powershell
python scripts\build_harvest_domains.py     # → data/harvest/domains.json + carrier_pages.json
```

两份台账都从项目**自己的采集台账**（真实来源直链/承载页）提取，不联网臆测：

* `data/harvest/domains.json` —— 26 所院校的官方域名；
* `data/harvest/carrier_pages.json` —— 115 个承载页 URL，供 `--harvest-page` 直采。

插件在两种情况下会零命中，属**真实边界**而非 bug：
① 目标材料挂在未被全站爬覆盖的子域（走承载页直采）；
② 站点按来源 IP 做认证（例如经境外代理访问会跳 `ipauth.htm`）。

### 3.3 入库与解析

`HarvestImporter` 把插件产物接成与本地同构的数据：

| 步骤 | 落点 |
| --- | --- |
| 原件入库 | `data/source/<材料类型>/<院校>/…`（同名同内容跳过，绝不覆盖本地材料） |
| 培养方案解析 | `data/harvest/<院校>/courses.json`（学分/学时/必修，A 级） |
| 正文缓存 | `data/harvest/<院校>/texts/<材料类型>/*.txt` |
| 年度报告事实 | `data/harvest/<院校>/facts.json`（就业率/签约率/深造率等） |
| 台账 | `data/processed/harvest_imports.json`、`data/harvest/<院校>/manifest.json` |

**关键设计**：与本地完全相同的收割件虽然不再重复入库，但**仍会被解析进收割库**——
否则 `plugin` 模式（不依赖本地库）会缺这批课程。重复导入幂等。

---

## 4. 验证

## 3b. 同类院校检索（全国口径）

教师端/政府端的"同类基准"不能只看北京。`edumatch/peers.py` 用**全国高校名单**
（随插件下发的教育部名单，2952 所 + 985/211）判定同类院校：

```python
from pathlib import Path
from edumatch.peers import PeerSelector, find_peers

selector = PeerSelector.from_project(Path("."))
peers, note = selector.resolve("华中科技大学", major="机械工程", max_peers=6)
```

排序是**可解释加权**（不是排行榜）：层次一致 +40 / 接近 +18；同城 +25、同省 +15、
同区域 +8；同校型（理工/师范/财经/医药…）+6；同分时优先"已有材料、可离线分析"的院校。
每个候选都带 `reasons`，报告中逐条披露。

```powershell
python scripts\harvest_peers.py --school 北京工业大学 --major 人工智能 --max-peers 4 --list
python scripts\harvest_peers.py --school 北京工业大学 --peers 北京邮电大学,北京航空航天大学
python -m agent.runner --query "…" --source-mode hybrid --peers auto --peer-max 3
```

MCP 工具：`find_peer_schools`、`harvest_peer_schools`、`resolve_school_domain`。

### 域名：实测核实，不猜

插件红线是"绝不猜域名"。`scripts/resolve_school_domains.py` 的做法是**候选人+实测确认**：
请求 `https://<域名>`，要求 HTTP 200、返回 HTML、页面出现该校全名或简称，三项都满足才写入
`data/harvest/domains.json`（附状态码、命中词、时间）。实测通过示例：
`武汉大学→whu.edu.cn`、`华中科技大学→hust.edu.cn`、`天津大学→tju.edu.cn`、
`西安交通大学→xjtu.edu.cn`。

没有通过核实的候选会在报告里**显式列出**为 `missing_domain`，由 Agent 联网搜索补齐后重跑。

### 实测边界（2026-10-04）

| 目标 | 全站爬结果 | 结论 |
| --- | --- | --- |
| 北京工业大学 | 0 命中 | 材料在 `undergrad.bjut.edu.cn`，需承载页直采（拿到 350 份） |
| 华中科技大学 | 采到 16 份，但都是本科生院**表格下载**（申报表/模版） | 命中"类型假"陷阱 → 已加类型闸门隔离；需正确承载页 |
| 武汉大学 | 附件被站点拦截（实测返回 HTML） | 需要带承载页 referer 的直采 |

也就是说：**"找同类校"全国可用**；**"采到正确的材料"取决于站点结构**，大站要走
入口 B（Agent 联网搜索定位承载页 → `--harvest-page`）。这与插件文档的判据一致。

## 3c. 需求侧扩容：按专业导出的岗位表

`data/source/招聘数据/招聘原始表/_全部专业合并.xlsx` 是全国按专业导出的岗位表
（68 个专业 / 55,620 行 / 含"专业名称、学科门类、来源检索词"）。并入方式：

```powershell
python scripts\import_job_exports.py --dry-run
python scripts\import_job_exports.py
```

设计要点（保证既有结论不被稀释）：

* 新行写入 `corpus="major_export"` 与 `major_scopes`（一条岗位可同时属于多个专业）；
* `target_jobs()` / `baseline_jobs()` **排除**该语料 → AI/计算机的 16,161 / 53 口径完全不变；
* 分析某专业时优先用它的专业作用域语料，不再依赖"关键词恰好出现在 JD 里"——
  这正是交接文档里"需求侧只有 AI+CS"那个头号缺口的解法；
* 实测：北工大**机械工程**从"需求缺失、不予计算"变为可出结论（Primary TSI 45.63）。

## 4. 验证

```powershell
python -m pytest tests -q                                  # 全量单元测试
python -m pytest tests/test_supply_source.py -q            # 数据来源专项
python scripts\build_source_index.py                       # 清洗 + 索引 + 审计
python scripts\audit_data_coverage.py                      # 材料利用率
python scripts\build_harvest_replay.py                     # 生成离线回放夹具
```

离线回放（不需要网络、不需要插件在跑）：

```python
from edumatch.harvest import HarvestClient, HarvestImporter
outcome = HarvestClient.replay("demo/harvest_replay/北京工业大学", school="北京工业大学")
HarvestImporter(".").import_outcome(outcome)
```

### 实测结果（2026-10-04）

| 项 | 结果 |
| --- | --- |
| 插件 MCP 链路 | 12 个工具；`env_check` 通过（curl/7z/powershell/openpyxl） |
| 真实联网采集 | 北京工业大学 · 承载页直采 **350 份培养方案**，0 失败 |
| 与本地去重 | 338 份同名同内容跳过，**12 份本地缺失的培养方案**补入 |
| 收割库 | 18,972 门课程 / 350 份正文 |
| `plugin` 模式分析 | 78 门课（全部来自插件）· 岗位匹配度 64.29 · Primary TSI 61.34 |
| `hybrid` 模式分析 | 79 门课（插件+本地合并）· 岗位匹配度 64.29 · Primary TSI 68.06 |
| 本地数据利用率 | 94.2%（1818/1930），未解析逐条给出原因 |

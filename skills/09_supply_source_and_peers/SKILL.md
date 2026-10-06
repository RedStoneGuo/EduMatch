# 09 Supply Source & Peers｜数据来源与同类院校

## Purpose
让任意通用 Agent 在**对话中**确定分析尺度与对象后，能一键选对"供给端数据从哪来"和
"拿谁做同类基准"，再进入既有的匹配/缺口/TSI 流水线。

## When to use
- 用户给的院校**不在本地 27 所**里 → 需要插件联网采集；
- 用户要"和同类院校比" → 需要同类校检索与基准池；
- 用户问的专业**不是 AI/计算机** → 需要专业作用域岗位语料。

## Inputs
- 目标院校、专业、（可选）目标岗位；
- 数据来源模式：`local` / `plugin` / `hybrid`；
- 同类校口径：`auto`（全国名单自动判定）/ `none` / 显式校名列表。

## Outputs
- `result.data_source`：本次供给端实际来源、规模、同类校候选与跳过原因；
- peer benchmark 池：目标校 vs 同类校 vs 市场的三角比较。

## Workflow
1. **定尺度与对象**：跟用户确认「院校+专业+目标岗位」（中观）；宏观/微观见
   `docs/下一阶段_TSI多尺度多角色应用层.md`。
2. **选模式**：本地有数据用 `local`；没有或要"脱离本地库"用 `plugin`；要"本地+新增"用 `hybrid`。
3. **补域名**（若走插件）：`find_peer_schools` 看候选；缺域名的用
   `resolve_school_domain`（实测核实）或联网搜索后写入 `data/harvest/domains.json`。
4. **采同类校**：`harvest_peers.py`（推荐先预取）或引擎参数 `--peers auto --harvest`。
5. **运行分析**：`python -m agent.runner --query "…" --occupation "…" --source-mode … --peers auto`。
6. **审阅披露**：报告 §18 会列出候选、得分、理由、跳过原因与利用率；缺失一律记 null。

## Tools
`query_local_supply`、`local_supply_coverage`、`harvest_status`、`harvest_school_materials`、
`find_peer_schools`、`harvest_peer_schools`、`resolve_school_domain`

## Constraints
- **同类校是"可解释加权排序"，不是排行榜**，理由必须随候选一起输出；
- **域名不猜**：只有实测确认（HTTP 200 且页面出现校名）才入台账；
- **类型闸门**：插件栏目名不等于材料本体；"培养方案却是 .doc/.xls"一律隔离到
  `data/source/非分析归档/疑似误判/`；
- 大站/被 WAF 挡的站点走**承载页直采**（入口 B），别反复全站爬；
- 需求侧：按专业导出的语料只在分析对应专业时使用，AI/计算机既有口径不得被稀释。

## Evidence requirements
同类校候选要带 `score + reasons + domain + harvestable`；采集要带 `url + page` 台账；
未解析/未采集的每一份都要有原因。

## Failure handling
- 目标校无公开源 → 目标校供给予 `insufficient_evidence`，不用同类校替代，报告披露；
- 同类校域名缺失 → 列入 `missing_domain`，请用户/Agent 补后再跑；
- 采集到的是表格/模版 → 类型闸门隔离，报告提示换承载页重采。

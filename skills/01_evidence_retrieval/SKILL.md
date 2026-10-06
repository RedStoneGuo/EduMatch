# 01 Evidence Retrieval｜证据检索

## Purpose
为研究任务建立可追溯的证据底座：把归档中的政策原文、报告抽取结果、结构化事实与既有中间产物，转成带来源定位与证据等级的条目。

## When to use
- 任何分析开始前的第一步；
- 需要回答"这个数字从哪来"；
- 需要判断某个结论是否只是 LLM 的印象。

## Inputs
- `query`：研究问题；`major` / `school` / `year`：范围限定。
- 本地一手材料目录 `data/source`（规范结构「数据类型 → 院校」，只读，不得修改）；
  插件联网采集的一手材料由 `edumatch/harvest` 落到同一结构。

## Outputs
- `EvidenceItem[]`：含 `evidence_id / source_type / locator / quote / year / school / evidence_level / confidence`。
- 证据等级分布与缺口清单。

## Workflow
1. 调用 `get_report` 读取归档清单，确认覆盖范围；
2. 调用 `query_employment` / `find_report_evidence` 召回陈述性事实；
3. 调用 `search_policy` 与 `find_policy_evidence` 召回政策原文；
4. 对每条证据标注等级：A 官方原文 / B 官方数据计算 / C 多源交叉 / D 语义抽取 / E 不足；
5. 输出缺口清单（哪些指标没有任何证据）。

## Tools
`get_report`、`find_report_evidence`、`query_employment`、`search_policy`、`find_policy_evidence`、`list_sources`

## Constraints
- 不修改归档；不抓取未授权内容；不把 LLM 摘要当作原始数据。
- 同一事实有多个来源时保留全部来源，不做合并覆盖。

## Evidence requirements
每条证据必须给出 `locator`（文件相对路径 / 表号 / URL）与 `quote`（原文片段）。无 locator 的内容不得进入结论。

## Failure handling
- PDF 无解析器 → 登记 `text_status='extractor_unavailable'`，不猜测内容；
- 检索为空 → 返回 `insufficient_evidence` 并说明缺失字段名。

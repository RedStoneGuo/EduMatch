# 08 Audit & Report｜审计与报告

## Setup
本 Skill 负责把前面所有结果组装成可答辩、可追溯、可复现的报告，并做自检。

## When to use
- 每次分析收尾；
- 任何对外输出前；
- 提交比赛材料前。

## Inputs
- 引擎结果（指标、分数、证据、工具调用日志）。

## Outputs
- 18 节研究报告（研究对象→数据范围→……→Evidence Chain）；
- 审计记录（analysis_runs / evidence / metrics 表）；
- 自检清单结果。

## Workflow
1. `render_markdown` 生成报告；
2. `trace_claim` 对关键结论做证据回溯；
3. 自检：缺失是否记 null、就业率与岗位数是否分离、是否出现因果断言、是否存在无法解释的分数；
4. 持久化运行记录（analysis_id / plan / tool_calls / metrics / scores / evidence / timestamp）。

## Tools
`search_evidence`、`get_evidence`、`trace_claim`、`list_sources`

## Constraints
- 报告中的每个数字必须能被 analysis/ 下的函数复算；
- 不得隐藏缺失与不确定性；
- 不得把模拟结果表述为预测。

## Evidence requirements
报告末尾必须附证据链摘要与运行编号。

## Failure handling
- 自检发现"缺失记 0""就业率来自岗位数""因果表述"任一项 → 阻断输出并回到对应 Skill 修复；
- 持久化失败 → 报告仍可输出，但必须提示运行记录未落库。

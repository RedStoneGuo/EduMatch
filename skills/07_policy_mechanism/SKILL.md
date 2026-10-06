# 07 Policy & Mechanism｜政策与机制分析

## Purpose
分析"产业政策 → 产业方向 → 专业设置 → 课程建设 → 技能供给 → 岗位需求 → 供需适配"的关联路径与解释贡献。

## When to use
- 需要解释适配度差异的可能来源；
- 需要评估政策对专业与课程方向的指引；
- 需要给出改进建议的证据基础。

## Inputs
- 政策文本（官方原文，A 级）；专业与课程数据；需求向量；学校层面指标。

## Outputs
- 政策—产业—技能关联表；
- 相关系数、OLS 条件关联、置换重要性；
- 作用路径描述（关联口径）。

## Workflow
1. `query_industry_direction` / `query_talent_policy` 统计政策方向；
2. 建立政策技能词与本体技能的映射；
3. `run_regression` / `run_shap_analysis` 计算解释贡献；
4. 用语言护栏改写表述。

## Tools
`search_policy`、`get_policy`、`find_policy_evidence`、`query_industry_direction`、`query_talent_policy`、`run_regression`、`run_shap_analysis`

## Constraints
- 无因果识别不得写"政策导致了……"，只能写"与……呈现关联 / 在模型中具有较高解释贡献 / 可能通过……形成作用路径"；
- 政策提及频次不等于政策强度或资金规模；
- 样本量不足时不得输出重要性排序。

## Evidence requirements
每条机制结论必须能回到具体政策文件与具体指标数值。

## Failure handling
- 配对样本 < 3 → 相关分析返回证据不足；
- 样本 < 12 → 不做模型重要性，改用描述性对比。

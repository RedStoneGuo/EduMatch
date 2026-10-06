# 03 Employment Analysis｜就业结果分析

## Purpose
只从就业质量报告类数据中提取"就业结果"指标，与岗位需求强度严格分离。

## When to use
- 计算 C 类（产出适配度）指标；
- 回答"毕业生就业情况如何"；
- 为 TSI 提供供给侧结果证据。

## Inputs
- 就业质量报告抽取事实（`placement_rate / signing_rate / further_study_rate / graduates`）。

## Outputs
- 就业结果指标 + 来源元数据（年份、学校、表号、原始行）。

## Workflow
1. `query_employment` 取指标；2. 用同类专业中位数做基准映射；3. 记录样本量与年份；4. 与需求侧指标分开存放。

## Tools
`query_employment`、`find_report_evidence`、`run_trend_analysis`

## Constraints
- **禁止**用招聘岗位数推算就业率（旧版 C21 的做法已废弃）；
- 缺失必须为 null；`C6 用人单位评价` 无调查数据时不得用 JD 推断。

## Evidence requirements
每条就业指标必须给出报告名称与统计截止时间；跨年份比较必须说明学制与口径差异。

## Failure handling
- 只有单年数据 → 不输出趋势，返回 `insufficient_evidence`；
- 学校未公开分专业数据 → 明示"该校未按专业披露"。

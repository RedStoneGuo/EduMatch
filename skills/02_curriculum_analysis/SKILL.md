# 02 Curriculum Analysis｜培养方案与课程分析

## Purpose
把"培养方案文本"变成结构化的课程实体，并进一步变成技能供给信号。

## When to use
- 需要回答"这个专业教了什么"；
- 需要计算课程对岗位技能的覆盖；
- 需要做培养方案模拟前的基线建模。

## Inputs
- 课程清单（来自档案抽取，或用户提供的真实培养方案）；
- `include_template`：是否纳入标记为 E 级的模板课程。

## Outputs
- 课程实体：`name / credits / category / is_practice / practice_hours / source_document`；
- 课程×技能矩阵与技能供给 `Supply(skill)`。

## Workflow
1. `query_curriculum` 取课程；
2. 调用技能本体把课程名与描述映射到统一技能实体（规则别名 + 层级传播）；
3. `calculate_skill_coverage` 得到 `Σ w_c`、`Supply = min(Σw_c / C_ref, 1)`；
4. 输出未映射课程清单，作为数据缺口。

## Tools
`query_curriculum`、`calculate_skill_coverage`

## Constraints
- 只做规则匹配不得直接产出匹配结论，必须进入 06 匹配模型；
- 模板课程必须带 `template=true` 与 `evidence_level=E`，不得混入 A/B 级结论。

## Evidence requirements
每门课程保存 `source_document`；学科级数据（学分、学时）必须能回到报告中的原句。

## Failure handling
- 该校课程证据 < 5 门 → 回退到同类专业跨校课程池，并在报告中明示回退原因与样本量；
- 未映射课程 → 列入 `unmapped_courses`，不静默丢弃。

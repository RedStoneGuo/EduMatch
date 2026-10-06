# Primary TSI 规范（Core TSI Engine）

> 本文件由 `scripts/gen_docs.py` 从 `analysis/primary_tsi.py` 生成，指标表与代码完全一致。
> 设计说明见 `docs/core_tsi_engine.md`。重新生成：`python scripts/gen_docs.py`

## 1. 定位

Primary TSI 是**唯一**对用户露出的正式主指标；TSI V1（27 三级指标）为
`historical_version`，TSI 2.0（四维 24 指标）为 `research_comparison` /
`benchmark_version`，只出现在报告 §16 与审计段落。

```
Primary TSI = 0.40·供需适配(F) + 0.20·培养基础(S) + 0.25·人才结果(O) + 0.15·需求背景(M)
Fit = Σ_s Demand(s)·min(Supply(s),1) / Σ_s Demand(s)      # analysis/fit.py，唯一实现
Gap(s) = Demand(s) − Supply(s)                            # 与 Fit 共用同一组向量
```

缺失指标记 `null` 并从加权分母剔除；维度覆盖率 < 0.34 时整维剔除并披露。

## 2. 指标明细

| 编号 | 指标 | 维度 | 维内权重 | 绝对权重 | 基础变量 | 变换 | 数据来源 | 计算公式 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| F1 | 技能适配度 | F_供需适配 | 0.45 | 0.18 | core.fit | `demand_weighted_fit_scaled_100` | 课程-技能矩阵+招聘需求 | S = Fit × 100，Fit = Σ_s Demand(s)·min(Supply(s),1)/Σ_s Demand(s) |
| F2 | 核心技能缺口严重度 | F_供需适配 | 0.3 | 0.12 | core.gap_index | `inverted_scaled_100` | 同一 Supply/Demand 向量 | S = (1 − min(SkillGapIndex/0.5, 1)) × 100 |
| F3 | 技能覆盖广度 | F_供需适配 | 0.15 | 0.06 | core.breadth_recall | `coverage_ratio_scaled_100` | 课程-技能矩阵 | S = 已覆盖需求技能数 / 需求技能总数 × 100 |
| F4 | 供给结构强度 | F_供需适配 | 0.1 | 0.04 | core.supply_channels | `structured_supply_share` | 课程属性通道 | S = 有必修/实践支撑的已覆盖技能数 / 已覆盖技能数 × 100 |
| S1 | 培养目标—岗位能力一致性 | S_培养基础 | 0.35 | 0.07 | semantic.objective_job_alignment | `semantic_similarity_scaled_100` | 教学质量报告+招聘需求 | S = calibrated_similarity × 100 |
| S2 | 师资结构达标度 | S_培养基础 | 0.3 | 0.06 | teaching.senior_title_ratio, teaching.student_faculty_ratio | `composite_ratio_map` | 教学质量报告 | S = 0.6·map(高级职称比例) + 0.4·map_lower(生师比) |
| S3 | 实践教学强度 | S_培养基础 | 0.2 | 0.04 | teaching.practice_credit_ratio | `ratio_map` | 教学质量报告 | S = map_ratio(实践学分占比, 参考基准) |
| S4 | 教学条件与实验资源 | S_培养基础 | 0.15 | 0.03 | teaching.training_base_count | `threshold_map` | 教学质量报告 | S = map_count(实训基地数, benchmark=3) |
| O1 | 毕业去向落实率 | O_人才结果 | 0.35 | 0.0875 | employment.placement_rate | `ratio_map` | 就业质量报告 | S = map_ratio(落实率, 同类专业中位数) |
| O2 | 就业稳定性 | O_人才结果 | 0.2 | 0.05 | employment.signing_rate | `ratio_map` | 就业质量报告 | S = map_ratio(签约率, 基准) |
| O3 | 深造结构合理性 | O_人才结果 | 0.15 | 0.0375 | employment.further_study_rate | `distance_to_benchmark` | 就业质量报告 | S = 100 − |深造率−同类中位数|/同类中位数 × 100 |
| O4 | 用人单位评价 | O_人才结果 | 0.3 | 0.075 | employment.employer_rating | `ordinal_satisfaction` | 就业质量报告/用人单位调查 | S = 满意度 × 100 |
| M1 | 技能需求强度 | M_需求背景 | 0.4 | 0.06 | market.skill_demand_mean | `demand_mean_scaled_100` | 招聘数据 | S = 平均 Demand(skill) × 100 |
| M2 | 新兴技能占比 | M_需求背景 | 0.3 | 0.045 | market.emerging_skill_share | `share_scaled_100` | 招聘数据 | S = 新兴技能岗位数 / 有效岗位数 × 100 |
| M3 | 岗位需求规模 | M_需求背景 | 0.15 | 0.0225 | market.effective_count | `ratio_map` | 招聘数据 | S = map_ratio(有效岗位数, 基期有效岗位数) |
| M4 | 薪资溢价 | M_需求背景 | 0.15 | 0.0225 | market.salary_premium | `capped_ratio_scaled_100` | 招聘数据 | S = min(溢价率/0.5, 1) × 100 |

## 3. 维度权重

| 维度 | 名称 | 权重 |
| --- | --- | --- |
| `F_供需适配` | 供需适配 | 0.4 |
| `S_培养基础` | 培养基础 | 0.2 |
| `O_人才结果` | 人才结果 | 0.25 |
| `M_需求背景` | 需求背景 | 0.15 |

## 4. 指标依赖图审计

- 指标节点：16
- double counting 分组：0（clean=True）
- 规则：同一基础变量 + 同一变换重复进入加权即视为 double counting；共享基础变量但业务定义不同者必须显式声明 primitives。

上游指标的完整依赖图见 `result['metric_graph']['primary']`；TSI 2.0 的重复输入审计见 `result['metric_graph']['v2_audit']`。

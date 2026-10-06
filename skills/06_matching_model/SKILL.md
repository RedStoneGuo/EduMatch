# 06 Matching Model｜供需匹配与缺口模型

## Purpose
在课程—技能—岗位—产业多层映射之上，计算需求加权匹配度与 Skill Gap。

## When to use
- 需要量化"培养方案覆盖了多少岗位需求"；
- 需要给出技能缺口排序；
- 需要比较方案改动前后的差异。

## Inputs
- `Supply(skill)`（来自 02）与 `Demand(skill)`（来自 04）；
- `C_ref` 参考学分（默认 6，可配置）。

## Outputs
- `matching_score`（0–1）/ `matching_score_100`；
- `SkillGapRow[]`：`demand / supply / gap / status / severity / confidence / evidence_level`；
- `skill_gap_index`。

## Workflow
1. `calculate_skill_coverage` 得到供给；
2. `query_skill_frequency` 得到需求与置信度；
3. `calculate_matching`：`Match = Σ Demand·min(Supply,1)/Σ Demand`；
4. `calculate_skill_gap`：`Gap = Demand − Supply`，`SkillGapIndex = Σ Demand·max(Gap,0)/Σ Demand`；
5. 与归档旧结论交叉核对，输出一致/分歧清单。

## Tools
`calculate_matching`、`calculate_skill_gap`、`calculate_skill_coverage`、`compare_schools`

## Constraints
- 禁止退化为 TF-IDF 余弦相似度；
- 双侧任一缺失 → gap 记 null（`insufficient_evidence`），不得记 0 或 1；
- 需求分项缺失时从分母剔除，并降低置信度。

## Evidence requirements
每条 gap 给出 `demand[] / supply[] / gap[]` 的证据链键名与置信度。

## Failure handling
- 可比技能为 0 → 返回 `insufficient_evidence` 并指出缺失的一侧；
- 供求尺度不一致 → 先检查 `C_ref` 与需求归一化口径，再重算。

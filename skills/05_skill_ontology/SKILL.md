# 05 Skill Ontology｜技能本体归一化

## Purpose
把课程文本、招聘 JD、政策文本中形态各异的技能表述，映射为统一技能实体，并向上传播到上位技能。

## When to use
- 任何跨文本源比较之前（课程 vs 岗位 vs 政策）；
- 出现 "PyTorch / torch / pytorch框架" 这类同义写法；
- 需要层级聚合（如把 RAG 计入 大模型 与 人工智能）。

## Inputs
- 自由文本；技能本体文件 `ontology/skill_ontology.yaml`。

## Outputs
- `SkillMention[]`：`surface / skill_id / matched_alias / match_type(exact|containment|propagation|semantic)`。

## Workflow
1. 归一化文本（大小写、全半角、标点）；
2. 精确别名命中；
3. 最长别名包含匹配，拉丁字母加边界校验（避免 "C" 命中 "CNN"）；
4. 沿本体向上传播到上位技能；
5. 可选：embedding / LLM 语义复核，复核结果标注为新 match_type 并单独记录置信度。

## Tools
内部 `edumatch.ontology.SkillOntology`；对外经 `calculate_skill_coverage` / `query_skill_frequency` 体现。

## Constraints
- 字符串匹配只是召回层，不得作为最终判定依据；
- 单字母别名（C）必须要求上下文确认；
- 同一技能多次命中取最长别名那次作为记录。

## Evidence requirements
保留命中别名与命中位置，便于人工复核误匹配。

## Failure handling
- 未命中但疑似技能 → 进入 `unmapped` 清单，由人工或 LLM 复核后扩展本体；
- 本体冲突（同一别名指向多个技能）→ 保留全部候选并标记待裁决。

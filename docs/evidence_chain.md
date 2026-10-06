# Evidence Chain（证据链）

## 1. 证据等级

| 等级 | 含义 | 典型来源 | 置信度基准 |
| --- | --- | --- | --- |
| A | 官方原始数据直接得到 | 政策 DOCX 原文、报告中的原始数值 | 1.00 |
| B | 官方数据计算得到 | 薪资归一化、比例映射、去重计数 | 0.85 |
| C | 多来源交叉计算 | 课程×技能×岗位的匹配与缺口 | 0.70 |
| D | 语义抽取或模型判断 | 人工/LLM 整理台账、词汇对齐度 | 0.50 |
| E | 证据不足 | 缺失字段 | 0.00 |

## 2. 证据条目结构

```json
{
  "evidence_id": "ev:employment:placement_rate",
  "source_type": "document",
  "title": "北京交通大学人工智能毕业去向落实率",
  "locator": "data/raw/majors_ai.txt",
  "quote": "计算机科学与技术学院 | 人工智能 | 42 | 57.14% | 90.48% | 90.48%",
  "year": 2024,
  "school": "北京交通大学",
  "evidence_level": "D",
  "confidence": 0.5
}
```

## 3. 结论 → 指标 → 计算 → 证据 的追溯

以"RAG 存在技能缺口"为例：

```
claim        "RAG 是该专业的重要技能缺口"
  ↓ metric   Gap(RAG) = Demand(RAG) − Supply(RAG)
  ↓ calc     demand=0.10  supply=0.17  gap=−0.07  status=balanced
  ↓ demand   ev:market:aggregate  ← AI竞赛数据归档/输出过程记录/招聘.txt（D 级）
  ↓ supply   course_skill_matrix  ← 课程《大模型应用开发》等（E 级模板课程，已标注）
  ↓ evidence trace_claim 输出 demand[]/supply[]/gap[] 三个证据键
```

工具调用：`trace_claim(claim="RAG 存在技能缺口")` 返回逐技能的 `calculation` 与 `evidence_level`。

## 4. 三项强制披露

1. **缺失披露**：`tsi_v2.missing_indicators` 列出所有 `null` 指标及原因；
2. **口径披露**：`market.counts_status = aggregate_only`，
   `course_scope.reason` 说明是否发生跨校回退；
3. **分歧披露**：`skill_gaps.reported_gap_crosscheck` 把归档旧结论（D 级）
   与模型计算缺口并列，标出 `consistent` / `model_disagrees` / `unknown`。

## 5. 反审计用例

| 反模式 | 本系统的阻断点 |
| --- | --- |
| LLM 编造分数 | 分数只在 `analysis/` 生成；解释层只接收已算好的数字 |
| 假引用 | 每条证据必须有 `locator`；无 locator 的记录不入库（测试 M7 = 1.0） |
| 缺失记 0 | `MetricValue.missing()` 强制 `value=None, evidence_level='E'`（测试 M9 = 1.0） |
| 因果断言 | `mechanism.guard_causal_language` + 评测 M8 扫描（当前 0.0 违规） |
| 无样本量排名 | `benchmark.rankable` 需满足最小样本量，否则不排序 |

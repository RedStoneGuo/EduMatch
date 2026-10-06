# Evidence 框架

## 1. 证据链

```
Source → Evidence → Metric → Score → Interpretation → Recommendation
```

任何一个重要数字都能反查：来源文件 / 页码或位置 / 原始文本 / 抽取结果 / 映射 Skill /
计算逻辑 / 最终指标。实现：

- `edumatch/evidence.py`：`EvidenceItem`（含 `locator`、`quote`、`page`、`url`、
  `retrieval_time`、`evidence_level`、`confidence`）与 `MetricValue`
  （含 `detail.source_metric`、`formula`）；
- `analysis/tsi_tree.py`：把 Primary TSI 逐层展开到每个技能的需求 / 供给证据；
- 引擎报告 §17 Evidence Chain、§18 审计与复现。

## 2. 证据等级（A–E，保留）

| 等级 | 含义 | 默认置信度 |
| --- | --- | --- |
| A | 官方原始数据直接得到 | 1.0 |
| B | 官方数据计算得到 | 0.85 |
| C | 多来源交叉计算 | 0.7 |
| D | 语义抽取或模型判断 | 0.5 |
| E | 证据不足 | 0.0 |

## 3. 强制规则

1. **No evidence ≠ Negative evidence**：没有检索到 ≠ 不存在。
   必须写"未检索到公开证据"或"当前证据不足"。
2. **缺失 ≠ 0**：缺失记 `None`，不参与加权分母。
3. **弱代理要标明**：`analysis/semantic.py` 的字符 bigram 是**代理指标**（D 级），
   其 0 分必须与"证据不足"区分显示（见 `audit/tsi_audit.md` §3.1）。
4. **不为完成任务虚构数据**：无法获取的数据不填 0、不猜测、不伪造；示例数据必须
   明确标注 `Demo / Example / Synthetic / Illustrative`。

## 4. Evidence Conflict Resolver

当引擎结果与高等级原始证据冲突时（典型：课程材料明确含 Python，但结构化映射给出
Python 供给 0），走 `analysis/conflict_resolution.py`：

```
Engine Result → Evidence Cross-check(A/B) → Skill Mapping Review → 局部修正
→ 只重算受影响技能及其上层指标 → 保存新旧结果 → 记录修正理由
```

记录字段：`original_result / reconciled_result / evidence_source / mapping_reason /
changed_skill / recalculation_scope / timestamp / run_id`。
**禁止**因一个技能冲突而无理由重跑整个系统。

## 5. 高校资料覆盖状态机

搜索到 URL ≠ 已覆盖。`edumatch/coverage_state.py` 定义：

```
DISCOVERED → SOURCE_VERIFIED → DOWNLOAD_ATTEMPTED → FILE_VALIDATED
→ ORIGINAL_FILE_SAVED → TEXT_EXTRACTED → READY_FOR_ANALYSIS
```

只有 `READY_FOR_ANALYSIS` 计入覆盖；输出 `target / covered / coverage_rate /
successful_documents / missing_universities / failure_reasons`。

## 6. 自动质量门

`scripts/validate_edumatch.py` 检查：

- 数值：TSI ∈ [0,100]、权重和 = 1、无 NaN / 非法负值；
- TSI：正式总分唯一、Match 未作第二总分；
- Missing：证据不足的指标 value 必须为 None；
- 语义：报告不得残留"总供给 / 总需求 / 把 16,161 说成岗位需求数 / 13 所代表全市"等表述（否定语境除外）；
- 证据链：有值指标必须带证据 ID 或打分依据。

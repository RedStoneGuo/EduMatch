# EduMatch 评测报告

生成时间：2026-10-04T16:27:20

## 指标结果

| 指标 | 数值 | 说明 |
| --- | --- | --- |
| M1_extraction_accuracy | 0.4 | {"n": 10, "by_scope": {"major": {"hit": 4, "total": 4, "value": 1.0}, "school": {"hit": 0, "total": 6, "value": 0.0}}, " |
| M2_normalisation_accuracy | 1.0 | {"n": 10, "misses": []} |
| M3_evidence_recall | 1.0 | {"n": 12} |
| M4_numeric_consistency | 1.0 | {"engine": 0.7765, "manual": 0.776532} |
| M5_tsi_repeatability | 1.0 | {"tsi": 55.39} |
| M6_gap_repeatability | 1.0 | {"gap_index": 0.0375} |
| M7_citation_completeness | 1.0 | {"n_evidence": 260} |
| M8_hallucination_rate | 0.0 | {"n_reports": 12, "patterns": ["导致", "证明了", "必然导致", "决定了就业"]} |
| M9_missing_handling | 1.0 | {} |
| M10_tool_call_success | 1.0 | {"n_calls": 158} |
| M11_job_market_integrity | 1.0 | {"counts": {"raw_count": 128379, "deduplicated_count": 35145, "effective_count": 35133, "note": "raw=全部来源原始行数；deduplicat |
| M12_literature_retrieval | 0.9661 | {"n_works": 59, "source": "openalex", "robots": {"api.openalex.org": "User-agent: * / Allow: /"}} |

## 标准测试案例

通过 12/12

| 案例 | 期望模式 | 实际模式 | 通过 | TSI | 匹配度 | Gap | 工具数 | 缺失指标 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| TC01 | E_skill_gap | E_skill_gap | ✅ | 55.25 | 0.7765 | 0.0375 | 13 | 6 |
| TC02 | B_school_major_analysis | B_school_major_analysis | ✅ | 51.74 | 0.5765 | 0.0906 | 14 | 9 |
| TC03 | C_benchmark | C_benchmark | ✅ | 55.25 | 0.7765 | 0.0375 | 13 | 6 |
| TC04 | D_trend | D_trend | ✅ | 55.25 | 0.7765 | 0.0375 | 13 | 6 |
| TC05 | E_skill_gap | E_skill_gap | ✅ | 55.25 | 0.7765 | 0.0375 | 13 | 6 |
| TC06 | F_policy_mechanism | F_policy_mechanism | ✅ | 55.25 | 0.7765 | 0.0375 | 13 | 6 |
| TC07 | G_curriculum_simulation | G_curriculum_simulation | ✅ | 55.39 | 0.7765 | 0.0375 | 14 | 6 |
| TC08 | H_full_report | H_full_report | ✅ | 55.39 | 0.7765 | 0.0375 | 14 | 6 |
| TC09 | B_school_major_analysis | B_school_major_analysis | ✅ | 50.86 | 0.7765 | 0.0375 | 13 | 9 |
| TC10 | A_major_analysis | A_major_analysis | ✅ | 53.03 | 0.7765 | 0.0375 | 13 | 6 |
| TC11 | F_policy_mechanism | F_policy_mechanism | ✅ | 55.25 | 0.7765 | 0.0375 | 13 | 6 |
| TC12 | A_major_analysis | A_major_analysis | ✅ | 55.25 | 0.7765 | 0.0375 | 13 | 6 |

## 旧版 baseline 对比

- 旧版公式复算 TSI：49.929
- 旧版报告（LLM）写出的 TSI：70.0
- 二者差：20.07
- 旧版 27 指标中记 0 分的数量：13（48.1%）
- 记 0 的指标：A13, A24, B12, B22, B31, B32, B33, B41, B42, B51, C11, C31, C33
- TSI 2.0：55.39，缺失指标 6 个，覆盖率 100.0%
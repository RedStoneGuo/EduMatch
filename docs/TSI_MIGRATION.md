# TSI 迁移说明（旧 → 新）

> 目的：能解释"为什么新系统与旧报告结果不同"，并保证旧字段、旧接口不被破坏。

## 1. 唯一正式总分

```
Primary TSI = 0.40·F_供需适配 + 0.20·S_培养基础 + 0.25·O_人才结果 + 0.15·M_需求背景
```

`primary_tsi` 是**唯一**对用户露出的正式总分；其余版本只作对照：

| 版本 | 角色 | 处理 |
| --- | --- | --- |
| `primary_tsi` v`primary-3.0` | formal / primary | 唯一正式总分 |
| `tsi_v1` v1.0（27 三级指标） | historical_version | 仅 §16 历史对照 |
| `tsi_v2` v2.0（24 指标，含 B1≡C4 重复输入） | research_comparison / benchmark_version | 仅 §16 与研究对照 |

## 2. 旧指标 → 新指标

| 旧指标 | 新规范 | 变化原因 | 数据来源 | 计算变化 | 兼容方式 |
| --- | --- | --- | --- | --- | --- |
| 岗位匹配度 `match` / `match_100` | `structural_fit` / `structural_fit_100`（子指标） | 与 F1 技能适配度同一数学形式，被误当作第二总分 | 岗位族需求向量 + 课程供给 | 计算不变，仅降级与改名 | 保留旧键，新增别名 |
| `matching_score` / `matching_score_100` | `skill_fit` / `skill_fit_100` | 命名统一到 Fit 主线 | 同 Fit | 计算不变 | 保留旧键，新增别名 |
| `tsi_score` / `tsi_value` | `primary_tsi` | 对外统一一个正式总分字段 | 同 Primary TSI | 计算不变 | 保留旧键，新增别名 |
| 旧 Coze 基线（把 13/27 个"信息不足"指标记 0 分，49.93 vs 报告 70.00） | 缺数据记 `None` + `insufficient_evidence` | 缺失不等于低能力 | 同 | 缺失不参与加权分母 | 旧基线仅留历史说明 |
| 供给侧 `course_set` 课程池 | `SupplyProfile.skill_supply` | 需要统一四层对象 | 同 | `from_supply_vector` 适配，数值不变 | 原 `SupplyVector` 保留 |
| 需求侧岗位向量 | `JobProfile.skill_requirements` | 统一岗位画像 Schema | 同 | `from_demand` 适配 | 原向量保留 |

兼容实现：`edumatch/profiles.py::apply_legacy_compat`；映射表 `canonical_field_map()`。

## 3. 为什么新结果可能与旧报告不同

1. **移除重复加权**：旧 TSI 2.0 的 B1 与 C4 输入完全相同（C4 写作 `0.5·m4 + 0.5·m4`），
   同一匹配结果被加权两次；Primary TSI 移除该重复并按统一 Fit 主线重建供需适配维。
2. **缺失不再记 0**：旧版把"信息不足"记 0 会系统性压低分数；新版缺失不进入分母，
   但会用维度覆盖率与置信度披露。
3. **数量口径与覆盖口径修正**：招聘记录改为 Observed Job Posting Demand，
   高校供给改为"覆盖样本"，不再声称区域总量——这会改变结论的**表述**，不改变计算。
4. **Match 不再并列**：Match 仍可计算，但只是子指标；读者看到的头条数字是 Primary TSI。

## 4. S1 弱代理 0 值：已修复（2026-10-05）

**问题**：`S1 培养目标—岗位能力一致性` 由 TF-IDF 字符余弦计算，低于校准下限时被压成
`0.0` 输出，调用方只判断"是否为 None"，于是把"文本不足以判断"读成"完全不一致"，
S1 恒为 0，并把 S_培养基础 从约 77 拉到 50.22。同时"培养目标"抽取还会把
"拓展型培养方案 / 课程修读要求"当成目标原文。

**修复（三层）**：

1. 契约：`analysis/embeddings.py` 低于下限 → `similarity=None`（不再记 0）；
   `analysis/tsi.py::_alignment` 只接受 `status=ok` 的值。
2. 度量：新增 `analysis/objective_alignment.py`，S1 = **需求加权单侧覆盖**：

   ```
   S1 = Σ_{s∈Demand, 培养目标文本命中 s} w(s) / Σ_{s∈Demand} w(s)
   ```

   并做培养目标有效性校验（拒样板段落）、多来源并集覆盖、命中技能可列出。
3. 抽取：`edumatch/engine.py` 扫描培养方案 / 专业介绍正文（按专业名严格匹配），
   记录候选与依据；找不到可核查目标原文时 S1 = `insufficient_evidence`（不记 0）。

**结果**：宏观 S1 0.3882（覆盖 17/91 项需求能力，Primary TSI 61.07 → 64.12）；
中观（北工大）本地只有课程表、无培养目标段落 → S1 记证据不足，S 维按覆盖率剔除并披露。
旧字段与旧接口未删除；`tests/test_objective_alignment.py` 锁定该契约。

## 5. 版本与复现

每次运行记录 `run_id / timestamp / data_version / ontology_version / model_version /
prompt_version`，并保存输入快照、证据快照、计算结果与输出报告。
自动检查：`python scripts\validate_edumatch.py`（数值 / 唯一性 / 缺失 / 语义 / 证据链）。

# Core TSI Engine 升级：当前架构 → 目标架构

> 本文件是本次重构的**审查与设计记录**。所有结论都来自对实际代码与最近一次
> 运行产物（`data/processed/case_reports/*/result.json`、`data/processed/runs/*/result.json`）
> 的核对，不是按提示词推测。
>
> 配套实现说明见 `docs/core_tsi_engine.md`（改造后的正式规范）。

## 1. 现状审查（改造前）

### 1.1 代码入口

| 环节 | 入口 | 说明 |
| --- | --- | --- |
| TSI 计算入口 | `analysis/tsi.py::score_indicators/compute_tsi` | TSI 2.0，四维 24 指标 |
| 旧版 TSI | `analysis/tsi_v1.py::compute_v1` | 27 个三级指标 A/B/C，权重取自 `TSI指标搭建.docx` |
| Skill Match 入口 | `analysis/matching.py::build_course_skill_matrix` / `demand_weighted_match` | 学分加权覆盖 |
| Skill Gap 入口 | `analysis/skill_gap.py::compute_skill_gaps` | `Gap = Demand − Supply` |
| Benchmark 入口 | `analysis/benchmark.py::benchmark_table` + `engine._benchmark_context` | 就业/教学指标横向比较 |
| 报告入口 | `agent/report.py::render_markdown` | 18 节，指标驱动 |
| 数据 schema | `edumatch/dataset.py`, `edumatch/evidence.py` | `EducationFact` / `CourseRecord` / `MetricValue` / `EvidenceItem` |
| Agent/Skill/MCP | `agent/core.py` → `edumatch/engine.py` → `analysis/*`；`skills/*`；`mcp_servers/server.py` | 确定型流水线 + 可选 LLM 解释层 |
| 可复现运行 | `python -m agent.runner --query "..." --simulate --template` → `data/processed/runs/<run_id>/` | run_id 由 query/mode/major/school/开始时间哈希 |

### 1.2 当前数据流

```
query ──plan──> family(ai/cs/econ) + school?
                     │
     ┌───────────────┼───────────────────────────────┐
     ▼               ▼                               ▼
 课程(course_set)  招聘(jobs.json)                报告/政策 PDF
     │               │                               │
 course×skill矩阵  demand_vector(SkillDemand)    教学/就业事实
     └──────┬────────┘                               │
            ▼                                        │
     matching(需求加权覆盖) ──> skill_gap             │
            │                                        │
     tsi_v2(24指标) + tsi_v1(27指标, 并行输出) <───────┘
            │
     benchmark(就业/教学横向) · trend · mechanism(样本不足即 insufficient)
            │
        report.md（指标驱动，18 节）
```

### 1.3 已核实的问题（含证据）

| # | 问题 | 证据 |
| --- | --- | --- |
| P1 | 研究尺度以"某高校某专业"为中心 | `build_plan` 只有 `family + school`；无 industry/occupation/major_family 层 |
| P2 | TSI 更像"教育质量综合评价" | `tsi_v2` A/B/C 维权重合计 0.70 描述办学条件与结果，只有 B1/B6/C4 涉及供需 |
| P3 | Supply/Fit/Gap/TSI 未形成统一数学主线 | `matching` 与 `skill_gap` 各自独立实现；TSI 通过 `context["matching"]` 间接引用 |
| P4 | 指标重复计入同一匹配结果 | V1：`B11` 与 `C23` 输入完全相同（均为 `matching_score_100`），合计绝对权重 0.0995；V2：`C4 = 0.5·m4 + 0.5·m4 ≡ m4`，与 `B1` 完全相同，合计绝对权重 0.10 |
| P5 | Skill Supply ≈ "课程是否出现该技能" | `matching.course_weight` 只用学分与 `is_practice`；矩阵元素为 0/1，无必修/选修、深度、实验/项目、培养目标通道 |
| P6 | 跨校课程池回退替代了目标高校真实供给 | `engine._curriculum`：目标校课程 < 5 门即整体换成北京 211 课程池。实跑"北京工业大学_软件工程"`course_scope.scope=cross_school_pool`，目标校实际只有 1 门课程，供给却按 22 门池计算 |
| P7 | 正式 TSI 不唯一 | `engine.run` 同时产出 `tsi_v1`(54.95) 与 `tsi_v2`(48.74)；报告 §10 标题为"TSI（主口径 V1）"、§10.1 为"TSI 2.0" |
| P8 | Benchmark 不是供需适配基准 | `_benchmark_context` 指标集 = 落实率/签约率/深造率/实践学分/高级职称，全部是教育背景指标 |
| P9 | 机制分析直接 `insufficient_evidence` | `_mechanism_context` 的 `n_paired_observations = 0`（实践学分与落实率无同校配对），无政策—产业—岗位—技能—课程路径 |
| P10 | 趋势模块为"有模块"而输出 | `_trend_context` 对同一年多点/单点也输出"2022→2022 变化 …"；`trend.series_summary` 不过滤同年重复，也不要求 ≥2 个**不同**年份 |
| P11 | 报告把研究结论、系统日志、数据审计混排 | 18 节以 A11…D7 指标表为主体，结论散落在各节 |

## 2. 目标架构（本次改造）

```
Beijing (region)
  └─ industry ──> occupation ──> major_family ──> institution ──> major
                        │
       ┌────────────────┴────────────────┐
       ▼                                 ▼
  Demand Vector                     Supply Vector ×2
  (需求强度/岗位覆盖/            ┌── Target Supply（目标高校真实课程）
   岗位族覆盖/趋势/稳定性)      └── Peer Benchmark Supply（北京同类专业池）
       └────────────┬───────────────┘
                    ▼
            Skill Fit（统一主线，唯一实现）
                    ▼
            Skill Gap（核心解释结果）
                    ▼
   Primary TSI = 0.40·Fit + 0.20·培养基础 + 0.25·人才结果 + 0.15·需求背景
   (指标依赖图去重；V1/V2 降级为历史/对比版本)
                    ▼
   机制（政策—产业—岗位—技能—课程 关联路径，明确非因果）
                    ▼
   培养方案模拟（Gap → 课程 → ΔSupply → ΔFit → ΔPrimary TSI）
                    ▼
   三层报告：Executive（发现） / Research（画像与矩阵） / Audit（run_id/证据/公式）
```

### 2.1 核心对象与唯一数学主线

```
Supply(s) = min( Σ_c w_credit·m_required·m_depth·(1+m_practice) / C_ref + β·1[培养目标命中 s], 1 )
Demand(s) = Σ_k W_k·component_k(s) / Σ_k W_k     （仅用可用分量，缺项不进分母）
Fit       = Σ_s Demand(s)·min(Supply(s),1) / Σ_s Demand(s)
Gap(s)    = Demand(s) − Supply(s)                 （Fit 与 Gap 共用同一 Supply/Demand 向量）
PrimaryTSI= Σ Dimensions(可用维度) 加权平均
```

`Fit` 只有一份实现（`analysis/fit.py`），`matching.py` 与 `skill_gap.py` 都调用它，
消除"三套评分体系"。

### 2.2 模块改造清单

| 模块 | 处理 | 内容 |
| --- | --- | --- |
| `analysis/supply.py` | 新增 | 连续型 Skill Supply Score + 供给通道分解（覆盖/学分/必修选修/多课覆盖/深度/实践/实验项目/培养目标） |
| `analysis/fit.py` | 新增 | 统一 Skill Fit（唯一实现），`matching` 改为委托 |
| `analysis/matching.py` | 重构（保接口） | 权重与 supply 由 `supply.py` 提供；保留 `CourseSkillMatrix` 字段与数值兼容 |
| `analysis/demand.py` | 新增 | 需求向量的统一封装（频率/岗位覆盖/岗位族覆盖/薪资溢价/政策相关/趋势/稳定性） |
| `analysis/metric_graph.py` | 新增 | 指标依赖图 + double counting 检测器 |
| `analysis/primary_tsi.py` | 新增 | Primary TSI 3.0（四维去重指标）；V1/V2 作为版本登记 |
| `analysis/benchmark.py` | 升级 | 新增技能级基准与"目标 vs 基准 vs 市场"三角比较 |
| `analysis/mechanism.py` | 升级 | 新增 `association_path`：政策主题→产业方向→技能需求→课程覆盖→缺口 |
| `analysis/trend.py` | 升级 | 同年去重、≥2 个不同年份才出结论、新增"市场变化 vs 培养响应"同步分析 |
| `edumatch/engine.py` | 重构 | Target/Peer 供给分离；Primary TSI 接入；机制/趋势/基准/数据质量块 |
| `agent/report.py` | 重构 | 三层输出 + 发现驱动 18 节（保留 18 节结构以兼容评测 TC08） |
| `config/config.yaml` | 扩展 | `core_model` 段：目标课程门槛、C_ref、供给通道权重、Primary TSI 维度权重 |
| `tests/test_core_model.py` | 新增 | 供给通道、Target/Peer 分离、Fit/Gap 闭合、单一 Primary TSI、无 double counting、趋势门槛 |
| `docs/core_tsi_engine.md` | 新增 | 改造后正式规范（对象定义、公式、指标表、依赖图、版本策略） |

### 2.3 兼容性承诺（不得丢失）

- `tsi_v1` / `tsi_v2` 键与 27/24 指标结构、`evaluation` 阈值（M1–M12）保持可读；
- `course_skill_matrix` / `matching` / `skill_gaps` 键保持存在且自洽（M4 手工复算仍成立）；
- Evidence Chain、run_id、可复现性、缺失记 null、LLM 不产数值等硬约束不变。

## 3. 验收对照

| 验收点 | 落地位置 |
| --- | --- |
| 统一 Supply/Demand/Fit/Gap/TSI | `analysis/supply.py`+`fit.py`+`primary_tsi.py` |
| 无 double counting | `analysis/metric_graph.py` + `tests/test_core_model.py` |
| Target 与 Peer 严格分离 | `engine.run` 的 `supply.target/peer` 与 `skill_fit.target/peer` |
| 只有一个 Primary TSI | `result["primary_tsi"]`；报告仅 Executive/Research 露出主分 |
| Skill Supply 不再是 0/1 | `analysis/supply.py` 的通道分解与连续分 |
| 缺失影响可信度 | `result["data_quality"]` + 报告 §15 |
| 发现驱动报告 | `agent/report.py` §1–§6 发现区 |

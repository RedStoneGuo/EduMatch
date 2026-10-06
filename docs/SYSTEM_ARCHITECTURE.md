# 系统架构（多尺度教育—就业供需适配）

> 定位：**以 Primary TSI 为核心评价结果、以 Evidence Chain 为可信基础、
> 以 Knowledge–Skill–Capability–Practice 为供需匹配骨架、以宏观—中观—微观三尺度为
> 决策入口、以 Agent + Simulation 为决策辅助的教育—就业智能分析系统。**
> 本文件描述改造后的目标架构与现有代码的对应关系。

## 1. 四层架构

```
应用层      Government(宏观)      Faculty(中观)        Student(微观)
            区域人才结构           专业培养适配          个人证据诊断
                          │（同一套 TSI 哲学）
多尺度层    evaluate_macro / evaluate_middle / evaluate_micro
            RegionalProfile / MajorProfile / PersonalEvidenceProfile
                          │
核心引擎    Supply Profile ↔ Demand Profile
            Knowledge / Skill / Capability / Practice 四层比较
            Fit · Gap · ConflictResolver · Scenario · Simulation
            唯一正式总分 Primary TSI + TSI Tree
                          │
数据知识层  高校 · 专业 · 课程 · 学生证据 · 技能本体 · 岗位 · 政策
            Evidence Chain（A–E 级，可回溯到来源文件 / 页码 / 原文）
```

## 2. 现有代码映射

| 架构层 | 现有模块 | 状态 |
| --- | --- | --- |
| 数据知识层 | `edumatch/dataset.py`、`edumatch/ontology.py`、`data/` | 保留 |
| 证据链 | `edumatch/evidence.py` | 保留（A–E） |
| 四层对象 | `edumatch/profiles.py` | 新增 |
| 能力推断 | `analysis/capability.py` | 新增 |
| 供给构造 | `analysis/supply.py` | 保留 |
| 需求构造 | `analysis/demand.py`、`edumatch/occupation.py` | 保留 |
| 匹配 / 缺口 | `analysis/fit.py`、`analysis/skill_gap.py`、`analysis/occupation_match.py` | 保留 |
| 冲突消解 | `analysis/conflict_resolution.py` | 新增 |
| 场景切片 | `analysis/scenario.py` | 新增 |
| 唯一总分 | `analysis/primary_tsi.py` | 保留 |
| 分解展示 | `analysis/tsi_tree.py` | 新增 |
| 模拟 | `analysis/simulation.py` | 保留（重定位待做） |
| 报告 | `agent/report.py`（18 节） | 保留 |
| 展示 | `EduMatch-演示页面/` | 改造（Primary TSI + TSI Tree + 语义） |
| 质量门 | `scripts/validate_edumatch.py` | 新增 |

## 3. 三尺度 = 一个模型的三个投影

三尺度共享：同一 Skill Ontology、同一 Evidence Chain、同一 Fit/Gap 主线和
同一 Primary TSI 计算逻辑；只是 `SupplyProfile.scale` 与需求范围不同：

| 尺度 | SupplyProfile.scale | 供给对象 | 需求对象 |
| --- | --- | --- | --- |
| 宏观 | `regional` | 覆盖高校培养能力 | 岗位大类可观察招聘记录 |
| 中观 | `major` | 某校某专业培养方案 | 目标岗位族 |
| 微观 | `personal` | 个人证据（L0–L4） | 具体岗位 |

**三尺度分值不直接横向比较**，因为评价对象不同。

## 4. 确定性计算 + Agent 解释

- Python（`analysis/`、`edumatch/`）负责数据处理、指标计算、归一化、加权、TSI、聚合、Simulation；
- Agent（`agent/llm.py`、报告渲染）负责检索、证据抽取、语义理解、Skill Mapping、冲突识别、
  机制解释、推荐、场景选择；
- **LLM 不产出最终数字**；所有最终数值可由确定性程序重算。

## 5. 可复现性

每次运行记录 `run_id / timestamp / data_version / ontology_version / model_version /
prompt_version`，并保存输入快照、证据快照、计算结果与输出报告；同一输入可重算同一结果。
`scripts/validate_edumatch.py` 提供数值、TSI 唯一性、缺失语义、证据链与报告口径的自动检查。

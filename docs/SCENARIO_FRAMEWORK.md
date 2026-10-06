# Scenario 框架

## 1. 不追求场景指数爆炸

禁止机械生成"4 层能力 × 5 个场景 × 3 个尺度"，避免几十上百份报告。
采用 **Dynamic Scenario Selection**：先按用户目标挑有价值的切片，再切片，并硬性封顶。

实现：`analysis/scenario.py`

- `select_dimensions(goal_text, max_dimensions=3)`：按目标关键词给维度打分排序；
- `plan_scenarios(goal_text, jobs, max_dimensions=3, max_scenarios=12)`：
  输出选中的维度、可行切片与 `n_total_before_cap / capped`；
- `slice_jobs(jobs, dimension, value)`：确定性切片，无样本时返回 `insufficient_evidence`。

## 2. 维度优先级

| 维度 | id | 说明 | 优先级 |
| --- | --- | --- | --- |
| 岗位类型 | `job_type` | 岗位族 / 具体岗位 | 高 |
| 技术链 | `task_chain` | 模型训练 / Fine-tuning / RAG / Agent / Evaluation / Deployment / Data Engineering / AI Application | 高 |
| 经验要求 | `experience_requirement` | 应届 / 1-3 年 / 3-5 年 / 5 年以上 | 中 |
| 行业 | `industry` | 金融 / 医疗 / 制造 / 教育 / 政务 / 互联网 / 能源 / 汽车 | 中 |

示例：

- 学生说"我想成为大模型算法工程师" → 优先 `job_type + task_chain + experience_requirement`；
- 学生说"我想进入金融 AI" → 优先 `industry + job_type + capability`。

## 3. 中观主要场景

专业 × 岗位类型 / 行业 / 工作经验要求 / 工作任务·技术链。
**学历**作为资格约束（Eligibility），**薪资**作为市场切片（Market Segmentation），
二者不做 TSI 核心维度。

## 4. Simulation 的定位（Phase 7）

Simulation 是**决策辅助工具**，不是 Agent 的上级约束：

```
Agent（证据分析 / 政策 / 产业 / 教育逻辑 / 推荐）
        ↓ 可形式化的方案
   Simulation（若实施该措施，结构性变化可能如何）
        ↓ 量化证据
   回到 Agent 解释与建议
```

Agent 可以基于教育逻辑先提出建议；不能因为"写不成优化变量"就禁止提建议。
Simulation 回答的是"如果实施，大概率出现怎样的结构性变化"，输出 ΔFit / ΔTSI / 缺口减少。

## 5. 报告中的场景

每个场景切片必须带：`dimension / value / n_jobs / status`，并标明该切片是
**可观察样本**；样本不足时如实标注 `insufficient_evidence`，不做推断。

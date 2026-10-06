# Supply / Demand 框架

## 1. 统一供需结构

供给与需求使用**同一套四层 Schema**，逐层比较：

```
Knowledge Supply  ↔  Knowledge Demand
Skill Supply      ↔  Skill Demand
Capability Supply ↔  Capability Demand
Practice Supply   ↔  Practice Demand
        │
        ▼
Fit → Gap（critical / emerging / coverage / practice）→ Primary TSI
```

代码：

- 供给：`edumatch/profiles.py::SupplyProfile`、`analysis/supply.py::build_supply_vector`
- 需求：`edumatch/profiles.py::JobProfile`、`analysis/demand.py`
- 比较：`analysis/fit.py::skill_fit`（唯一实现）、`analysis/skill_gap.py`
- 缺口对象：`edumatch/profiles.py::Gap`、`gaps_from_fit`

## 2. 四层定义

| 层 | 定义 | 例子 | 现有数据 |
| --- | --- | --- | --- |
| Knowledge | 理论与知识基础 | 数学基础、机器学习、深度学习、Transformer、大模型原理、数据结构、数据库 | ✅ 课程池可支撑 |
| Skill | 可执行技术技能 | Python、PyTorch、RAG、Prompt、Agent、模型微调、模型部署、数据处理 | ✅ 引擎已产出 |
| Capability | 综合解决问题的能力（≠ Skill） | 算法研发、模型训练、AI 工程开发、应用设计、模型评测、研究创新 | 🟡 由 Knowledge+Skill+Practice 确定性推断，需求侧数据待补 |
| Practice | 真实任务经历 | Learning / Project / Industry / Research Practice | 🟡 课程实践通道已有；产业实践待补 |

能力推断规则：`analysis/capability.py::infer_capabilities`

```
Capability(c) = Σ_r w_r · min(Supply(layer_r, item_r), 1) / Σ_r w_r   # 仅可用分量
```

缺失分量不进分母，并在 `missing_components` 中披露——缺数据不等于能力为 0。

## 3. 语义边界

- **招聘记录**只能作为 `Observed Job Posting Demand`（可观察职位发布需求）使用；
  不得把招聘记录表述成区域或全国范围的需求总量，也不得表述为就业人口规模。
- **高校课程池**只能作为"覆盖高校的培养能力供给"；不得表述为区域总供给。
- **学历**是 `Eligibility Constraint`（是否满足门槛），不是"越高 TSI 越高"。
- **薪资**是 `Market Segmentation Variable`（市场切片），不直接进入 TSI 主体。
- **政策 / 产业**是分析变量：`Policy → Industry → Job → Skill → Education` 只输出
  关联路径（`association_path`），不做因果断言。

## 4. 缺失值规则

- 缺失记 `None` + `status='insufficient_evidence'`，**不记 0**；
- 缺失不进入加权分母；
- 维度覆盖率低于阈值时整维剔除并披露；
- 口径内确认为"未见供给"时，才记 `supply_basis='absent_in_scope'` 的 0（可审计假设）。

## 5. 三尺度供给 / 需求向量

| 尺度 | Supply | Demand |
| --- | --- | --- |
| 宏观 | Regional Supply（覆盖高校培养能力） | Macro Demand（岗位大类可观察记录） |
| 中观 | Major Supply（某校某专业） | Job-Family Demand（目标岗位族） |
| 微观 | Personal Supply（个人四层证据） | Specific Job Demand（具体岗位 JD） |

三者共享 Skill Ontology 与 Evidence Chain，但**读数不互相换算**。

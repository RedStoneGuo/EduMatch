# 统一 Profile Schema（Supply / Demand / Personal）

> 代码实现：`edumatch/profiles.py`（对象定义）、`analysis/capability.py`（能力推断）、
> `edumatch/personal_extract.py`（自然语言抽取）。
> 本文件是"宏观 / 中观 / 微观共用同一套 Schema"的正式说明；三个尺度只换观察对象，
> 不换字段定义。

## 0. 总原则

- 四层能力：**Knowledge → Skill → Capability → Practice**，是供需两侧比较的共同骨架。
- 缺失值一律 `None` + `status='insufficient_evidence'`，**不记 0**；缺失不进入加权分母。
- `education_requirement` 是**资格约束**，`salary_segment` 是**市场切片变量**，
  二者都不进入匹配主体；进入匹配主体的是四层向量。
- 所有数值来自 `analysis/` 的确定性函数；Agent/LLM 不产出数字。

## 1. SupplyProfile（高校 / 专业 / 个人 通用）

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `scale` | str | 是 | `regional` / `major` / `personal` |
| `knowledge_supply` | dict[str, float\|null] | 否 | 知识层供给，key=知识项 |
| `skill_supply` | dict[str, float\|null] | 否 | 技能层供给（引擎 `SupplyVector.score` 适配） |
| `capability_supply` | dict[str, float\|null] | 否 | 能力层，由 `analysis/capability.py` 确定性推断 |
| `practice_supply` | dict[str, float\|null] | 否 | 实践层（Industry / Project / Learning Practice） |
| `graduate_profile` | list[dict] | 否 | 毕业生画像条目（培养目标 / 毕业要求） |
| `evidence` | list[str] | 否 | 证据 ID 列表 |
| `coverage` | dict[str, Any] | 自动 | 每层已填字段占比（`refresh_coverage()` 生成） |
| `confidence` | dict[str, Any] | 自动 | 分层置信度 |
| `provenance` | str | 否 | `target` / `peer` / `observed` 等证据来源类型 |
| `status` / `reason` | str | 否 | `ok` / `insufficient_evidence` 及原因 |
| `meta` | dict[str, Any] | 否 | 通道明细、课程数、可靠度等审计信息 |

兼容：`SupplyProfile.from_supply_vector(vec)` 直接适配现有
`analysis.supply.SupplyVector`；`skill_supply` 逐值等于引擎输出，不重算。

## 2. JobProfile（统一岗位画像，spec §26）

| 字段 | 类型 | 进入匹配主体 | 说明 |
| --- | --- | --- | --- |
| `job_family` | list[str] | 否 | 岗位族 |
| `industry` | list[str] | 否 | 行业（场景切片变量） |
| `experience_requirement` | list[str] | 否 | 经验要求（场景切片变量） |
| `education_requirement` | list[str] | 否（**约束**） | 学历门槛：是否满足，而非"越高越好" |
| `knowledge_requirements` | dict[str, float\|null] | 是 | 知识需求 |
| `skill_requirements` | dict[str, float\|null] | 是 | 技能需求（引擎 `DemandVector`） |
| `capability_requirements` | dict[str, float\|null] | 是 | 能力需求 |
| `practice_requirements` | dict[str, float\|null] | 是 | 实践需求 |
| `task_chain` | list[str] | 否 | 工作任务 / 技术链切片 |
| `technology_stack` | list[str] | 否 | 技术栈 |
| `salary_segment` | dict[str, Any] | 否（**切片**） | 薪资分位：用于市场分层，不直接进 TSI |
| `evidence` | list[str] | 否 | 证据 ID |

兼容：`JobProfile.from_demand(demand, occupation=..., demand_meta=...)`。

## 3. PersonalEvidenceProfile（微观，spec §21–§24）

| 字段 | 说明 |
| --- | --- |
| `knowledge_evidence` / `skill_evidence` / `capability_evidence` / `practice_evidence` | 四层证据条目列表 |
| `evidence_strength` | 条目 → 确定性强度（自述=粗粒度档位，不是能力分值） |
| `coverage` / `confidence` | 覆盖率与置信度 |
| `sparse_level` | L0 仅学校+专业+年级+岗位；L1 +课程；L2 +技能；L3 +项目；L4 +实习/科研/作品/成果 |
| `declared` | 用户自述信息（含 `absences`：明确声明的"没有/不会"） |

要点（spec §23、§29）：

- L0 输出为 **Major Baseline**，必须写明"专业基准推断，不是真实个人能力判断"；
- "没有正式实习"记入 `declared.absences`，**不等于** practice=0，也不等于证据不足；
- 自然语言入口：`PersonalEvidenceProfile.from_text(text)`，规则抽取、可复现。

## 4. Gap（统一缺口对象）

| 字段 | 说明 |
| --- | --- |
| `skill` | 缺口对应的知识/技能/能力/实践项 |
| `layer` | `knowledge` / `skill` / `capability` / `practice` |
| `demand` / `supply` / `gap` | 同一 Supply/Demand 向量导出的数值 |
| `category` | `critical` / `emerging` / `coverage` / `practice` |
| `severity` | `high` / `medium` / `low` / `unknown` |
| `supply_basis` | `covered` / `absent_in_scope`（口径内未见供给） |
| `evidence_ids` | 证据链 |

微观报告至少分别输出 **Knowledge Gap / Skill Gap / Experience-Practice Gap**，
不得把三者合成一个数字。

## 5. TSIResult 与兼容层

`Primary TSI` 是唯一正式总分；`match` 降级为子指标。

| 旧字段 | 新规范 | 处理方式 |
| --- | --- | --- |
| `match` | `structural_fit` | 保留旧键 + 增加规范别名 |
| `match_100` | `structural_fit_100` | 保留旧键 + 增加规范别名 |
| `matching_score` / `matching_score_100` | `skill_fit` / `skill_fit_100` | 保留旧键 + 增加规范别名 |
| `tsi_score` / `tsi_value` | `primary_tsi` | 保留旧键 + 增加规范别名 |

实现：`edumatch.profiles.apply_legacy_compat(payload)`，并把别名关系写入
`payload["legacy_fields"]` 供审计。映射表由 `profiles.canonical_field_map()` 暴露。

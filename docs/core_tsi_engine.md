# Core TSI Engine｜北京高等教育人才供需适配核心引擎（正式规范）

> 版本：`primary-3.0`　实现：`analysis/supply.py`、`analysis/demand.py`、`analysis/fit.py`、
> `analysis/skill_gap.py`、`analysis/primary_tsi.py`、`analysis/metric_graph.py`、
> `analysis/benchmark.py`、`analysis/mechanism.py`、`analysis/trend.py`、`edumatch/engine.py`、
> `agent/report.py`
>
> 本规范中所有指标权重、维度权重与依赖关系都由 `tests/test_core_model.py` 断言，
> 代码与文档不一致时测试会失败。
> 指标明细表由 `python scripts/gen_docs.py` 生成到 [docs/core_tsi_spec.md](core_tsi_spec.md)。

## 1. 定位与研究层级

### 1.1 模型输入 / 输出（目标岗位匹配）

```
输入：院校 + 专业 + 目标岗位
       ↓
  岗位解析（edumatch/occupation.py）→ 岗位族（大模型算法 / CV / NLP / 算法 / 数据工程 /
      数据分析 / AI应用 / MLOps / AI产品 / 人工智能相关岗位全部）
       ↓
  Demand_occ = 只由该岗位族岗位计算的技能需求向量
  Supply     = 研究对象自身口径的供给向量（院校专业，或未点名时的区域课程池）
       ↓
  岗位匹配度 = Σ_s Demand_occ(s)·min(Supply(s),1) / Σ_s Demand_occ(s)
       ↓
  匹配带（高度匹配 ≥0.80 / 较匹配 ≥0.65 / 部分匹配 ≥0.45 / 匹配不足）
  + 覆盖技能数、缺失技能清单、岗位定义性技能缺口、岗位学历结构、基准对照
```

要点：

- **岗位需求只用该岗位族的岗位**，不与"全市场 AI 岗位"混用（例如大模型算法工程师的
  `大模型` 权重明显高于全市场口径）；
- **岗位族定义性技能**（`typical_skills`）即使未被文本抽取到，也以最小权重进入分母，
  否则"课程从没教过 Transformer"这类事实会被漏掉；
- 目标岗位解析不到 / 岗位样本 < 30 条 → 返回 `insufficient_evidence` 并说明原因，
  不猜岗位、不用其他岗位族的数据；
- 岗位匹配度与 Primary TSI 使用**同一个** `analysis/fit.py` 主线，不存在第二套评分。

**调用方式**

```powershell
python -m agent.runner --list-occupations
python -m agent.runner --query "分析北京工业大学人工智能专业与大模型算法工程师岗位的匹配度" --occupation "大模型算法工程师" --simulate --template
python scripts\batch_school_analysis.py --major 人工智能 --schools 北京工业大学 --occupation "大模型算法工程师"
```

Python API：`ResearchEngine.run(query, target_occupation="大模型算法工程师")`；
结果写入 `result["occupation"]`（岗位切片/需求/要求）与 `result["occupation_match"]`
（匹配度、匹配带、技能明细），并作为 `JOB1` 指标进入 `result["metrics"]`。

**输入契约**

| 输入 | 必填 | 说明 |
| --- | --- | --- |
| 院校 | 否 | 给出则供需适配/岗位匹配只用该校证据；未给出则研究对象为北京同类专业课程池（区域口径，显式披露） |
| 专业 | 是 | 解析到 ai / cs / econ 族；未知专业如实拒绝 |
| 目标岗位 | 否 | 给出则输出岗位匹配度；未给出时，若问题含"岗位/匹配度"等意图且为 ai 族，默认"人工智能相关岗位（全部）" |

Core TSI Engine 不是"评价某高校某专业好不好"，而是**建立北京高等教育人才供需适配的统一量化模型**。
高校专业只是当前的分析粒度，底层对象已按下列层级组织，向上可直接扩展到区域与产业，
向下可扩展到专业与个人：

```
Beijing(region) → industry → occupation → major_family → institution → major → curriculum
                                                                              ↘ student → target_job
```

`ResearchPlan` 目前落在 `major_family + institution` 一层，但供给向量、需求向量、Fit/Gap
三个对象都与粒度无关：换一组 course 记录或一组 job postings 即可复用同一套数学。

## 2. 五个核心对象与唯一数学主线

```
Supply Vector    Skill Supply Score  ∈ [0,1]    来自培养方案（课程-技能边 + 通道权重）
Demand Vector    Skill Demand Score  ∈ [0,1]    来自招聘数据（仅用可用分量）
Skill Fit        Σ_s D(s)·min(S(s),1) / Σ_s D(s) ∈ [0,1]
Skill Gap        Gap(s) = D(s) − S(s)
Primary TSI      四维加权（供需适配 / 培养基础 / 人才结果 / 需求背景）
```

**唯一实现**：`analysis.fit.skill_fit`。`analysis.matching.demand_weighted_match` 只是它的
兼容包装（保留历史字段 `matching_score` / `per_skill`），`analysis.skill_gap` 使用同一组
Supply/Demand 向量计算差值，因此 Fit 与 Gap 永远闭合：

```
gap(s) == demand(s) − supply(s)     # analysis/fit.fit_gap_closure 逐行校验
```

### 2.1 供给侧：连续型 Skill Supply Score

```
w(c,s) = credits(c) · required_factor(c) · depth_factor(c) · practice_factor(c)
Supply(s) = min( Σ_{c: s∈skills(c)} w(c,s) / C_ref  +  β · 1[培养目标命中 s] , 1 )
```

| 通道 | 取值 | 数据不可用时的处理 |
| --- | --- | --- |
| 覆盖（多门课程） | 逐门累加，天然体现"多门课程共同覆盖" | — |
| 学分 | 缺失时中性 1.0，并在 `credits_imputed` 标记 | 中性值，非 0 |
| 必修/选修 | 必修 ×1.15；选修 ×0.85 | 来源未说明 → ×1.0，记入 `unavailable_channels` |
| 教学深度 | 导论 0.90 / 核心 1.10 / 进阶 1.20 / 研究 1.15 | 未说明 → ×1.0 |
| 实践（实验/项目/实习） | 实践课 ×1.2；实践学时 +min(学时/64, 0.5) | 无实践信息 → 不加成 |
| 培养目标 | 命中则 +β（默认 0.10，可配置） | 无培养目标文本 → 不启用 |

`C_ref`（默认 6 学分）是**参考教学量**而不是总学分：多门课程共同覆盖同一技能时供给趋近 1，
从而与需求强度同量纲可比。模板课程（`template=True`，E 级）只进入 Peer 基准池，
**绝不进入任何高校的 Target Supply**。

### 2.2 需求侧：Skill Demand Score

```
Demand(s) = Σ_k W_k · component_k(s) / Σ_k W_k      （仅对可用分量求和）
```

| 分量 | 权重 | 定义 | 当前数据 |
| --- | --- | --- | --- |
| frequency | 0.25 | 岗位中出现该技能的频率 | 可用 |
| position_coverage | 0.20 | 覆盖的岗位比例 | 可用 |
| occupation_coverage | 0.15 | 覆盖的岗位族（不同岗位名称）比例，30% 视为满分 | 可用 |
| salary_premium | 0.10 | 该技能岗位相对市场中位的薪资溢价 | 可用 |
| policy_relevance | 0.15 | 政策文本相关度（背景变量） | 可用 |
| industry_weight | 0.05 | 产业方向权重（背景变量） | 可用 |
| trend | 0.05 | 跨期变化 | 单期数据 → `null` |
| stability | 0.05 | 需求普遍性/稳定性 | 单期数据 → `null` |

缺失分量不参与分子分母，并在 `demand_vector.unavailable_components` 中披露。

## 3. Primary TSI（正式主指标）

```
Primary TSI = 0.40·F 供需适配 + 0.20·S 培养基础 + 0.25·O 人才结果 + 0.15·M 需求背景
```

| 维度 | 权重 | 指标（维内权重） |
| --- | --- | --- |
| F 供需适配 | 0.40 | F1 技能适配度(0.45)、F2 核心技能缺口严重度(0.30)、F3 技能覆盖广度(0.15)、F4 供给结构强度(0.10) |
| S 培养基础 | 0.20 | S1 培养目标—岗位能力一致性(0.35)、S2 师资结构达标度(0.30)、S3 实践教学强度(0.20)、S4 教学条件与实验资源(0.15) |
| O 人才结果 | 0.25 | O1 毕业去向落实率(0.35)、O2 就业稳定性(0.20)、O3 深造结构合理性(0.15)、O4 用人单位评价(0.30) |
| M 需求背景 | 0.15 | M1 技能需求强度(0.40)、M2 新兴技能占比(0.30)、M3 岗位需求规模(0.15)、M4 薪资溢价(0.15) |

打分口径（与 TSI 2.0 保持一致，保证可比）：

- 连续型 `S = clamp(60 + (raw/benchmark − 1)·40, 0, 100)`；
- 语义型 `S = calibrated_similarity × 100`（D 级证据，provider 与余弦同时披露）；
- F2 为反向表达：`S = (1 − min(SkillGapIndex/0.5, 1)) × 100`；
- F3 为广度（不加权覆盖比例），F4 为结构（被覆盖技能中由必修或实践支撑的比例）；
- 维度分 = 可用指标加权平均；维度覆盖率 < 0.34 时整维剔除；
- 综合分 = 可用维度按权重归一化后的加权平均。

**分层最小规则**：指标缺证据 → `null`；维度缺覆盖率 → 剔除并披露；从不记 0。

**定义性维度**：`F_供需适配` 是 Primary TSI 的定义性维度。它不可用时
（`missing_required_dimensions` 非空）Primary TSI **不予计算**并给出
`not_computable_reason`——不允许用剩下的人才结果或需求背景拼一个数字冒充"适配度"。

## 4. 指标依赖图与 double counting 审计

每个指标在 `analysis/metric_graph.py` 中登记 `primitives`（基础变量）与 `transform`（变换）：

```
(frozenset(primitives), transform) 相同  →  同一测量被重复加权
```

- `Primary TSI` 的依赖图必须是 `clean = True`（`tests/test_core_model.py` 断言）；
- `TSI 2.0` 的审计**故意**检出 `B1 ≡ C4`：两者都取 `matching_score_100`
  （C4 写作 `0.5·m4 + 0.5·m4`，恒等于 m4），合并绝对权重 0.10，这是旧版 double counting 的直接证据；
- 允许共享基础变量，但必须通过不同的 `transform` 或不同的 `primitives` 表达不同业务定义
  （例如 F1 用 `core.fit`，F2 用 `core.gap_index`）。

运行结果中：`result["metric_graph"]["primary"]["audit"]` 与 `result["metric_graph"]["v2_audit"]`。

## 5. Target Supply 与 Peer Benchmark 严格分离

| 口径 | 内容 | 用途 |
| --- | --- | --- |
| Target Supply | 目标高校**本校**可核查课程（`provenance="target"`） | Primary TSI 的供需适配维、目标校画像 |
| Peer Benchmark Supply | 北京同类专业课程池（含 E 级模板课程） | Benchmark、三角比较、区域基准 |

规则：

1. 目标校课程在本校证据中不足 `min_target_courses`（默认 3）时，`status_label="partial_evidence"`，
   仍是**该校自己的证据**，只是标注为"保守下界"，并在 Primary TSI 中把 F 维指标置信度 ×0.5；
2. 目标校完全没有可核查课程时，`status_label="insufficient_evidence"`，Primary TSI 的 F 维为 `null`
   并整维剔除，**不使用基准值替代**；
3. 两种情况下 `peer` 向量都独立计算并公开，形成
   `目标高校 VS 北京同类专业基准 VS 市场需求` 三角比较（`analysis/benchmark.triangle`）；
4. 模板课程、学校未识别的课程只进入 peer 池。

运行结果中：`result["supply"]["target"|"peer"]`、`result["skill_fit"]["target"|"peer"]`、
`result["course_scope"]["used_for_fit"]`、`result["benchmark"]["triangle"]`。

### 5.1 证据不足优先于替代（硬约束）

**规则：数据不足时返回 `insufficient_evidence`，绝不编造，也不用其他院校/其他专业族/其他侧的数据顶替。**

| 场景 | 正确行为 | 禁止行为 |
| --- | --- | --- |
| 点名高校但该校无该专业族课程 | `supply.target = null`；`skill_fit.target.status = insufficient_evidence`；供需适配维整维剔除 | 用北京同类专业课程池冒充该校供给 |
| 未点名高校 | 区域课程池是**研究对象本身**（`used_for_primary = region_pool`，显式披露） | 把区域口径说成某校结论 |
| 岗位语料不覆盖该专业族 | 该族关键词覆盖率 < 30% 时需求向量为空 + 说明原因 | 用 AI 岗位语料充当经济管理需求 |
| 课程属于其他专业族 | 按来源文件归属（`course_family_of`），其他族课程不进入本族课程池 | 用 AI 专业课程给软件工程评分 |
| 高校缺该专业口径就业数据 | 允许回退到**同校**校级口径并标注 `fallback=school_level_of_same_school` | 用其他院校的就业率 |
| 指标缺证据 | `value=None` + `evidence_level=E`，从加权分母剔除 | 记 0、或用同类基准中位数填成"该校的值" |

同类基准中位数只用于"相对基准打分"（`map_ratio_to_score`），它出现在
`benchmark`、`benchmark_detail` 与三角比较中，**永远不会**作为研究对象自身的取值。
未指定高校时，区域口径即研究对象（例如"北京市重点高校人工智能专业供需适配"），
此时 Primary TSI 的供需适配维使用区域课程池，并在 `primary_tsi.supply_scope.scope_note` 中说明。

## 6. Skill Gap：核心解释结果

```
Gap(s) = Demand(s) − Supply(s)                       # 同一组向量
SkillGapIndex = Σ_s D(s)·max(Gap(s),0) / Σ_s D(s)    # 只累计正向缺口
severity: critical(gap≥0.35 且 D≥0.6) > material(≥0.20 且 D≥0.4) > moderate(>0.15) > balanced
          ; Gap < −0.15 → oversupply
```

`unlisted_supply_is_zero`：当供给向量与需求向量在同一技能全集内构建（即"已经把这门专业的课程
逐条对照过全部需求技能"）时，需求技能在课程口径内**从未出现**记为供给 0，并标注
`supply_basis="absent_in_scope"`；需求侧缺失仍记 `null`。这是"市场重要技能、课程从未覆盖"
能够进入缺口结论的前提。

> 注意：`unlisted_supply_is_zero` 是对外可关闭的开关，默认 `False`（任意两组向量的保守比较）；
> 引擎在专业分析中显式打开，并在 `skill_gaps.method_note` 与报告 §7 中披露。

## 7. 机制分析：政策—产业—岗位—技能—课程 关联路径

`analysis/mechanism.association_path` 输出可计算的**关联路径**：

```
政策主题（重点产业方向） → 政策文本提及技能 → 岗位需求 D(s) → 课程覆盖 S(s) → 缺口 G(s)
```

- 状态为 `association_path` 或 `insufficient_evidence`，不存在"沉默的空结果"；
- 明确标注"关联路径，非因果"；样本不足时**不**输出效应量；
- 统计部分（相关、置换重要性）只在样本量达标时输出，`guard_causal_language` 统一约束表述。

`result["mechanism"]["association_path"]`。

## 8. 趋势：市场变化是否被培养体系响应

1. 同一年内的重复观测按中位数合并为一个"期"，并公布 `n_samples`；
2. 少于 2 个**不同年份** → `insufficient_evidence`，不输出变化值；
3. `trend.response_analysis(market, curriculum)` 只做方向性判断：
   市场上升 + 课程未上升 → 响应滞后或覆盖不足；两侧无多期数据 → `insufficient_evidence`。

## 9. Benchmark：从高校排行榜到供需结构解释

- 保留教育背景指标（落实率/签约率/深造率/实践学分/高级职称）作为**背景**，`min_n` 不足时不排序；
- 核心改为技能级基准 `benchmark.skill_benchmark`：
  同一技能下 `目标校供给 / 北京同类基准供给 / 市场需求 / 目标缺口 / 与基准差`；
- `benchmark.triangle` 输出画像差异与解释性结论，明确"不产出高校排行榜"。

## 10. 报告三层输出

| 层 | 章节 | 内容 |
| --- | --- | --- |
| Executive View | §1–§2 | 六个发现（市场需要什么 / 高校在培养什么 / 差在哪里 / 核心缺口 / 为什么 / 调整后改善什么）+ Primary TSI 总览 |
| Research View | §3–§14 | 数据与方法、需求画像、目标供给、区域基准、Skill Fit/Gap、技能矩阵、供给通道、三角比较、趋势、机制、模拟、矛盾与建议 |
| Audit View | §15–§18 | 数据质量与可信度、版本策略、Evidence Chain、run_id/公式/指标依赖图/复现命令 |

正式主指标只在 Executive 与 Research 层出现；`tsi_v1` / `tsi_v2` 只在 §16 以
`historical_version` / `research_comparison` / `benchmark_version` 的身份出现，
因此最终输出**只有一个正式 TSI 总分**。

## 11. 结果结构（`data/processed/**/result.json` 关键键）

| 键 | 含义 |
| --- | --- |
| `primary_tsi` | 正式主指标：`primary_tsi`、`band`、`dimensions`、`metrics`、`dependency_graph`、`versions`、`supply_scope` |
| `supply.target` / `supply.peer` | 目标校与区域基准供给向量（强度、通道、可靠度、状态） |
| `demand_vector` | 需求向量：`score`、`meta`、`rows`、`unavailable_components` |
| `skill_fit.target` / `skill_fit.peer` | 两个口径的 Fit 与逐技能明细（含 `gap`、`supply_basis`） |
| `skill_gaps` / `skill_gaps_target` / `skill_gaps_peer` | 主用口径与两个口径的缺口结果 |
| `benchmark.skill_benchmark` / `benchmark.triangle` | 技能级基准与三角比较 |
| `mechanism.association_path` | 政策—产业—岗位—技能—课程 关联路径 |
| `trends.response` | 市场变化 vs 培养响应 |
| `data_quality` | 数据覆盖检查项、可信度判断、缺失清单 |
| `metric_graph.primary.audit` / `metric_graph.v2_audit` | 指标依赖与 double counting 审计 |
| `tsi_v1` / `tsi_v2` | 历史版本与研究对照版本（结构与旧版一致，可直接读取旧结果） |

## 12. 兼容性与保留能力

- `tsi_v1`（27 三级指标）与 `tsi_v2`（四维 24 指标）键、结构、公式不变，旧 `result.json` 仍可读取；
- `course_skill_matrix` / `matching` / `skill_gaps` 仍存在且相互自洽，
  评测 M4（手工复算匹配度）继续成立；
- Evidence Chain、run_id、数据缺失显式 `null`、LLM 不产生数值、招聘数据去重、
  培养方案模拟、JSON + Markdown 输出、Skill Ontology 全部保留；
- 报告保留 18 个编号章节（评测 TC08 依赖 `## 1.` … `## 18.`），只是重排为发现驱动。

## 13. 未来扩展路径（同一底座的三个视角）

| 视角 | 供给向量 | 需求向量 | 输出 |
| --- | --- | --- | --- |
| 学生 | 个人课程/项目/证书 → Skill Vector | 目标岗位 Demand | Personal Fit、个人 Skill Gap |
| 专业负责人 | Major Supply | Peer Benchmark + Market Demand | Curriculum Simulation（ΔFit/ΔTSI） |
| 政府 | Regional Supply（专业群/高校集合） | Industry Demand + Policy | 结构性缺口、政策情景模拟 |

三者共用 `analysis/supply.py`、`analysis/demand.py`、`analysis/fit.py` 与 `analysis/skill_gap.py`，
不需要为每个视角重写评分逻辑。

## 14. 验收与测试

```powershell
python -m pytest tests -q                  # 含 tests/test_core_model.py（11 项核心模型断言）
python scripts\core_model_upgrade_report.py   # 3 个已有专业 + 1 个全市口径的改造前后对照
python scripts\run_evaluation.py           # M1–M12 与 12 个标准案例
python demo\export_static.py               # 离线演示页
```

检查清单：

- [x] 统一 Supply/Demand/Fit/Gap/TSI（`analysis/fit.py` 唯一实现，`fit_gap_closure` 校验）
- [x] 无 double counting（Primary 依赖图 `clean=True`，V2 的 B1≡C4 被审计检出）
- [x] Target Supply 与 Peer Benchmark 严格分离（含 `partial_evidence` / `insufficient_evidence` 两档）
- [x] 只有一个正式 Primary TSI（V1/V2 降级为历史与研究对照）
- [x] Skill Supply 不再是 0/1 课程出现指标（六通道连续分解）
- [x] 缺失数据影响可信度（`data_quality` + 报告 §15）
- [x] 主报告发现驱动，审计信息保留不淹没结论

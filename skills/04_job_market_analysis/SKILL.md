# 04 Job Market Analysis｜招聘需求分析

## Purpose
把招聘数据变成可解释的"需求强度"信号，而不是岗位条数或就业率。

## When to use
- 计算 D 类（市场需求）指标；
- 识别技能需求强度、新兴技能、薪资溢价；
- 为 Skill Gap 提供需求侧输入。

## Inputs
- 逐条岗位表（company/position/city/salary/education/experience/description/publish_time/source/url/crawl_time），或聚合招聘证据。

## Outputs
- `raw_count / deduplicated_count / effective_count` 三口径计数；
- 技能需求向量 `Demand(skill)`（0–1）与各分项可用性。

## Workflow
1. `crawl_jobs`（合规、默认关闭）或读取既有数据集；
2. `normalize_job` 归一化公司/岗位/城市/薪资，生成指纹；
3. `deduplicate_jobs` 做精确去重与近似重复识别；
4. `query_skill_frequency` 计算需求向量，缺失分项从分母剔除；
5. 披露时间窗口、城市过滤、样本量与口径。

## Tools
`crawl_jobs`、`normalize_job`、`deduplicate_jobs`、`search_jobs`、`query_job_statistics`、`query_skill_frequency`、`query_salary`、`query_job_trend`

## Constraints
- 遵守 robots.txt 与服务条款，不绕过验证码/登录/反爬；
- 不得把网页条数当真实需求；同一岗位跨页面重复必须去重；
- 招聘数据不得用于推断毕业生胜任度。

## Evidence requirements
每条岗位保留 `source / url / crawl_time`；统计口径必须与岗位表版本对应。

## Failure handling
- 无逐条数据（仅聚合证据）→ 计数记 null，需求强度按可得分项计算并降低置信度；
- 只有单期数据 → 趋势类指标记 null。

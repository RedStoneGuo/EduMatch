# 数据模型

存储选择：**SQLite**（`data/db/edumatch.sqlite`）。
理由：数据量适中（795 文档 / 739 事实 / 145 政策 / 40 技能），SQLite 随 Python 内置、
零部署、便于随比赛作品打包；原始与中间产物同时以 JSON 保存在 `data/processed/`，便于 diff 与复现。

## 表结构

| 表 | 主键 | 作用 | 关键字段 |
| --- | --- | --- | --- |
| `documents` | doc_id | 归档全部文件的元数据与可抽取性 | relative_path, category, school, years, text_status |
| `schools` | school_id | 高校 | name, is_211, city |
| `majors` | major_id | 专业 | name, family, major_code |
| `education_facts` | fact_id | 供给侧结构化事实 | school, year, major, fact_type, value, unit, source_document, source_line, evidence_level |
| `skills` | skill_id | 技能本体实体 | name, category, parents, children, aliases |
| `courses` | course_id | 课程实体 | school, year, name, credits, is_practice, source_document |
| `course_skills` | (course_id, skill_id) | 课程→技能边 | match_type, confidence |
| `jobs` | job_id | 逐条岗位（HAR 导入，当前 73 条） | company, position, salary_min/max, education, job_description, fingerprint, dataset_id, search_keyword, source_job_id |
| `job_skills` | (job_id, skill_id) | 岗位→技能边（当前 263 条） | weight |
| `market_evidence` | dataset_id | 聚合招聘证据 | payload, source_document, evidence_level, n_postings |
| `policies` | policy_id | 政策文书 | title, agency, year, industry_direction, skills_related, text_status |
| `evidence` | evidence_id | 证据条目（按运行） | run_id, locator, quote, evidence_level, confidence |
| `metrics` | (run_id, metric_id) | TSI 指标值 | value(null 合法), status, confidence, reason |
| `scores` | (run_id, key) | 维度/总分 | value, dimension, payload |
| `analysis_runs` | run_id | 运行审计 | user_query, plan, tool_calls, skill_calls, metrics, scores, evidence, timestamps |

## 关键设计决策

1. **`metrics.value` 允许 NULL**：数据库层面就禁止"缺失即 0"的旧习惯；
2. **三层计数**：`jobs` 保留 `fingerprint` / `content_key` / `is_duplicate`，
   使 `raw_count / deduplicated_count / effective_count` 可随时重算；
3. **证据双向可查**：`evidence.evidence_id` 出现在 `metrics.evidence_ids` 中，
   也可由 `evidence.run_id` 反查整轮分析；
4. **政策方向用 JSON 数组**：`industry_direction` / `skills_related` 便于跨文档聚合；
5. **不存原始 PDF 内容**：归档保持只读，数据库只存定位符与抽取结果。

## 构建与检查

```powershell
python scripts/archive_inventory_report.py   # 795 条文档元数据 + 覆盖率报告
python scripts/build_database.py             # 建库并装载全部结构化数据
python scripts/gen_docs.py                   # 从代码生成 TSI/MCP/Skill 文档
```

## 当前装载结果

```
documents 795 · schools 21 · education_facts 739 · skills 40
courses 22 · course_skill_edges 40 · policies 145（去重 2） · market_evidence 1
jobs 73（raw 100） · job_skills 263 · literature 59 篇
```

## 岗位数据的来源与三口径

岗位表由 `scripts/import_har_jobs.py` 从用户本人浏览器的 HAR 抓包导入
（合规路径说明见 [auto_pipeline.md](auto_pipeline.md)）：

| 口径 | 数值 | 含义 |
| --- | --- | --- |
| `raw_count` | 100 | 各分页响应中出现的岗位行数（含跨页/跨搜索重复） |
| `deduplicated_count` | 73 | 按「公司+岗位+城市+薪资区间」指纹去重后的岗位数 |
| `effective_count` | 73 | 其中具备可用描述/技能、能支撑需求估算的岗位数 |

新增列用于溯源与合规：`dataset_id`、`search_keyword`、`city_code`、`work_type`、
`company_size`、`salary_detail`、`source_job_id`。
`db.migrate()` 会对既有数据库做幂等 ALTER，不丢数据。

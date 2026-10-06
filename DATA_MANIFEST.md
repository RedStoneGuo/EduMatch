# 数据清单与恢复方式

本仓库是 **EduMatch** 的公开发布包：**代码、提示词、模板、以及"跑得起来的最小数据充分集"**。
原始材料（合计约 4.5 GB，其中 6 个文件超过 GitHub 的 100 MB 单文件上限）不在仓库内，
按下面说明放回即可恢复完整能力。

## 这个包里带了什么

| 内容 | 路径 | 说明 |
| --- | --- | --- |
| 全库课程库 | `data/raw/supplementary_courses.json` | 22 所院校 · 42,401 门可核查课程（培养方案解析结果） |
| 通用招聘语料 | `data/processed/jobs.json` | AI/计算机关键词岗位 16,387 条（需求主口径） |
| 就业事实 | `data/processed/pdf_facts.json` | 26 所院校的就业率/签约率/师资/实践学分等（来自就业与教学质量报告） |
| 分专业就业行 | `data/processed/pdf_major_rows.json` | 18 所院校 · 320 个专业的落实率/签约率/深造率 |
| 全量语料紧凑索引 | `data/processed/full_corpus_index.json` | 72759 行（63.3 MB）——**任意专业**需求侧兜底 |
| 同城薪资基线样本 | `data/processed/jobs_baseline_sample.json` | 10000 行（23.5 MB）——薪资溢价基线 |
| 政策库（预解析缓存） | `data/processed/policies.json` | 145 条政策记录（由 147 份政策原文预解析；政策—产业维度） |
| 采集台账 | `data/source/采集台账/` | 材料索引与采集记录 |

## 这个包里**没有**什么（以及为什么）

| 未包含 | 体积 | 原因 |
| --- | --- | --- |
| `data/source/培养方案|课程大纲|专业介绍|年度报告|政策文件`（原始文件） | 约 4.5 GB | 超仓库建议上限；含 6 个 >100 MB 的单文件（最大 443 MB），GitHub 直接拒绝。政策原文已预解析成 `policies.json`（147 个文件 → 1 个文件，运行时等价） |
| `data/raw/pdf_text/`（正文缓存） | 约 1.1 GB | 可由 PDF 重新抽取 |
| `data/processed/major_jobs/`（专业作用域岗位语料全量） | 577 MB | 已用紧凑索引覆盖"任意专业兜底"；如需精确专业语料可按命令重建 |
| `data/source/招聘数据/招聘岗位数据_v2总表.csv` 等原始表 | 436 MB | 超单文件上限 |
| `北京人工智能简历数据.xlsx` | 31 MB | **含真实个人履历，隐私原因不入公开仓库** |

## 恢复全量能力（把数据放回后按序执行）

```powershell
# 0) 把原始材料放回对应目录
#    data/source/培养方案/<院校>/、data/source/年度报告/<院校>/{就业质量报告,教学质量报告}/
#    data/source/招聘数据/*.csv|xlsx

python scripts\import_extra_text.py                                # PDF/docx → 正文缓存
python scripts\import_supplementary.py --all --force --max-mb 80   # 培养方案 → 课程库
python scripts\reextract_pdf_facts.py                              # 正文 → 就业/教学事实
python scripts\extract_pdf_major_rows.py                           # 就业报告 → 分专业就业行
python scripts\merge_job_exports.py                                # 全部岗位表 → 需求端语料
python scripts\relativize_paths.py                                 # 派生件路径改回相对路径
python scripts\audit_data_coverage.py                              # 复核材料利用率
```

## 数据来源与口径

* 教育侧：各校官方《本科培养方案》《毕业生就业质量报告》《本科教学质量报告》《课程大纲》《专业介绍》；
* 需求侧：公开招聘平台岗位导出表（含岗位名、公司、城市、学历、经验、薪资、职责、行业）；
* 缺失一律记 `null` 并在报告中标注「未获取」，**不补位、不估算、不用其它专业/院校的数据顶替**。

# 第三方组件与数据来源说明

## 1. 联网采集插件：`vendor/edu-material-harvest/`

| 项目 | 说明 |
| --- | --- |
| 来源仓库 | <https://github.com/shoucunren-tsy/edu-material-harvest> |
| 在本项目中的作用 | **唯一的联网采集通道**。EduMatch 通过 `edumatch/source_modes.py::run_plugin_harvest` 调用它的 MCP 工具，采集目标院校/同类院校的公开材料（培养方案、专业介绍、课程大纲、年度报告、就业质量报告、教学质量报告），并支持"入口 A 全站/栏目"与"入口 B 承载页直采"两条路径 |
| 使用方式 | 本地子进程 + MCP（stdio），随包 `vendor/` 目录一起分发，**不做二次修改** |
| 许可证 | 以**上游仓库**为准，请在使用/再分发前确认其授权条款。本仓库（EduMatch）自身的 MIT 许可**不覆盖**该目录 |
| 合规约束 | 项目红线：联网只走此插件；域名必须先经「官方教育域 + HTTP 200 + 页面含校名」核验，**绝不猜域名**；遇到反爬/拦截时如实记录失败原因，不绕过 |

如需把本系统用于生产环境，建议直接从上游仓库获取该插件的最新版本，替换 `vendor/edu-material-harvest/`。

## 2. 数据来源

本仓库**不包含**任何原始一手材料（PDF/Excel 等），只包含由它们派生的结构化数据与一份招聘语料索引。详见根目录 `DATA_MANIFEST.md`。

派生物的来源类别：

| 类别 | 原始来源 | 本仓库中的形态 |
| --- | --- | --- |
| 培养方案 / 课程大纲 / 专业介绍 | 各高校教务处、本科招生网公开文件 | `data/raw/supplementary_courses.json`（课程库） |
| 毕业生就业质量报告 / 本科教学质量报告 | 各高校信息公开栏目公开文件 | `data/processed/pdf_facts.json`、`pdf_major_rows.json` |
| 招聘岗位数据 | 公开招聘平台岗位导出表 | `data/processed/jobs.json`、`full_corpus_index.json`、`jobs_baseline_sample.json` |
| 政策文件 | 教育部、人社部、北京市人社局等公开政策原文 | `data/processed/policies.json`（预解析缓存） |
| 学术文献 | OpenAlex 开放 API | `data/processed/literature.json` |

**再分发提醒**：上述材料版权归原始发布方所有。本仓库将它们用于分析研究并保留出处字段
（`source_document` / `url` / `locator`）；转载或商业使用请遵守原始来源的条款。

## 3. 隐私

含真实个人履历的简历数据（`北京人工智能简历数据.xlsx` 等）**不进入本仓库**。

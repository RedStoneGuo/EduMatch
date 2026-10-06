# 11 Comprehensive Retrieval｜全面检索是默认意识

## 1. 为什么要单独立一条

任何一个"没查到"的结论，都只有在**穷举了全部可用来源**之后才成立。只查一个地方就
断言"没有"，是本项目最容易犯、后果最严重的错误。因此把"全面检索"写成系统默认动作，
而不是靠 Agent 临场想起。

## 2. 固定检索顺序（缺一不可）

| 顺序 | 来源 | 位置 | 说明 |
| --- | --- | --- | --- |
| 1 | 本地正文缓存 | `data/raw/pdf_text/**` | 已抽取的 txt，最快 |
| 2 | 规范一手材料 | `data/source/<数据类型>/<院校>/**` | PDF / DOCX / XLSX / TXT；PDF 按需抽正文并缓存 |
| 3 | 归档历史资料 | `../AI竞赛数据归档/**` | 只读；常含更早年份的质量报告 |
| 4 | 采集产物 | `data/harvest/<院校>/**` | 插件离线回放结果 |
| 5 | 联网插件采集 | `vendor/edu-material-harvest` | 有**已核实域名**才允许；入口 A 全站/栏目、入口 B 承载页直采 |

实现：`edumatch/retrieval_sweep.py::sweep_sources`，产出 **检索台账**（每条带
`kind / reference / state / reason / objectives_found`）。

## 3. 状态语义（必须如实标注）

| state | 含义 | 下一步 |
| --- | --- | --- |
| `hit` | 找到正文且可读 | 直接用于抽取 |
| `extracted_pdf` | 只有 PDF，已按需抽正文（缓存） | 直接用于抽取 |
| `error` | 文件在但抽取失败（无文本层 / 格式不支持） | 换来源或标注 `extractor_unavailable` |
| `need_online` | 前述来源都没有可核查内容 | 给出域名与入口，走第 5 步 |
| `miss` | 该来源下不存在匹配材料 | 记录，不代表"事实不存在" |

## 4. 与结论的关系

1. **只有穷举后仍无，才能写"证据不足"**，并附上台账（查了哪些源、各自状态、补采计划）。
2. **不因单一来源未命中就下"没有"的结论**。
3. **校级 ≠ 专业级**：院校报告里的"人才培养目标"是全校口径，只能作**已披露的代理**，
   不计入 Primary TSI；本专业目标必须来自专业名锚定的段落。
4. **联网补采要合规**：域名必须来自 `data/harvest/domains.json` 或实测核实，
   禁止猜域名（`scripts/resolve_school_domains.py`）。

## 5. 在报告里怎么体现

- 18 节报告的 §3「数据范围、方法与可复现」写一行台账摘要；
- 单层级报告（宏观/中观）带完整台账表 + 联网补采计划；
- `result["retrieval_ledger"]` 进 JSON，供 HTML 与人工复核。

## 6. 相关实现

| 能力 | 文件 |
| --- | --- |
| 检索穷举与台账 | `edumatch/retrieval_sweep.py` |
| PDF 按需抽取与缓存 | `edumatch/pdf_text.py` |
| 专业名锚定的目标定位 | `analysis/objective_alignment.py` |
| 覆盖面状态机（材料级） | `edumatch/coverage_pipeline.py` |

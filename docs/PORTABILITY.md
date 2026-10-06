# 可迁移性说明（整包拷到别的电脑 / 别的 Agent）

结论：**把 `EduMatch` 整个文件夹复制到任意路径即可运行**，
不需要修改配置、不需要原始归档、不依赖某个盘符。

## 1. 一条命令验证

```powershell
cd <本包目录>
python scripts\check_portability.py       # 期望：可迁移（0 处绝对路径 / 0 处非法包外引用 / 0 缺失）
python scripts\relativize_paths.py --check  # 期望：待改写 0 处绝对路径
python -m pytest tests -q                 # 期望：181 passed / 3 skipped
```

## 2. 路径规则

| 类别 | 规则 | 现状 |
| --- | --- | --- |
| 代码 / 配置 / 脚本 | **不得出现盘符绝对路径**（`D:\…` / `C:/…`） | 0 处（`check_portability.py` 每次校验） |
| `config/config.yaml` | 所有路径相对本包：`workspace: "."`、`archive: "reference/archive"`、`data/...` | ✓ |
| 数据里的来源路径 | `source_document` 一律相对写法：包内 `data/source/...`、包外 `../AI竞赛数据归档/...` | ✓（`relativize_paths.py --check` = 0） |
| 输出目录 | 默认 **当前工作目录/分析产物**（可用 `EDUMATCH_OUT_DIR` 或 `--out-dir` 改） | ✓ 不依赖包外结构 |
| Python 解释器 | 用 `EDUMATCH_PYTHON` 指定；`analyze.ps1` 默认用 PATH 里的 `python` | ✓ 不写死解释器路径 |

## 3. 整包内包含什么（能独立跑的部分）

```
analysis/ edumatch/ agent/ reporting/ mcp_servers/ skills/ scripts/ tests/ docs/
config/config.yaml  ontology/skill_ontology.yaml
data/raw  data/processed  data/source（一手材料）  data/harvest（采集产物）  data/db
reference/archive（政策原文 + 旧版过程记录的最小可运行副本）
vendor/edu-material-harvest（联网采集插件，12 个 MCP 工具）
analyze.ps1  AGENTS.md  PROMPT.md  交接文档.md  README.md
```

## 4. 包外依赖（只有两类，且都可缺席）

| 依赖 | 用途 | 缺席时行为 |
| --- | --- | --- |
| `../AI竞赛数据归档`（可选） | 历史归档 PDF / 旧过程记录，作为**补充**证据源 | 记录为 `miss`，改用包内 `reference/archive` 与 `data/source`，流程不中断 |
| 网络（可选） | 插件联网采集、域名核验 | `--offline` 只出采集计划与缺口；核验失败会如实记录，不影响本地分析 |

> **原始归档材料已随包**：`data/source/` 现有 2,510 个文件 / 约 4.13 GB
> （培养方案 0.82 GB、年度报告 2.39 GB、专业介绍 0.35 GB、课程大纲 0.33 GB、政策 26 MB 等），
> 归档 PDF 均已复制进来，整包拷走即可离线完成全流程。
> 包外 `../AI竞赛数据归档` 只是**历史补充源**，不再必需。

## 5. 换机器后的检查清单

1. `python scripts\check_portability.py` → 必须"可迁移"；
2. `python scripts\relativize_paths.py --check` → 必须 0 处；
3. `python -m pytest tests -q` → 基线通过；
4. `.\analyze.ps1 "分析北京工业大学人工智能专业与大模型算法工程师岗位的匹配度" -NoHarvest` → 能出 `报告_all.html`；
5. 需要联网采集时：`python scripts\check_portability.py` 不报网络问题即可，再按 `--domain-candidate` 核验域名。

## 6. 常见的"看起来像绝对路径"但没问题的情况

- `https://…` 是 URL，不是文件路径；
- 文档里的示例路径（`` `D:\Codex_project\…` ``）只作说明，已标注为"例如"；
- `reference/archive` 是包内相对路径。

`scripts/check_portability.py` 已按这些规则跳过文档示例，只对**真实代码/配置**报错。

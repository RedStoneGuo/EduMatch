# 10 Scoped Report｜按层级交付与追问

## 目标

让系统对**任意院校 + 任意专业 + 任意目标岗位**都可用，并且**只交付用户要的那一层**：
用户选微观，就给微观报告与微观网页；不要顺手把宏观/中观塞进去。

## 1. 交互协议（保留原有问询，新增两步）

```
第 0 轮（原有）：确认尺度与对象（院校 / 专业 / 岗位 / 个人）
第 1 轮（原有）：按尺度补细节（宏观：区域与岗位大类；中观：培养方案版本与同类校；
                微观：引导式画像——先课程勾选，再问做过的事，用行为锚点代替自评）
第 2 轮（原有）：复述确认
第 3 轮（新增）：确认**交付层级**——宏观 / 中观 / 微观 / 三视角
第 4 轮（新增）：第一版产出后，问"是否需要更完整的三视角报告与 HTML？"
```

命令行：

```powershell
python -m agent.runner --query "<问题>" --scope micro --json out.json
python -m reporting.render --result out.json --scope micro --out 微观报告.html
python -m agent.runner --query "<问题>" --scope all --json out_all.json   # 直接出三视角
```

未指定 `--scope` 时按 query 推断（`agent/scope.py`），交互模式下会请用户确认；
`--no-interactive` 用于批处理。

## 2. 各层级交付什么

| 层级 | 读者 | 报告必须包含 |
| --- | --- | --- |
| 宏观 | 政府/主管部门 | Primary TSI、**逐校信息源台账**（哪几所院校贡献了什么材料）、覆盖高校样本、Observed Job Posting Demand、**需求侧画像（学历/行业/技能热度/薪资多条形图）**、**各校课程贡献条图**、**目标校×同类校×市场三角对照与技能级三方对照**、**同类高校就业结果对比**、S1、关键缺口、政策—产业—岗位—技能关联路径、布局/政策模拟 |
| 中观 | 专业负责人/教师 | Primary TSI、培养方案画像、**课程 × 技能矩阵（逐门可核查 + 未映射课程）**、目标岗位画像、S1、Fit/Gap 明细、同类院校 Benchmark（**逐技能本校 vs 同类校 vs 市场**，不是一句话口径）、证据冲突消解、培养方案优化模拟 |
| 微观 | 学生本人 | 个人证据画像 L0–L4（含分层口径说明）、**个人缺口条形图（需求 vs 个人供给）**、个人岗位适配（子指标）、Knowledge/Skill/Capability/Practice 四层缺口全量明细、优先行动与学习路径、自述缺项、边界 |

三视角（`--scope all`）= 宏观 + 中观 + 微观，由 `agent/report.py` 的 18 节完整版渲染。
来源与复现页另需包含**数据资产总览**（本地文档/课程/政策规模 + 采集入库量 + 证据等级分布）。

## 3. 硬约束

1. **只呈现所选层级**：报告与 HTML 都不出现另外两层的读数与图表（来源与复现章节除外）。
2. **Finding 驱动**：每个重要结论写清 Finding → Evidence → Model → Action → Simulation。
3. **Primary TSI 唯一**：Match / Skill Fit 一律标为子指标，不并列、不换算。
4. **缺失不记 0**：S1 找不到培养目标原文就记证据不足；个人"没提到"的技能记证据不足。
5. **培养目标来源通用化**：培养方案正文 → 专业介绍 → 教学质量报告 → 就业质量报告；
   院校级报告要按专业名在正文中定位，禁止用整校"人才培养目标"顶替专业目标。

## 4. 相关实现

| 能力 | 文件 |
| --- | --- |
| 层级选择 / 推断 / 追问话术 | `agent/scope.py` |
| 单层级报告 | `agent/scoped_report.py` |
| 三视角 18 节报告 | `agent/report.py` |
| 单层级自包含 HTML | `agent/html_report.py` |
| 主题（CSS/JS，唯一来源） | `EduMatch/reporting/theme.py` |
| 版式构件（图表/TSI Tree/S1/台账/导航） | `EduMatch/reporting/components.py` |
| 任意院校/专业 → 既有版式 HTML | `python -m reporting.render`（`EduMatch/reporting/render.py`） |
| 自定义页面模板 | `EduMatch/reporting/templates/` |
| **零数据模板（生成前必看）** | `reporting/templates/page_template.html` / `page_template_micro.html` |
| 演示页面（标准场景） | `EduMatch-演示页面/_build/build_page.py --scope <…>`（import Core 主题/构件） |
| 培养目标通用抽取 | `analysis/objective_alignment.py`、`edumatch/engine.py`、`edumatch/pdf_text.py` |

## 5. 交付红线（避免偏离既有系统路径）

1. **联网只走插件**：`vendor/edu-material-harvest`（`--source-mode plugin|hybrid --harvest`），
   域名先实测核实；不要用 `urllib`/`curl`/浏览器手工抓站替代。
2. **HTML 只用既有版式**：Core 的 `python -m reporting.render`（任意院校专业）或
   `_build/build_page.py`（标准演示场景）。允许基于 `reporting/theme.py` +
   `reporting/components.py` **自行编写新页面/脚本**（模板在 `reporting/templates/`），
   但**禁止另造 CSS/版式**；`agent.runner --html` 仅作内部预览。
3. **报告以引擎产物为准**：不因为"引擎某维证据不足"就绕过引擎自撰报告；证据不足要写进报告
   并说明补数路径，而不是替换掉引擎链路。
4. **三视角是完整交付**：单层级是第一版，产出后必须追问是否补 `--scope all`。
5. **维度不得删减**：生成前对照 `reporting/templates/page_template.html` 的结构清单，
   缺数据的维度显示「未获取」而不是省略；模板本身零真实数据，不得把占位当值。
6. **宏观不得只显示 1 所高校**：统计卡口径是「区域课程池院校 N 所」，目标校单列；
   台账必须逐校展开。若 `supply.peer_by_school` 为空，先补采再出结论，
   而不是把 1 所目标校当成"区域"。（详见 `AGENTS.md` §11）

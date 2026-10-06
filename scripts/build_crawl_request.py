"""按学科门类生成"岗位数据补采需求清单"（交给爬取 Agent 使用）。

    python scripts/build_crawl_request.py

产出（写到 EduMatch 根目录，便于直接交付）：

* `数据补采需求清单.md`   —— 人读版：门类 → 专业 → 建议检索词 → 优先级 → 缺口说明
* `数据补采需求清单.csv`  —— 机读版：一行一个专业，含检索词、院校数、当前是否有岗位数据
* `data/processed/crawl_request.json` —— 完整结构化结果（含统计口径与生成时间）

判定"是否需要补采岗位数据"的依据来自本地数据，而不是拍脑袋：

* 该专业是否已有培养方案课程（供给侧已就绪 → 缺的就是需求侧）；
* 该专业是否已有就业事实（就业质量报告覆盖）；
* 该专业关键词在当前岗位语料中的覆盖率（AI/计算机 ≈ 高，其余 ≈ 0）。
"""

from __future__ import annotations

import csv
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parent
sys.path.insert(0, str(ROOT))

from edumatch import majors as majors_mod  # noqa: E402
from edumatch.dataset import Dataset  # noqa: E402

#: 专业名 → 学科门类（按教育部学科门类口径），用于分组与检索词提示。
DISCIPLINE_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("工学", ("机械", "车辆", "材料", "冶金", "焊接", "化工", "化学工程", "土木", "建筑", "城乡规划",
              "风景园林", "给排水", "环境工程", "环境科学", "资源循环", "制药", "能源", "动力",
              "电气", "自动化", "测控", "仪器",
              "电子", "通信", "信息工程", "光电", "微电子", "集成电路", "计算机", "软件", "网络",
              "物联网", "信息安全", "人工智能", "智能", "机器人", "数据科学", "大数据", "测绘",
              "地质工程", "采矿", "石油", "储运", "安全工程", "交通", "航空", "航天", "飞行器",
              "兵器", "武器", "核工程", "船舶", "纺织", "食品", "生物工程", "生物医学工程",
              "农业工程", "林业工程", "包装", "印刷", "工程管理", "工业工程", "智能制造",
              "数字媒体技术", "物联网工程", "能源与动力", "新能源")),
    ("理学", ("数学", "信息与计算", "统计", "物理", "化学", "生物科学", "生物技术", "地理", "地质学",
              "地球物理", "大气", "海洋", "天文", "心理", "生态", "力学", "材料物理", "光电信息科学")),
    ("管理学", ("管理", "工商", "会计", "财务", "审计", "市场营销", "人力资源", "物流", "电子商务",
                "旅游", "公共事业", "行政管理", "土地资源", "图书情报", "档案", "工程管理", "信息管理")),
    ("经济学", ("经济", "金融", "国际贸易", "国际经济", "财政", "税收", "保险", "投资", "数字经济")),
    ("法学", ("法学", "法律", "政治学", "国际政治", "社会学", "社会工作", "民族学", "马克思主义",
              "思想政治教育", "公安", "侦查", "知识产权")),
    ("教育学", ("教育学", "学前教育", "小学教育", "特殊教育", "教育技术", "体育教育", "运动训练",
                "社会体育", "体育", "运动", "舞蹈教育", "国际汉语教育")),
    ("文学", ("汉语言", "汉语国际", "中国语言", "英语", "日语", "德语", "法语", "俄语", "西班牙语",
              "翻译", "新闻", "传播", "广告", "编辑出版", "外国语言", "汉语", "对外汉语")),
    ("医学", ("临床医学", "口腔", "预防医学", "中医学", "中药", "药学", "护理", "医学影像", "麻醉",
              "康复", "眼视光", "医学检验", "公共卫生", "生物医学", "制药")),
    ("农学", ("农学", "园艺", "植物保护", "种子", "农业资源", "动物科学", "动物医学", "林学", "园林",
              "水产", "草业", "茶学", "食品科学与工程", "食品质量", "农业工程")),
    ("艺术学", ("音乐", "美术", "绘画", "雕塑", "设计", "视觉传达", "环境设计", "产品设计", "服装",
                "工艺美术", "数字媒体艺术", "戏剧", "影视", "播音", "动画", "书法")),
    ("交叉学科", ("数据科学", "人工智能", "智能科学", "机器人工程", "数字经济", "金融科技", "生物信息")),
]

#: 门类 → 建议的招聘检索词模板（给爬取 Agent 的起点，具体专业词见行内 keywords 列）
DISCIPLINE_CRAWL_HINT = {
    "工学": "按「专业名 + 工程师/技术员/设计师」检索，同时抓取所在行业头部企业校招岗位",
    "理学": "按「专业名 + 研究员/分析师/教师」检索，注意科研院所与中学教师岗",
    "管理学": "按「专业名 + 专员/经理/管培生」检索",
    "经济学": "按「专业名 + 分析师/客户经理/风控」检索",
    "法学": "按「专业名 + 法务/律师/合规」检索",
    "教育学": "按「专业名 + 教师/教练/教研」检索",
    "文学": "按「专业名 + 编辑/翻译/运营/教师」检索",
    "医学": "按「专业名 + 医师/药师/护士/技师」检索，注意规培与医院招聘口径",
    "农学": "按「专业名 + 技术推广/研发/养殖」检索",
    "艺术学": "按「专业名 + 设计师/编导/教师」检索",
    "交叉学科": "按「专业名 + 算法/工程/产品」检索",
}


def discipline_of(major: str) -> str:
    """按专业名归类到学科门类；命中多条时取最长关键词所属门类。"""
    best: tuple[int, str] | None = None
    for name, keywords in DISCIPLINE_RULES:
        for keyword in keywords:
            if keyword in major and (best is None or len(keyword) > best[0]):
                best = (len(keyword), name)
    return best[1] if best else "其他"


def main() -> int:
    ds = Dataset.build(with_policies=False)
    catalog = ds.major_catalog()
    courses_by_major: dict[str, set[str]] = defaultdict(set)
    for course in ds.courses:
        if course.major:
            courses_by_major[majors_mod.normalize_major(str(course.major))].add(str(course.school))
    employment = Counter()
    try:
        rows = json.loads((ds.settings.processed_dir / "pdf_major_rows.json").read_text(encoding="utf-8"))
        employment = Counter(majors_mod.normalize_major(str(r.get("major") or ""))
                             for r in rows if r.get("major"))
    except (json.JSONDecodeError, OSError):
        pass

    # 现有岗位语料的覆盖：哪些专业的关键词能在语料里命中
    rows_jobs = ds.target_jobs()
    job_text = [f"{j.get('position') or ''}{j.get('job_description') or ''}" for j in rows_jobs]

    curated_path = ds.settings.project_root / "data" / "raw" / "major_keywords.json"
    curated = {}
    if curated_path.exists():
        try:
            curated = json.loads(curated_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            curated = {}

    entries: list[dict] = []
    for key, ref in catalog.items():
        if not majors_mod.is_plausible_major(ref.name):
            continue
        spec = majors_mod.job_keywords(ref.name, curated=curated)
        hits = sum(1 for text in job_text if any(k in text for k in spec["keywords"]))
        share = hits / len(job_text) if job_text else 0.0
        schools = sorted(courses_by_major.get(key, set()))
        n_employment = employment.get(key, 0)
        if share >= 0.30:
            need, priority = "已有岗位语料", "—"
        elif schools and n_employment:
            need, priority = "缺岗位语料（供给侧+就业侧就绪）", "P0"
        elif schools:
            need, priority = "缺岗位语料（供给侧就绪）", "P1"
        elif n_employment:
            need, priority = "缺岗位语料（仅就业侧）", "P2"
        else:
            need, priority = "缺岗位语料（需先补教育侧数据）", "P3"
        entries.append({
            "discipline": discipline_of(ref.name),
            "major": ref.name,
            "keywords": spec["keywords"],
            "keyword_source": spec["source"],
            "n_courses": ref.n_courses,
            "n_schools_with_plan": len(schools),
            "schools_sample": schools[:5],
            "n_employment_rows": n_employment,
            "job_corpus_share": round(share, 4),
            "gap": need,
            "priority": priority,
        })

    entries.sort(key=lambda e: (e["discipline"], e["priority"], -e["n_schools_with_plan"], e["major"]))
    by_discipline: dict[str, list[dict]] = defaultdict(list)
    for entry in entries:
        by_discipline[entry["discipline"]].append(entry)

    out_json = ds.settings.processed_dir / "crawl_request.json"
    out_json.write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "catalog_size": len(entries),
        "job_corpus": {"n_jobs": len(rows_jobs), "coverage_threshold": 0.30,
                       "note": "现有岗位语料仅覆盖人工智能与计算机领域"},
        "by_discipline": {k: v for k, v in sorted(by_discipline.items())},
        "entries": entries,
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    csv_path = WORKSPACE / "数据补采需求清单.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["学科门类", "专业名称", "建议检索词", "优先级", "缺口类型",
                         "培养方案课程数", "有培养方案院校数", "就业事实条数", "现有岗位语料覆盖率"])
        for entry in entries:
            writer.writerow([entry["discipline"], entry["major"], "、".join(entry["keywords"]),
                             entry["priority"], entry["gap"], entry["n_courses"],
                             entry["n_schools_with_plan"], entry["n_employment_rows"],
                             f"{entry['job_corpus_share']:.1%}"])

    md = WORKSPACE / "数据补采需求清单.md"
    lines = ["# 岗位数据补采需求清单（按学科门类）", "",
             f"生成时间：{datetime.now(timezone.utc).astimezone().strftime('%Y-%m-%d %H:%M')}　"
             f"覆盖专业：{len(entries)} 个　现有岗位语料：{len(rows_jobs)} 条（仅人工智能+计算机领域）", "",
             "## 使用说明", "",
             "1. 每行一个专业，`建议检索词`交给爬取 Agent 作为招聘平台检索词；",
             "2. 优先级：**P0** 供给与就业数据都已就绪、只缺岗位（最该先抓）；"
             "**P1** 有培养方案缺岗位；**P2** 仅有就业数据；**P3** 教育侧也缺；",
             "3. 抓取口径建议：北京地区为主，按专业关键词导出，保留岗位名称/公司/学历/经验/薪资/"
             "岗位职责/关键词字段；同一检索词建议保留最近 12 个月；",
             "4. 导出后放入 `data/source/招聘原始表/` 并跑导入脚本即可自动进入模型。", ""]
    # 主体：P0/P1（教育侧已就绪、只缺岗位）展开成表；P2/P3 汇总成清单，避免文档被噪声淹没
    for discipline, items in sorted(by_discipline.items()):
        items = [e for e in items if e["priority"] in {"P0", "P1"}]
        if not items:
            continue
        p0 = [e for e in items if e["priority"] == "P0"]
        lines += [f"## {discipline}（待补 {len(items)} 个专业；其中 P0 {len(p0)} 个）", "",
                  f"> 检索建议：{DISCIPLINE_CRAWL_HINT.get(discipline, '按专业名 + 岗位名检索')}", "",
                  "| 优先级 | 专业 | 建议检索词 | 培养方案课程 | 有方案院校 | 就业事实 | 现有语料覆盖 |",
                  "| --- | --- | --- | --- | --- | --- | --- |"]
        for entry in items:
            lines.append(
                f"| {entry['priority']} | {entry['major']} | {'、'.join(entry['keywords'])} | "
                f"{entry['n_courses']} | {entry['n_schools_with_plan']} | "
                f"{entry['n_employment_rows']} | {entry['job_corpus_share']:.1%} |")
        lines.append("")
    others = [e for e in entries if e["priority"] in {"P2", "P3"}]
    if others:
        lines += ["## 附：仅有就业数据 / 教育侧也缺的专业（P2/P3，暂不建议优先抓取）", "",
                  f"共 {len(others)} 个，完整清单见 `数据补采需求清单.csv`。示例：", ""]
        lines.append("、".join(e["major"] for e in others[:60]) + " …")
        lines.append("")
    md.write_text("\n".join(lines), encoding="utf-8")

    summary = {d: {"n": len(v), "p0": sum(1 for e in v if e["priority"] == "P0")}
               for d, v in sorted(by_discipline.items())}
    print(json.dumps({"majors": len(entries), "by_discipline": summary,
                      "files": [str(md), str(csv_path), str(out_json)]},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

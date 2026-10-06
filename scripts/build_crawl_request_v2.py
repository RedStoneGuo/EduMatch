"""数据补采需求清单 v2：不只"专业缺岗位语料"，而是把**四类缺口**分开算清。

v1（`scripts/build_crawl_request.py`）只回答一件事：这个专业缺不缺岗位语料。
但实测（北理工会计学 / 矿大工程力学）证明"没数据"有四种完全不同的成因，
对应四种完全不同的处理动作，混在一起会让人去补本来已有的数据：

1. **岗位族未定义** —— 本地已有岗位语料，但 `edumatch/occupation.py` 只登记了 10 个
   AI/计算机方向的岗位族，会计/机械/土木等岗位族缺位 → 岗位级 Match 算不了。
   动作：补岗位族定义（名称 + 检索词 + 典型技能），不用爬数据。
2. **岗位语料缺口** —— 该专业在本地按专业导出语料里 0 条。
   动作：按检索词导出岗位表。
3. **就业质量报告缺口** —— 该专业没有落实率/签约率/深造率事实。
   动作：补该校《毕业生就业质量报告》。
4. **培养方案课程表解析缺口** —— PDF 与正文都在、里面确实有课程表，但引擎解析 ≈0 门
   （版式未被适配器识别）。动作：先修解析规则或换承载件，**不是缺数据**。

用法：

    python scripts\\build_crawl_request_v2.py

产出（写到 EduMatch 根目录）：

    data/processed/crawl_request_v2.json   完整结构化结果
    数据补采需求清单_v2.csv                 机读版（一行一个缺口项）
    数据补采需求清单_v2.md                  人读版（按缺口类型分组）
"""

from __future__ import annotations

import csv
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

CORE = Path(__file__).resolve().parents[1]
WORKSPACE = CORE.parent
sys.path.insert(0, str(CORE))

from edumatch.dataset import Dataset, major_matches  # noqa: E402
from edumatch import majors as majors_mod  # noqa: E402
from edumatch.occupation import OCCUPATIONS  # noqa: E402

#: 候选岗位族：本地岗位语料里确实存在、但 `occupation.py` 没有登记的方向。
#: ``keywords`` 同时用于（a）统计本地语料里有多少条命中、（b）作为补岗位族的检索词建议。
CANDIDATE_OCCUPATIONS: list[tuple[str, tuple[str, ...], str]] = [
    ("会计 / 财务", ("会计", "财务", "出纳", "总账", "成本"), "管理学 · 经管类岗位"),
    ("审计 / 税务", ("审计", "税务", "税审", "内控"), "管理学 · 经管类岗位"),
    ("人力资源 / 行政", ("人力资源", "人事", "招聘专员", "行政"), "管理学 · 职能类岗位"),
    ("市场营销 / 销售", ("市场营销", "销售", "渠道", "客户经理", "大客户"), "管理学 · 市场类岗位"),
    ("电商运营 / 内容运营", ("电商运营", "运营专员", "新媒体运营", "店铺运营"), "管理学 · 运营类岗位"),
    ("物流 / 供应链", ("物流", "供应链", "采购", "仓储"), "管理学 · 供应链岗位"),
    ("机械 / 结构设计", ("机械设计", "结构设计", "机械工程师", "结构工程师", "CAD"), "工学 · 机械/土木"),
    ("电气 / 自动化", ("电气", "自动化", "PLC", "配电", "控制工程师"), "工学 · 电气自动化"),
    ("土木 / 施工管理", ("土木", "施工", "工程管理", "造价", "监理"), "工学 · 土木建筑"),
    ("化工 / 材料", ("化工", "工艺工程师", "材料工程", "高分子", "电池"), "工学 · 化工材料"),
    ("环境 / 安全", ("环境工程", "环保", "安全工程", "EHS"), "工学 · 环境安全"),
    ("医药 / 护理", ("临床", "医师", "药师", "护士", "医学检验"), "医学 · 医疗卫生"),
    ("教师 / 教研", ("教师", "教研", "讲师", "课程顾问"), "教育学 · 教育岗位"),
    ("法务 / 合规", ("法务", "律师", "合规", "风控"), "法学 · 法务合规"),
    ("翻译 / 外语", ("翻译", "口译", "笔译", "外语"), "文学 · 语言服务"),
    ("设计 / 传媒", ("平面设计", "视觉设计", "UI设计", "编导", "文案"), "艺术学 · 设计传媒"),
]

#: 课程表解析缺口判定：引擎解析出的课程数低于此值，而 PDF/正文存在。
MIN_PARSED_COURSES = 20

#: 明显是"单位名"而不是专业名（就业质量报告表格里会把用人单位抽成专业行）。
ORG_NAME_HINTS = ("事务所", "有限公司", "股份有限公司", "集团", "银行", "分公司",
                  "医院", "学校", "大学", "学院", "研究院", "研究所", "中心", "局", "委员会")


def is_org_like(name: str) -> bool:
    return any(hint in name for hint in ORG_NAME_HINTS)


def _job_text(row: dict) -> str:
    return " ".join(str(row.get(k) or "") for k in ("position", "job_description", "industry"))


def occupation_gap_rows(jobs: list[dict]) -> list[dict]:
    defined = " ".join(f"{o.name}{''.join(o.keywords)}" for o in OCCUPATIONS)
    rows: list[dict] = []
    for name, keywords, discipline in CANDIDATE_OCCUPATIONS:
        if any(k in defined for k in keywords):
            continue                       # 已经有岗位族，不用补
        hits = [j for j in jobs if any(k in _job_text(j) for k in keywords)]
        with_salary = sum(1 for j in hits
                          if isinstance(j.get("salary_max") or j.get("salary_min"), (int, float)))
        if not hits:
            priority = "P2"                # 连语料都没有：先补语料再定义岗位族
        elif len(hits) >= 300:
            priority = "P0"                # 语料充足，只缺岗位族定义
        else:
            priority = "P1"
        rows.append({
            "gap_type": "① 岗位族未定义（可选：提升岗位匹配精度）",
            "object_type": "岗位族",
            "object": name,
            "school": "",
            "keywords": "、".join(keywords),
            "priority": priority,
            "status": (f"本地可匹配岗位 {len(hits)} 条（含薪资 {with_salary} 条）；"
                       f"occupation.py 未登记该岗位族——系统已改用「岗位名在全量招聘表直搜」，"
                       "岗位级 Match 照常可算"),
            "action": ("可选：补 edumatch/occupation.py 岗位族（id + 名称 + 检索词 + 典型技能）"
                       "以获得更精确的技能词表；**不补也能分析**"
                       + ("；语料已足够" if hits else "；另需先补岗位语料")),
            "discipline": discipline,
        })
    return rows


def course_parse_gap_rows(ds: Dataset) -> list[dict]:
    """PDF 与正文都在、但引擎解析出的课程 ≈0 的 (院校, 专业)：先修解析，不是补数据。"""
    plan_root = ds.settings.project_root / "data" / "source" / "培养方案"
    text_root = ds.settings.project_root / "data" / "raw" / "pdf_text"
    by_school: dict[str, set[str]] = defaultdict(set)
    for course in ds.courses:
        school = course.get("school") if isinstance(course, dict) else getattr(course, "school", "")
        major = course.get("major") if isinstance(course, dict) else getattr(course, "major", "")
        if school and major:
            by_school[str(school)].add(str(major))
    rows: list[dict] = []
    if not plan_root.exists():
        return rows
    for school_dir in sorted(p for p in plan_root.iterdir() if p.is_dir()):
        school = school_dir.name
        for pdf in sorted(school_dir.glob("*.pdf")):
            major = pdf.stem.split("_", 1)[1] if "_" in pdf.stem else pdf.stem
            if major.endswith("（实验班）") or "教改" in major:
                continue
            parsed = ds.course_set(school=school, major=major, include_template=False)
            if len(parsed) >= MIN_PARSED_COURSES:
                continue
            text = (text_root / school / "培养方案" / f"{pdf.stem}.txt")
            if not text.exists():
                continue                    # 正文都没抽出来：属于"补文本层"，不是版式问题
            body = text.read_text(encoding="utf-8", errors="ignore")
            n_codes = body.count("课程代码") + len([l for l in body.splitlines()
                                                    if l.strip()[:6].isdigit()])
            has_table = ("学分" in body and "课程" in body)
            rows.append({
                "gap_type": ("④ 培养方案课程表解析缺口（正文有表但未识别）" if has_table
                             else "⑤ 培养方案正文不含课程表（材料不完整）"),
                "object_type": "院校·专业",
                "object": major,
                "school": school,
                "keywords": "",
                "priority": "P0" if (has_table and n_codes >= 20) else "P1",
                "status": (f"培养方案 PDF 与正文均在（{len(body)} 字，疑似课程行 {n_codes}），"
                           f"引擎解析出 {len(parsed)} 门课程；"
                           + ("正文含课程表线索" if has_table else "正文不含课程表")),
                "action": ("先修 edumatch/ingest/plan_tables.py 版式适配（或换承载页件）"
                           if has_table else
                           "该 PDF 只有培养目标/毕业要求，需补采含课程表的完整培养方案"
                           "（或从课程大纲/专业介绍里取课程信息）"),
                "discipline": "",
            })
    return rows


def education_gap_rows(ds: Dataset) -> tuple[list[dict], list[dict]]:
    """按专业算：岗位语料缺口 + 就业质量报告缺口。"""
    catalog = ds.major_catalog()
    employment: Counter = Counter()
    try:
        payload = json.loads(
            (ds.settings.processed_dir / "pdf_major_rows.json").read_text(encoding="utf-8"))
        for row in payload:
            if row.get("major"):
                employment[str(row["major"])] += 1
    except (json.JSONDecodeError, OSError):
        pass
    job_rows: list[dict] = []
    edu_rows: list[dict] = []
    for ref in catalog.values():
        name = ref.name
        if not majors_mod.is_plausible_major(name):
            continue                       # 过滤"普华永道中天会计师事务所"这类非专业条目
        if is_org_like(name):
            continue
        scoped = ds.major_scope_jobs(name)
        schools = sorted({
            str((c.get("school") if isinstance(c, dict) else getattr(c, "school", "")) or "")
            for c in ds.course_set(major=name, include_template=False)} - {""})
        n_edu = sum(v for k, v in employment.items() if major_matches(k, name))
        if schools and not scoped:
            job_rows.append({
                "gap_type": "② 岗位语料缺口（该专业本地无按专业导出岗位）",
                "object_type": "专业", "object": name, "school": "",
                "keywords": "、".join([name]), "priority": "P0",
                "status": (f"有培养方案院校 {len(schools)} 所（{'、'.join(schools[:3])}…）、"
                           f"就业事实 {n_edu} 条，但按专业导出岗位 0 条"),
                "action": "按专业名导出最近 12 个月岗位（北京为主），放入 data/source/招聘原始表/",
                "discipline": "",
            })
        if schools and n_edu == 0:
            edu_rows.append({
                "gap_type": "③ 就业质量报告缺口（该专业无就业事实）",
                "object_type": "专业", "object": name, "school": "、".join(schools[:3]),
                "keywords": "", "priority": "P1",
                "status": f"有培养方案院校 {len(schools)} 所，就业事实 0 条",
                "action": "补这些院校的《毕业生就业质量报告》分专业表（落实率/签约率/深造率）",
                "discipline": "",
            })
    return job_rows, edu_rows


def main() -> int:
    ds = Dataset.build(with_policies=False)
    jobs = list(ds.jobs)
    occ_rows = occupation_gap_rows(jobs)
    parse_rows = course_parse_gap_rows(ds)
    job_rows, edu_rows = education_gap_rows(ds)
    entries = occ_rows + job_rows + edu_rows + parse_rows
    order = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
    entries.sort(key=lambda e: (e["gap_type"], order.get(e["priority"], 9),
                                -int(len(e["status"])) , e["object"]))

    processed = ds.settings.processed_dir
    processed.mkdir(parents=True, exist_ok=True)
    (processed / "crawl_request_v2.json").write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_jobs_local": len(jobs),
        "n_occupation_families_defined": len(OCCUPATIONS),
        "counts": {t: sum(1 for e in entries if e["gap_type"] == t)
                   for t in sorted({e["gap_type"] for e in entries})},
        "entries": entries,
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    csv_path = WORKSPACE / "数据补采需求清单_v2.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["缺口类型", "对象类型", "对象名称", "涉及院校", "建议检索词",
                         "优先级", "现状", "建议动作"])
        for e in entries:
            writer.writerow([e["gap_type"], e["object_type"], e["object"], e["school"],
                             e["keywords"], e["priority"], e["status"], e["action"]])

    grouped: dict[str, list[dict]] = defaultdict(list)
    for e in entries:
        grouped[e["gap_type"]].append(e)
    lines = ["# 数据补采需求清单 v2（按缺口类型）", "",
             f"生成时间：{datetime.now(timezone.utc).astimezone().strftime('%Y-%m-%d %H:%M')}　"
             f"本地岗位语料：{len(jobs):,} 条　已登记岗位族：{len(OCCUPATIONS)} 个（均为 AI/计算机方向）", "",
             "## 这份清单和 v1 的区别", "",
             "v1 只回答「这个专业缺不缺岗位语料」。实测发现**「没数据」有四种成因**，"
             "混在一起会让人去补本来已有的数据：", "",
             "| 缺口类型 | 先别急着采数据 | 正确的第一步 |", "| --- | --- | --- |",
             "| ① 岗位族未定义 | 本地岗位语料往往已经够用 | **可选的**精度提升：补 `occupation.py` 岗位族；"
             "系统已支持「岗位名在全量招聘表直搜」，不补也能出岗位级 Match |",
             "| ② 岗位语料缺口 | — | 按检索词导出岗位表 |",
             "| ③ 就业质量报告缺口 | — | 补该校就业质量报告分专业表 |",
             "| ④ 课程表解析缺口（正文有表） | **数据本来就有** | 先修解析版式适配 |",
             "| ⑤ 培养方案正文不含课程表 | 材料本身不完整 | 补采含课程表的完整培养方案 |",
             "（同一个 PDF 里到底有没有课程表，用 `scripts\\find_source.py --school <校> --major <专业>` 即可查清。）", "",
             "## 用法", "",
             "1. 先看①：如果目标岗位在①里，**不用爬数据**，补岗位族定义即可让岗位级 Match 可用；",
             "2. 再看④：如果目标院校专业在④里，**先修解析**，否则会把已有课程当成「专业没教」；",
             "3. ②③才是真正要出门采的：导出后放 `data/source/招聘原始表/`、"
             "就业质量报告放 `data/source/年度报告/<院校>/就业质量报告/`。", ""]
    for gap_type in sorted(grouped):
        items = grouped[gap_type]
        p0 = sum(1 for e in items if e["priority"] == "P0")
        lines += [f"## {gap_type}", "",
                  f"共 {len(items)} 项；其中 P0 {p0} 项。", "",
                  "| 优先级 | 对象 | 涉及院校 | 建议检索词 | 现状 | 建议动作 |",
                  "| --- | --- | --- | --- | --- | --- |"]
        for e in items[:60]:
            lines.append(f"| {e['priority']} | {e['object']} | {e['school'] or '—'} | "
                         f"{e['keywords'] or '—'} | {e['status']} | {e['action']} |")
        if len(items) > 60:
            lines.append(f"| … | 其余 {len(items) - 60} 项见 CSV | | | | |")
        lines.append("")
    md_path = WORKSPACE / "数据补采需求清单_v2.md"
    md_path.write_text("\n".join(lines), encoding="utf-8")

    print(f"岗位族缺口 {len(occ_rows)} 项 / 岗位语料缺口 {len(job_rows)} 项 / "
          f"就业报告缺口 {len(edu_rows)} 项 / 课程解析缺口 {len(parse_rows)} 项")
    print(f"已写出：{csv_path.name}、{md_path.name}、data/processed/crawl_request_v2.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

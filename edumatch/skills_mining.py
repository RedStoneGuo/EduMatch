"""从「岗位语料 × 课程语料」的交集中挖掘专业级**共享技能词表**。

为什么需要它：本体的 40 个实体是 AI/计算机/经管口径，机械、材料、建筑等专业既不在
本体里，"用课程名当技能"又行不通——岗位 JD 不会写"机械原理"这种课程名。结果是供需
两侧落在两套几乎不相交的词表上，匹配度虽然能算出数字，语义却是空的（实测机械工程：
供给词 5 个、需求技能 33 个、重叠率 15%）。

做法：把**只在岗位里出现**的词和**只在课程里出现**的词都排除，只保留同时出现在两侧的
候选词。这样得到的词表天然可比——既来自真实岗位需求，又确实在课程体系里教。

* 英文/工具词：SolidWorks、ANSYS、MATLAB、PLC、CNC …
* 中文术语：中文串的 2–6 字 n-gram，按岗位文档频次筛，再与课程语料取交集
* 过滤：虚词首尾、纯数字、过短/过长、在岗位里过于普遍（>60% 文档）的通用词

词表由数据驱动、随语料重算，不是人工拍的；不同专业得到不同词表。
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Iterable

EN_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9+#._/-]{1,24}")
CJK_RUN = re.compile(r"[\u4e00-\u9fff]{2,}")

#: 培养方案解析器写进 description 的样板文字（不是课程内容）
BOILERPLATE = [
    r"\d{4}级", r"培养方案", r"章节[:：][^·]*", r"学分\s*[\d.]+",
    r"总学时\s*[\d.]+", r"讲课\s*[\d.]+", r"实验\s*[\d.]+", r"实践学时\s*[\d.]+",
    r"必修", r"选修", r"理论", r"考查", r"考试",
]
_BOILER_RE = re.compile("|".join(BOILERPLATE))


def clean_course_text(name: str, description: str = "", *, extra_noise: Iterable[str] = ()) -> str:
    """课程匹配文本 = 课程名 + 去掉样板文字的描述。

    解析器会把"…培养方案 · 章节：… · 学分 3.0 · 总学时 48"塞进 description，
    不清洗的话每门课都会命中"机械工程/机电/学分"，供给向量全是假信号。
    """
    text = str(description or "")
    text = _BOILER_RE.sub(" ", text)
    for noise in extra_noise:
        if noise:
            text = text.replace(str(noise), " ")
    text = re.sub(r"[·、，,；;]+", " ", text)
    return re.sub(r"\s+", " ", f"{str(name or '').strip()} {text}").strip()

_EDGE_WORDS = (
    "的了和与及或在对于等我们你他她它这那有是无为非请能可要不很非常"
    "以及并且但是因为所以如果工作职责要求岗位优先熟悉掌握了解具备"
)
EDGE_STOP = set(_EDGE_WORDS)

GENERIC = {
    "工作经验", "岗位职责", "任职要求", "工作内容", "以上学历", "相关专业",
    "团队合作", "沟通能力", "学习能力", "责任心", "公司", "项目", "能力",
    "本科", "硕士", "博士", "大专", "学历", "专业", "技术", "经验", "以上",
    "要求", "优先", "熟悉", "掌握", "了解", "具备", "负责", "参与", "完成",
    "学分", "学时", "讲课", "实验", "实践", "必修", "选修", "培养方案", "章节",
}


def _cjk_ngrams(text: str, *, min_len: int = 2, max_len: int = 6) -> set[str]:
    out: set[str] = set()
    for run in CJK_RUN.findall(text or ""):
        for size in range(min_len, min(max_len, len(run)) + 1):
            for start in range(0, len(run) - size + 1):
                term = run[start:start + size]
                if term[0] in EDGE_STOP or term[-1] in EDGE_STOP:
                    continue
                out.add(term)
    return out


def _english(text: str) -> set[str]:
    return {t for t in EN_TOKEN.findall(text or "") if len(t) >= 2 and not t.isdigit()}


def mine_skill_vocabulary(
    course_texts: Iterable[str], job_texts: Iterable[str], *,
    background_texts: Iterable[str] | None = None,
    seed_terms: Iterable[str] = (),
    curated_terms: Iterable[str] = (),
    min_df: int = 3, min_share: float = 0.02, max_df_ratio: float = 0.5,
    min_lift: float = 2.0, gap_min_df: int = 8, gap_min_lift: float = 3.0,
    gap_limit: int = 40, limit: int = 400,
) -> dict:
    """为**任意专业**构建技能词表（所有专业同一条路，不分核心/非核心）。

    分工原则：**统计负责高召回候选，Agent 负责判定，算法负责计算**。纯统计挖出来的是
    "关键词"而不是"技能"，所以词表分三层、用途不同：

    * ``comparable_terms``：**岗位 ∧ 课程**都出现 → 两侧可比，用于 Fit/Gap 计算；
    * ``gap_candidates``：**只在岗位**出现且统计显著（更严的 df / lift 阈值）→ 候选缺口词，
      进入需求向量后供给自然为 0，正是"市场要、学校没教"的信号，供 Agent 确认；
    * ``curated_terms``：Agent/人工写入的确认词表，优先级最高、不受统计阈值限制。

    本体（40 个实体）在这里只是**普通种子词**，与人工词表同等待遇，没有特殊地位。
    """
    courses = [str(t or "") for t in course_texts]
    jobs = [str(t or "") for t in job_texts]
    if not jobs:
        return {"terms": [], "stats": {"n_courses": len(courses), "n_jobs": 0,
                                       "reason": "没有岗位语料，无法建技能词表"}}
    course_blob = "\n".join(courses)
    df: Counter[str] = Counter()
    for text in jobs:
        df.update(_english(text) | _cjk_ngrams(text))
    background = [str(t or "") for t in (background_texts or [])]
    bg_df: Counter[str] = Counter()
    for text in background:
        bg_df.update(_english(text) | _cjk_ngrams(text))
    max_df = max(min_df, int(len(jobs) * max_df_ratio))
    generic_ok = [
        (term, n) for term, n in df.items()
        if term not in GENERIC and len(term) >= 2
        and min_df <= n <= max_df
        and n / len(jobs) >= min_share
        # 专业特异性：本专业出现频率至少是背景语料的 min_lift 倍
        and (n + 1) / (bg_df.get(term, 0) + 1) >= min_lift
    ]
    comparable = {
        term for term, _ in _drop_substrings(
            [(t, n) for t, n in generic_ok if t in course_blob], df)
    }
    # 只出现在岗位、课程里没有的词：候选缺口。阈值更严，且数量受限，避免关键词淹没技能。
    gap_pool = [
        (t, n) for t, n in generic_ok
        if t not in course_blob and n >= gap_min_df and len(t) >= 3
        and (n + 1) / (bg_df.get(t, 0) + 1) >= gap_min_lift
    ]
    gap_pool = _drop_substrings(gap_pool, df)
    gap_pool.sort(key=lambda kv: -kv[1])
    gap_candidates = {term for term, _ in gap_pool[:gap_limit]}

    # 种子词（本体）与人工词表：普通候选，只要出现在岗位语料里就纳入
    seed_blob = "\n".join(jobs)
    seeds = {
        str(s).strip() for s in seed_terms
        if str(s).strip() and str(s).strip() not in GENERIC and len(str(s).strip()) >= 2
    }
    seeds_in_jobs = {s for s in seeds if s in seed_blob}
    curated = {
        str(s).strip() for s in curated_terms
        if str(s).strip() and str(s).strip() not in GENERIC and len(str(s).strip()) >= 2
    }
    # 计分只用"有把握是技能"的词：可比词 + 种子词 + 人工确认词。
    # gap_candidates 只作**候选清单**输出给 Agent 审阅——统计挖出来的是关键词，
    # 直接塞进需求向量会拿"base/SOP/toC"这类非技能词把 Fit 压低，那是噪音不是结论。
    vocabulary = comparable | seeds_in_jobs | curated
    vocabulary = _prune(list(vocabulary))
    ordered = sorted(
        vocabulary,
        key=lambda t: (0 if t in curated else 1 if t in comparable else 2,
                       0 if re.match(r"^[A-Za-z]", t) else 1, -df.get(t, 0), t),
    )[:limit]
    return {
        "terms": ordered,
        "comparable_terms": sorted(comparable),
        "gap_candidates": sorted(gap_candidates),
        "curated_terms": sorted(curated),
        "stats": {
            "n_courses": len(courses), "n_jobs": len(jobs),
            "n_candidates": len(df), "n_terms": len(ordered),
            "n_comparable": len(comparable), "n_gap_candidates": len(gap_candidates),
            "n_from_seeds": len(seeds_in_jobs), "n_curated": len(curated),
            "min_df": min_df, "max_df": max_df, "min_share": min_share, "min_lift": min_lift,
            "gap_min_df": gap_min_df, "gap_min_lift": gap_min_lift, "n_background": len(background),
            "top_examples": [{"term": t, "df": df.get(t, 0)} for t in ordered[:20]],
            "method": ("三层词表：岗位∧课程（可比，用于 Fit）∪ 岗位-only 显著词（候选缺口）"
                       "∪ 种子/人工词表。供需两侧同一套词表与同一抽取函数，不区分专业类别。"),
        },
    }


def _prune(terms: list[str]) -> list[str]:
    """最长匹配：'械设' 被 '机械设计' 吸收（长词出现频次足够时才吸收）。"""
    ordered = sorted(set(terms), key=len, reverse=True)
    keep: list[str] = []
    for term in ordered:
        if any(term != other and term in other for other in keep):
            continue
        keep.append(term)
    return keep


def _drop_substrings(kept: list[tuple[str, int]], df: Counter[str]) -> list[tuple[str, int]]:
    """去掉被更长术语吸收的碎片：'械设' 不该和 '机械设计' 同时进词表。

    只有更长术语的频次不至于太低（≥ 短词的 30%）时才吸收，避免一个罕见长词
    吃掉一个常见短词。
    """
    terms = [t for t, _ in kept]
    by_len = sorted(terms, key=len, reverse=True)
    keep: list[str] = []
    for term in by_len:
        absorbed = any(
            term != other and term in other and df.get(other, 0) >= 0.3 * df.get(term, 0)
            for other in keep
        )
        if absorbed:
            continue
        keep.append(term)
    order = {t: df.get(t, 0) for t in keep}
    return [(t, order[t]) for t in keep]

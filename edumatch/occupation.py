"""目标岗位（Occupation）解析与岗位切片。

模型输入从"院校 + 专业"扩展为"院校 + 专业 + 目标岗位"：先把这个目标岗位解析到
一个可核查的岗位族，再在招聘语料里切出属于该岗位族的岗位，得到**岗位级需求向量**。

解析规则是确定性的、可审计的：

1. 空值或"人工智能/AI/人工智能相关岗位" → `ai_all`（整个 AI 检索语料即目标岗位集合）；
2. 命中岗位族标准名或其关键词 → 该岗位族（取最长关键词命中；同长取定义顺序）；
3. 语料中该岗位族岗位数不足 `min_jobs` 时，先按岗位名称匹配，再回退到"名称+描述"匹配，
   并在 `match_scope` 中标注；
4. 仍无可用样本 → `status='insufficient_evidence'`，绝不编造岗位需求。

岗位族定义不引入外部知识库，全部来自本文件，便于审查与扩展。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

MIN_OCCUPATION_JOBS = 30

#: 同一岗位的常见叫法（用户说的词 → 家族或规范词）。
#: 目的：用户写"算法分析师"，系统不能因为语料里没有这四个字就判"检索不到"。
OCCUPATION_SYNONYMS: dict[str, str] = {
    "算法分析": "data_analysis", "算法分析师": "data_analysis",
    "数据科学": "data_analysis", "数据分析": "data_analysis",
    "大数据分析": "data_analysis", "大数据分析师": "data_analysis",
    "商业分析": "data_analysis", "bi工程师": "data_analysis", "bi": "data_analysis",
    "算法": "ml_algorithm", "算法工程师": "ml_algorithm", "算法专家": "ml_algorithm",
    "算法研究员": "ml_algorithm", "机器学习工程师": "ml_algorithm",
    "深度学习工程师": "ml_algorithm", "ai工程师": "ai_application",
    "人工智能工程师": "ai_application", "大模型工程师": "llm_algorithm",
    "llm工程师": "llm_algorithm", "大模型应用开发": "llm_algorithm",
    "数据开发": "data_engineering", "数仓开发": "data_engineering",
    "数据仓库": "data_engineering", "etl工程师": "data_engineering",
    "大数据开发": "data_engineering", "平台工程师": "mlops_platform",
    "运维开发": "mlops_platform", "ai产品": "ai_product", "产品经理": "ai_product",
}

#: 泛化时要剥掉的通用后缀（"数据分析师" → "数据分析"）。
TITLE_SUFFIXES: tuple[str, ...] = (
    "工程师", "分析师", "研究员", "专员", "主管", "经理", "专家", "顾问",
    "师", "员", "岗", "职位",
)

#: 泛化时要剥掉的修饰前缀（"高级数据分析师" → "数据分析师" → "数据分析"）。
TITLE_PREFIXES: tuple[str, ...] = (
    "高级", "资深", "初级", "中级", "首席", "助理", "实习", "应届", "兼职", "全职",
)


def title_variants(text: str | None, *, limit: int = 6) -> list[str]:
    """把一个岗位名展开成可检索的变体（原词 → 去后缀 → 去括号 → 词干）。

    例："高级数据分析师" → ["高级数据分析师", "数据分析", "数据"]。
    只做**确定性**的字符串泛化，不引入外部同义词库；命中哪一档会写进结果供披露。
    """
    raw = str(text or "").strip()
    if not raw:
        return []
    variants: list[str] = []

    def add(value: str) -> None:
        value = value.strip("　 ，,。；;、/-")
        if len(value) >= 2 and value not in variants:
            variants.append(value)

    add(raw)
    base = re.sub(r"[（(][^）)]*[）)]", "", raw).strip()
    add(base)
    changed = True
    while changed and len(variants) < limit:
        changed = False
        for value in list(variants):
            for suffix in TITLE_SUFFIXES:
                if value.endswith(suffix) and len(value) > len(suffix) + 1:
                    stripped = value[: -len(suffix)]
                    if stripped not in variants:
                        add(stripped)
                        changed = True
            for prefix in TITLE_PREFIXES:
                if value.startswith(prefix) and len(value) > len(prefix) + 1:
                    stripped = value[len(prefix):]
                    if stripped not in variants:
                        add(stripped)
                        changed = True
            # 同时剥前缀与后缀（"高级数据分析师" → "数据分析"），否则永远差一步
            core = value
            for prefix in TITLE_PREFIXES:
                if core.startswith(prefix) and len(core) > len(prefix) + 1:
                    core = core[len(prefix):]
            for suffix in TITLE_SUFFIXES:
                if core.endswith(suffix) and len(core) > len(suffix) + 1:
                    core = core[: -len(suffix)]
            if core != value and core not in variants:
                add(core)
                changed = True
    return variants[:limit]

@dataclass(frozen=True)
class OccupationFamily:
    id: str
    name: str
    keywords: tuple[str, ...]
    typical_skills: tuple[str, ...] = ()
    note: str = ""


#: 定义顺序即优先级（越靠前越具体）；`ai_all` 必须最后。
OCCUPATIONS: list[OccupationFamily] = [
    OccupationFamily(
        "llm_algorithm", "大模型算法工程师",
        ("大模型", "LLM", "语言模型", "GPT", "AIGC", "预训练", "微调", "对齐", "Transformer"),
        ("大模型", "Transformer", "RAG", "Prompt工程", "模型微调", "模型对齐", "Python", "PyTorch"),
        "偏大模型训练/微调/对齐与应用开发。",
    ),
    OccupationFamily(
        "cv_algorithm", "计算机视觉算法工程师",
        ("计算机视觉", "图像算法", "图像识别", "视觉算法", "目标检测", "图像处理", "人脸识别"),
        ("计算机视觉", "卷积神经网络", "深度学习", "PyTorch", "Python", "模型部署"),
        "图像/视频方向的算法岗位。",
    ),
    OccupationFamily(
        "nlp_voice", "自然语言处理 / 语音算法工程师",
        ("自然语言处理", "NLP", "语音", "文本", "语义", "大语音"),
        ("自然语言处理", "Transformer", "深度学习", "Python", "语音识别"),
        "文本与语音方向的算法岗位。",
    ),
    OccupationFamily(
        "ml_algorithm", "机器学习 / 深度学习算法工程师",
        ("机器学习", "深度学习", "算法工程师", "算法专家", "强化学习", "算法开发", "算法研究员", "算法"),
        ("机器学习", "深度学习", "Python", "PyTorch", "TensorFlow", "特征工程", "模型评估"),
        "通用算法岗位；覆盖最广，作为算法类目标的默认落点。",
    ),
    OccupationFamily(
        "data_engineering", "大数据 / 数据工程",
        ("大数据", "数据开发", "数据仓库", "数据平台", "数据工程", "数据架构", "ETL", "数据中台"),
        ("数据工程", "SQL", "数据架构", "Python", "云计算"),
        "数据链路与平台建设岗位。",
    ),
    OccupationFamily(
        "data_analysis", "数据分析 / 数据挖掘",
        ("数据分析", "数据挖掘", "数据科学", "商业分析", "BI"),
        ("数据分析", "SQL", "Python", "机器学习", "概率统计", "数据可视化"),
        "分析与洞察岗位。",
    ),
    OccupationFamily(
        "ai_application", "AI 应用 / 工程化开发",
        ("AI应用", "人工智能应用", "模型部署", "推理", "AI开发", "算法工程", "AI工程", "AI平台"),
        ("大模型", "RAG", "Prompt工程", "模型部署", "Docker", "Python", "工程化"),
        "把模型落到工程与产品里的岗位。",
    ),
    OccupationFamily(
        "mlops_platform", "MLOps / 平台与运维",
        ("MLOps", "运维", "SRE", "平台工程师", "基础设施", "算力"),
        ("MLOps", "Docker", "Kubernetes", "模型部署", "云计算"),
        "训练/推理平台与运维岗位。",
    ),
    OccupationFamily(
        "ai_product", "AI 产品 / 解决方案",
        ("AI产品", "人工智能产品", "产品经理", "解决方案", "售前", "技术支持"),
        ("人工智能", "应用方向", "大模型", "数据分析", "沟通表达"),
        "面向客户与产品的岗位。",
    ),
    OccupationFamily(
        "ai_all", "人工智能相关岗位（全部）",
        (),
        ("人工智能", "机器学习", "深度学习", "Python", "大模型"),
        "未指定具体岗位时，使用全部 AI 检索语料作为目标岗位集合。",
    ),
]

BY_ID = {occ.id: occ for occ in OCCUPATIONS}


def resolve_occupation(text: str | None) -> OccupationFamily | None:
    """把自由文本解析为岗位族；无法解析返回 None（调用方必须如实记证据不足）。"""
    if text is None:
        return None
    raw = str(text).strip()
    if not raw:
        return None
    normalized = raw.lower().replace(" ", "").replace("　", "")
    if normalized in {"人工智能", "ai", "人工智能相关岗位", "ai岗位", "人工智能相关", "算法岗"}:
        return BY_ID["ai_all"]
    # 同义词表：先按"用户怎么说"归一到岗位族，避免因为语料里没有这四个字就判检索不到
    synonym = OCCUPATION_SYNONYMS.get(normalized)
    if synonym and synonym in BY_ID:
        return BY_ID[synonym]
    # 1) 标准名整体命中
    for occ in OCCUPATIONS:
        if occ.name and (occ.name in raw or normalized == occ.name.lower()):
            return occ
    # 2) 关键词命中：最长关键词优先，其次定义顺序
    best: tuple[int, int, OccupationFamily] | None = None
    for order, occ in enumerate(OCCUPATIONS):
        if occ.id == "ai_all":
            continue
        for keyword in occ.keywords:
            if keyword.lower() in normalized:
                candidate = (len(keyword), -order, occ)
                if best is None or candidate[:2] > best[:2]:
                    best = candidate
    return best[2] if best else None


def resolve_occupation_with_expansion(text: str | None) -> tuple[OccupationFamily | None, list[str]]:
    """返回（岗位族, 实际用到的检索变体）。变体按"原词 → 泛化"的顺序给出，供披露。"""
    family = resolve_occupation(text)
    variants = title_variants(text)
    if family is not None:
        for keyword in family.keywords:
            if keyword and keyword not in variants:
                variants.append(keyword)
    return family, variants


def occupation_keywords(text: str) -> list[str]:
    occ = resolve_occupation(text)
    return list(occ.keywords) if occ else []


def slice_jobs(
    jobs: Sequence[Mapping[str, Any]],
    occupation: OccupationFamily | str | None,
    *,
    min_jobs: int = MIN_OCCUPATION_JOBS,
) -> dict[str, Any]:
    """切出目标岗位族对应的岗位行，并披露匹配口径与样本量。"""
    occ = occupation if isinstance(occupation, OccupationFamily) else resolve_occupation(occupation)
    rows = list(jobs)
    if occ is None:
        return {"status": "unresolved", "occupation": None, "rows": [], "n_jobs": 0,
                "match_scope": None, "reason": "无法把目标岗位解析到已知岗位族"}
    if occ.id == "ai_all":
        return {"status": "ok" if rows else "insufficient_evidence", "occupation": occ,
                "rows": rows, "n_jobs": len(rows), "match_scope": "全部 AI 检索岗位",
                "reason": "" if rows else "招聘语料为空"}

    query_text = occupation if isinstance(occupation, str) else occ.name
    variants = [v.lower() for v in title_variants(query_text)]
    family_keywords = [k.lower() for k in occ.keywords if k]

    def hits(terms: Sequence[str], scope: str) -> list[Mapping[str, Any]]:
        if not terms:
            return []
        out = []
        for job in rows:
            text = str(job.get("position") or "")
            if scope == "position+description":
                text += str(job.get("job_description") or "")
            lowered = text.lower()
            if any(term in lowered for term in terms):
                out.append(job)
        return out

    # 泛化级联：① 用户原词/去后缀变体 → ② 家族关键词（更宽）→ ③ 连同职责一起匹配。
    # 每一步都记录用了哪些词，结果里披露 `expansion`，不会"检索不到就算了"。
    # match_scope 保持既有契约（position / position+description）；
    # "用了哪些检索词、是否泛化"放进 matched_terms / generalized / expansion，不改变旧字段语义。
    matched = hits(variants, "position")
    scope, used_terms, generalized = "position", variants, False
    if len(matched) < min_jobs:
        wider = hits(family_keywords, "position")
        if len(wider) > len(matched):
            matched, scope, used_terms, generalized = (
                wider, "position", family_keywords, True)
    if len(matched) < min_jobs:
        wider = hits(family_keywords, "position+description")
        if len(wider) > len(matched):
            matched, scope, used_terms, generalized = (
                wider, "position+description", family_keywords, True)
    status = "ok" if len(matched) >= min_jobs else "insufficient_evidence"
    return {
        "status": status,
        "occupation": occ,
        "rows": matched,
        "n_jobs": len(matched),
        "match_scope": scope,
        "keywords": list(occ.keywords),
        "query_variants": list(variants),
        "matched_terms": list(used_terms),
        "generalized": generalized,
        "expansion": (f"原词「{variants[0] if variants else ''}」检索不足 {min_jobs} 条，"
                      f"已泛化到 {'、'.join(used_terms[:6])}") if generalized else "",
        "typical_skills": list(occ.typical_skills),
        "reason": "" if status == "ok" else (
            f"语料中匹配「{occ.name}」的岗位只有 {len(matched)} 条，"
            f"低于 {min_jobs} 条门槛，不输出岗位匹配结论"),
    }


def catalogue() -> list[dict[str, Any]]:
    return [
        {"id": o.id, "name": o.name, "keywords": list(o.keywords),
         "typical_skills": list(o.typical_skills), "note": o.note}
        for o in OCCUPATIONS
    ]

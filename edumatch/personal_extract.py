"""Deterministic natural-language extraction for the micro (personal) profile.

The micro scale must accept free text such as "我学过 Python、机器学习，做过一个
RAG 项目，没有正式实习" without forcing a structured form.  The extractor here
is deliberately rule based and reproducible: it maps text to the four layers
(knowledge / skill / capability / practice) and, crucially, separates a
*declared absence* ("没有实习") from *missing evidence* (spec §29):

* ``没有正式实习`` -> recorded in ``declared.absences``; it does **not** create a
  practice item, and it is **not** interpreted as "practice = 0".
* a recognised word -> one evidence item with a deterministic strength.

No number is inferred from text.  Strengths are coarse, documented levels so
that a later deterministic stage can consume them.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

#: layer -> canonical item -> surface forms
SKILL_LEXICON: dict[str, tuple[str, ...]] = {
    "Python": ("python",),
    "Java": ("java",),
    "C++": ("c++", "cpp"),
    "C": ("c语言",),
    "SQL": ("sql", "mysql", "postgresql"),
    "PyTorch": ("pytorch", "torch"),
    "TensorFlow": ("tensorflow",),
    "RAG": ("rag", "检索增强"),
    "Agent": ("agent", "智能体"),
    "Prompt工程": ("prompt", "提示词"),
    "模型微调": ("微调", "lora", "fine-tune", "finetune"),
    "模型部署": ("模型部署", "部署", "推理加速", "vllm", "docker", "kubernetes", "k8s"),
    "数据处理": ("数据处理", "数据清洗", "pandas", "numpy"),
    "数据可视化": ("可视化", "tableau", "matplotlib"),
    "Spark": ("spark",),
    "Flink": ("flink",),
    "Hive": ("hive",),
    "Kafka": ("kafka",),
    "Web开发": ("web", "前端", "后端", "flask", "django", "spring"),
}

KNOWLEDGE_LEXICON: dict[str, tuple[str, ...]] = {
    "数学基础": ("数学", "高等数学", "线性代数", "微积分"),
    "概率统计": ("概率", "统计", "数理统计"),
    "数据结构": ("数据结构",),
    "数据库": ("数据库",),
    "机器学习": ("机器学习", "machine learning", "ml"),
    "深度学习": ("深度学习", "deep learning", "神经网络"),
    "Transformer": ("transformer", "注意力机制"),
    "大模型原理": ("大模型", "llm", "语言模型", "预训练"),
    "优化": ("优化", "最优化"),
    "计算机视觉": ("计算机视觉", "图像识别", "目标检测", "cv"),
    "自然语言处理": ("自然语言处理", "nlp", "文本挖掘"),
}

#: capability -> (kind, keyword tuple).  kind="skill" means the capability is
#: evidenced by a skill cluster; kind="action" is a named capability phrase.
CAPABILITY_LEXICON: dict[str, tuple[str, ...]] = {
    "算法研发能力": ("算法", "模型训练", "模型开发", "训练模型"),
    "AI工程开发能力": ("工程", "系统开发", "后端", "平台", "部署"),
    "AI应用设计能力": ("应用设计", "产品设计", "方案设计", "应用开发"),
    "模型评测能力": ("评测", "评估", "benchmark", "ab test"),
    "研究创新能力": ("科研", "论文", "研究", "创新", "发表"),
    "数据分析能力": ("数据分析", "数据挖掘", "建模分析"),
    "问题解决能力": ("解决问题", "问题解决", "攻坚"),
}

#: practice evidence patterns and their deterministic strength.
PRACTICE_PATTERNS: tuple[tuple[str, str, float], ...] = (
    (r"实习", "Industry Practice", 0.9),
    (r"竞赛|比赛|大赛|获奖", "Project Practice", 0.8),
    (r"开源|github|仓库", "Project Practice", 0.8),
    (r"项目|课题|系统|平台", "Project Practice", 0.7),
    (r"课程设计|课程实验|实验课|课设", "Learning Practice", 0.5),
    (r"毕业设计|毕设", "Project Practice", 0.6),
    (r"论文|专利|发表", "Research Practice", 0.8),
    (r"作品集|portfolio", "Portfolio", 0.6),
    (r"证书|认证", "Certificate", 0.5),
)

NEGATION = ("没有", "没", "无", "未", "暂无", "缺乏", "不具备", "不会", "不熟悉")
_NEGATION_WINDOW = 8


def _has_negation(text: str, start: int) -> bool:
    window = text[max(0, start - _NEGATION_WINDOW):start]
    return any(token in window for token in NEGATION)


def _match_lexicon(text: str, lexicon: dict[str, tuple[str, ...]], layer: str,
                   *, default_strength: float) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    haystack = text.lower()
    found: dict[str, dict[str, Any]] = {}
    negated: list[dict[str, Any]] = []
    for canonical, surfaces in lexicon.items():
        for surface in surfaces:
            idx = haystack.find(surface.lower())
            if idx < 0:
                continue
            if _has_negation(haystack, idx):
                negated.append({"item": canonical, "layer": layer, "surface": surface,
                                "basis": "user_declared_absence"})
                continue
            if canonical not in found:
                found[canonical] = {
                    "item": canonical, "layer": layer, "surface": surface,
                    "strength": default_strength, "evidence_type": "self_report",
                }
    return list(found.values()), negated


def extract_personal_evidence(text: str) -> dict[str, Any]:
    """Return ``{knowledge, skill, capability, practice, declared}`` evidence."""
    text = text or ""
    skill, skill_neg = _match_lexicon(text, SKILL_LEXICON, "skill", default_strength=0.7)
    knowledge, knowledge_neg = _match_lexicon(text, KNOWLEDGE_LEXICON, "knowledge",
                                              default_strength=0.6)

    capability: list[dict[str, Any]] = []
    capability_neg: list[dict[str, Any]] = []
    haystack = text.lower()
    for canonical, keywords in CAPABILITY_LEXICON.items():
        for keyword in keywords:
            idx = haystack.find(keyword.lower())
            if idx < 0:
                continue
            item = {"item": canonical, "layer": "capability", "surface": keyword,
                    "strength": 0.5, "evidence_type": "inferred_from_text"}
            if _has_negation(haystack, idx):
                capability_neg.append({**item, "basis": "user_declared_absence"})
            else:
                capability.append(item)
            break

    practice: list[dict[str, Any]] = []
    practice_neg: list[dict[str, Any]] = []
    for pattern, evidence_type, strength in PRACTICE_PATTERNS:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            item = {"item": match.group(0), "layer": "practice",
                    "evidence_type": evidence_type, "strength": strength}
            if _has_negation(text, match.start()):
                practice_neg.append({**item, "basis": "user_declared_absence"})
            else:
                practice.append(item)

    declared = {
        "absences": skill_neg + knowledge_neg + capability_neg + practice_neg,
        "note": "用户明确声明的『没有/不会』记为自述缺项，不等同于证据不足，也不记为 0。",
    }
    return {"knowledge": knowledge, "skill": skill, "capability": capability,
            "practice": practice, "declared": declared}


def iter_items(payload: dict[str, Any]) -> Iterable[dict[str, Any]]:
    for layer in ("knowledge", "skill", "capability", "practice"):
        for item in payload.get(layer) or []:
            yield {**item, "layer": layer}

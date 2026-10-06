"""Semantic evidence scoring: replace keyword hit-counting with vector matching.

For each qualitative indicator (专业设置依据、组织建设、数字化教学、校企共编教材、
企业参与课程、校企合作深度) we define **anchor phrases per level** in natural
language. The report text is chunked, embedded, and compared against those
anchors; the best-matching anchor decides the level and the score scales with the
cosine. Nothing is decided by "does the report contain this word".

Anchors and their calibrated cosines are returned with every result, so the basis
is auditable: which sentence matched, with what similarity, against which anchor.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable, Sequence

#: 每个信号：等级（强→弱）→ 锚点句（自然语言，代表该等级的证据形态）
SEMANTIC_ANCHORS: dict[str, list[tuple[str, tuple[str, ...]]]] = {
    "setup_basis": [
        ("论证充分", ("学校组织专家对专业设置进行论证，开展了行业人才需求调研并形成论证报告",
                      "新增专业经过充分论证，面向国家战略与区域产业需求")),
        ("有依据", ("依据国家和区域产业发展需要主动布局新兴专业，优化专业结构",
                    "专业设置符合学校办学定位与社会人才需求")),
        ("仅提及", ("学校设有该专业并纳入招生计划",)),
    ],
    "organization": [
        ("设有专业负责人与教学组织", ("专业设有专业负责人，成立专业建设委员会与基层教学组织定期研讨教学",
                                      "建立教学指导委员会和教研室，负责专业建设与课程管理")),
        ("仅提及组织", ("学校设有相关教学组织",)),
    ],
    "digital_teaching": [
        ("平台化+数据驱动", ("建设知识图谱与智能助教，基于学情数据开展精准教学与学习分析",
                             "构建数字化教学平台，利用人工智能技术进行教学评价与反馈")),
        ("有在线课程/平台", ("建设在线课程与虚拟仿真实验平台，开展混合式教学",
                             "开发慕课与智慧教学资源")),
        ("仅提及", ("推进教学信息化建设",)),
    ],
    "joint_textbook": [
        ("有共编教材", ("与企业联合编写教材，校企共同开发课程教材与案例库",)),
        ("仅提及", ("重视教材建设并编写校本教材",)),
    ],
    "enterprise_course": [
        ("企业参与课程开发", ("企业深度参与课程开发与教学设计，校企共同制定课程标准",)),
        ("企业导师参与", ("聘请企业导师与行业专家参与授课和实践指导",)),
        ("仅提及", ("学校开展校企合作与产教融合工作",)),
    ],
    "industry_cooperation": [
        ("joint_course_and_base", ("校企共建课程与实习基地，共建产业学院和联合实验室",)),
        ("enterprise_mentor", ("聘请企业导师参与人才培养，企业专家进课堂授课",)),
        ("internship_only", ("与用人单位共建实习实训基地，安排学生顶岗实习",)),
        ("mentioned_only", ("学校重视校企合作与产学研结合",)),
    ],
}

CHUNK_SIZE = 220
MAX_CHUNKS = 500


@dataclass
class SemanticSignal:
    signal: str
    level: str | None
    cosine: float | None
    anchor: str = ""
    evidence_quote: str = ""
    provider: str = ""
    n_chunks: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "level": self.level,
            "cosine": None if self.cosine is None else round(self.cosine, 4),
            "anchor": self.anchor[:80],
            "evidence_quote": self.evidence_quote[:120],
            "provider": self.provider,
            "n_chunks": self.n_chunks,
        }


def chunk_text(text: str, size: int = CHUNK_SIZE, limit: int = MAX_CHUNKS) -> list[str]:
    text = re.sub(r"[\s\u3000]+", " ", text or "")
    chunks = [text[i:i + size] for i in range(0, len(text), size)]
    chunks = [c.strip() for c in chunks if len(c.strip()) >= 40]
    return chunks[:limit]


class SemanticEvidenceScorer:
    """Anchor-based semantic level detection using sentence embeddings."""

    provider = "anchor_embedding_v1"
    #: 分档阈值（按等级从强到弱）。实测：真正相关 0.73–0.80，无关 0.33–0.39，
    #: 因此最高档要求 0.78，避免"相邻主题"（0.70 左右）被误判为最强证据。
    LEVEL_THRESHOLDS = (0.78, 0.62, 0.50, 0.45)

    def __init__(self, model: Any, model_name: str = "", low: float = 0.42,
                 high: float = 0.70) -> None:
        self.model = model
        self.model_name = model_name or getattr(model, "_edumatch_name", "")
        self.low = low
        self.high = high
        self._anchor_cache: dict[str, tuple[list[str], Any]] = {}

    def _anchors(self, signal: str) -> tuple[list[str], Any]:
        if signal not in self._anchor_cache:
            labels: list[str] = []
            phrases: list[str] = []
            for level, anchors in SEMANTIC_ANCHORS[signal]:
                for anchor in anchors:
                    labels.append(level)
                    phrases.append(anchor)
            self._anchor_cache[signal] = (labels, self.model.encode(phrases, normalize_embeddings=True))
        return self._anchor_cache[signal]

    def score(self, text: str) -> dict[str, SemanticSignal]:
        chunks = chunk_text(text)
        if not chunks:
            return {s: SemanticSignal(s, None, None, provider=self.provider) for s in SEMANTIC_ANCHORS}
        chunk_vectors = self.model.encode(chunks, normalize_embeddings=True, batch_size=32)
        out: dict[str, SemanticSignal] = {}
        for signal in SEMANTIC_ANCHORS:
            labels, anchor_vectors = self._anchors(signal)
            similarity = chunk_vectors @ anchor_vectors.T      # (chunks, anchors)
            best_flat = int(similarity.argmax())
            chunk_index, anchor_index = divmod(best_flat, len(labels))
            cosine = float(similarity[chunk_index, anchor_index])
            level_order = {level: i for i, (level, _) in enumerate(SEMANTIC_ANCHORS[signal])}
            required = self.LEVEL_THRESHOLDS[min(level_order[labels[anchor_index]],
                                                 len(self.LEVEL_THRESHOLDS) - 1)]
            level = labels[anchor_index] if cosine >= required else None
            out[signal] = SemanticSignal(
                signal=signal, level=level, cosine=cosine,
                anchor=labels_to_text(signal, anchor_index),
                evidence_quote=chunks[chunk_index], provider=self.provider,
                n_chunks=len(chunks),
            )
        return out


def labels_to_text(signal: str, anchor_index: int) -> str:
    flat: list[str] = []
    for _level, anchors in SEMANTIC_ANCHORS[signal]:
        flat.extend(anchors)
    return flat[anchor_index] if 0 <= anchor_index < len(flat) else ""


def semantic_score(signal: str, result: SemanticSignal | dict[str, Any] | None,
                   table: dict[str, dict[str, float]]) -> float | None:
    """Map a semantic level to a score, scaled inside the level by its cosine."""
    if not result:
        return None
    data = result.to_dict() if isinstance(result, SemanticSignal) else result
    level = data.get("level")
    if level is None:
        return None
    base = table.get(signal, {}).get(level)
    if base is None:
        return None
    cosine = data.get("cosine")
    if cosine is None:
        return base
    # 同等级内按余弦在 [low, high] 区间微调 ±5 分，避免"同档同分"掩盖证据强弱
    low, high = 0.42, 0.70
    ratio = min(max((cosine - low) / max(high - low, 1e-6), 0.0), 1.0)
    return round(base * (0.95 + 0.10 * ratio), 2)

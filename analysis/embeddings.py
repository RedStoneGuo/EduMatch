"""Vector-based semantic scoring in pure Python (no LLM in the loop).

Why: the first version used character-bigram overlap, which is deterministic but
too coarse (a short training-objective phrase scored 0.008 against a job-skill
list). This module provides real vector comparison with two interchangeable
providers, both of which are deterministic at scoring time:

* ``TfidfCosineScorer`` - scikit-learn ``TfidfVectorizer`` (char n-grams) +
  cosine similarity. Ships with the current environment, no download, no network.
* ``EmbeddingCosineScorer`` - sentence-transformers multilingual embeddings,
  used automatically **if** the package and a local model are present. The model
  is never downloaded implicitly; installing it is an explicit opt-in.

Every result records ``provider`` so an indicator can always state which scorer
produced its number - that is the audit trail that prevents "the model said so".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

import numpy as np


@dataclass
class VectorScore:
    similarity: float | None
    provider: str
    status: str = "ok"
    cosine: float | None = None
    calibration: dict[str, float] = field(default_factory=dict)
    top_terms: list[tuple[str, float]] = field(default_factory=list)
    notes: str = ""
    evidence_level: str = "D"

    def to_dict(self) -> dict[str, Any]:
        return {
            "similarity": None if self.similarity is None else round(self.similarity, 4),
            "cosine": None if self.cosine is None else round(self.cosine, 4),
            "calibration": {k: round(v, 4) for k, v in self.calibration.items()},
            "provider": self.provider,
            "status": self.status,
            "top_terms": [(t, round(w, 4)) for t, w in self.top_terms],
            "notes": self.notes,
            "evidence_level": self.evidence_level,
            "caveat": "向量余弦衡量文本语义接近程度，是可复现的代理指标，不等同于人工作出的语义等价判断。",
        }


class TfidfCosineScorer:
    """char n-gram TF-IDF + cosine similarity (works well for Chinese)."""

    provider = "tfidf_char_cosine_v1"

    def __init__(self, ngram_range: tuple[int, int] = (2, 4),
                 low: float = 0.05, high: float = 0.45) -> None:
        self.ngram_range = ngram_range
        #: 校准锚点：cosine ≤ low 视为噪声（0 分），cosine ≥ high 视为高度对齐（100 分）。
        #: 锚点取自本语料实测：无关文本 0.00–0.02，弱相关 0.05–0.12，明确相关 0.15+。
        self.low = low
        self.high = high

    def score(self, text_a: str, text_b: str, *, background: Sequence[str] = ()) -> VectorScore:
        a, b = (text_a or "").strip(), (text_b or "").strip()
        if len(a) < 6 or len(b) < 6:
            return VectorScore(None, self.provider, "insufficient_evidence",
                               notes="至少一侧文本过短（<6 字符），无法构成可比向量")
        try:
            from sklearn.feature_extraction.text import TfidfVectorizer
            from sklearn.metrics.pairwise import cosine_similarity
        except Exception:  # noqa: BLE001 - sklearn missing => caller falls back
            return VectorScore(None, self.provider, "provider_unavailable",
                               notes="scikit-learn 不可用")
        corpus = [a, b] + [t for t in background if t][:40]
        vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=self.ngram_range,
                                     min_df=1, sublinear_tf=True)
        matrix = vectorizer.fit_transform(corpus)
        similarity = float(cosine_similarity(matrix[0], matrix[1])[0][0])
        calibrated = min(max((similarity - self.low) / (self.high - self.low), 0.0), 1.0)
        above_floor = similarity >= self.low
        names = vectorizer.get_feature_names_out()
        shared = np.asarray(matrix[0].multiply(matrix[1]).todense())[0]
        top_idx = np.argsort(shared)[::-1][:8]
        top_terms = [(str(names[i]), float(shared[i])) for i in top_idx if shared[i] > 0]
        return VectorScore(
            # 低于校准下限 = 这段文本不足以支撑判断，必须记"证据不足"（None），
            # 不能压成 0 分交给下游指标（历史缺陷：S1 恒为 0）。
            calibrated if above_floor else None, self.provider,
            "ok" if above_floor else "weak_similarity",
            cosine=similarity,
            calibration={"low": self.low, "high": self.high},
            top_terms=top_terms,
            notes=(f"对比语料 {len(corpus)} 段；原始余弦 {similarity:.4f}，按锚点 "
                   f"[{self.low}, {self.high}] 校准为 {calibrated:.4f}；"
                   + ("低于下限，记证据不足（不记 0）" if not above_floor else "达到可用下限")),
        )


class EmbeddingCosineScorer:
    """Multilingual sentence embeddings (opt-in; never downloads implicitly)."""

    provider = "sentence_embedding_cosine_v1"

    def __init__(self, model_name: str = "paraphrase-multilingual-MiniLM-L12-v2",
                 min_similarity: float = 0.35) -> None:
        self.model_name = model_name
        self.min_similarity = min_similarity
        self._model = None

    def _load(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer  # noqa: PLC0415

            self._model = SentenceTransformer(self.model_name)
        return self._model

    def score(self, text_a: str, text_b: str, *, background: Sequence[str] = ()) -> VectorScore:
        a, b = (text_a or "").strip(), (text_b or "").strip()
        if len(a) < 4 or len(b) < 4:
            return VectorScore(None, self.provider, "insufficient_evidence",
                               notes="文本过短，无法嵌入")
        try:
            model = self._load()
        except Exception as exc:  # noqa: BLE001
            return VectorScore(None, self.provider, "provider_unavailable",
                               notes=f"未安装本地句子向量模型：{type(exc).__name__}")
        vectors = model.encode([a, b], normalize_embeddings=True)
        similarity = float(np.dot(vectors[0], vectors[1]))
        above_floor = similarity >= self.min_similarity
        return VectorScore(
            similarity if above_floor else None, self.provider,
            "ok" if above_floor else "weak_similarity",
            notes=f"模型 {self.model_name}；阈值 {self.min_similarity}",
        )


def get_scorer(prefer: str = "tfidf") -> Any:
    """Return the best available scorer; embeddings only when explicitly preferred."""
    if prefer in {"embedding", "sentence", "auto"}:
        scorer = EmbeddingCosineScorer()
        probe = scorer.score("人工智能专业培养目标", "岗位技能需求")
        if probe.status != "provider_unavailable":
            return scorer
    return TfidfCosineScorer()


def provider_status() -> dict[str, Any]:
    """Report which providers are usable in this environment (for the basis output)."""
    out: dict[str, Any] = {}
    try:
        import sklearn  # noqa: F401

        out["tfidf_char_cosine_v1"] = "available"
    except Exception:  # noqa: BLE001
        out["tfidf_char_cosine_v1"] = "unavailable"
    try:
        import sentence_transformers  # noqa: F401

        out["sentence_embedding_cosine_v1"] = "available (需本地模型文件)"
    except Exception:  # noqa: BLE001
        out["sentence_embedding_cosine_v1"] = "未安装（可选）"
    return out

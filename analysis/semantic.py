"""Deterministic lexical alignment used as a transparent semantic proxy.

This is deliberately *not* presented as an LLM judgment. It is a reproducible
character-bigram Jaccard index over ontology-normalised terms, tagged evidence
level ``D`` with a capped confidence. The agent may later replace it with an
embedding or LLM verdict through the same interface, and every score records
which provider produced it.
"""

from __future__ import annotations

import re
from typing import Any

_PUNCT = re.compile(r"[\s，。、；：！？“”‘’（）()《》【】\-—_/·,.、:;!?\"']+")


def _bigrams(text: str) -> set[str]:
    cleaned = _PUNCT.sub("", text or "")
    if len(cleaned) < 2:
        return {cleaned} if cleaned else set()
    return {cleaned[i : i + 2] for i in range(len(cleaned) - 1)}


def lexical_alignment(text_a: str, text_b: str) -> dict[str, Any]:
    a, b = _bigrams(text_a), _bigrams(text_b)
    if not a or not b:
        return {
            "similarity": None,
            "status": "insufficient_evidence",
            "reason": "one side has no usable text",
            "provider": "lexical_bigram_jaccard_v1",
        }
    inter = a & b
    union = a | b
    return {
        "similarity": round(len(inter) / len(union), 4),
        "status": "ok",
        "provider": "lexical_bigram_jaccard_v1",
        "evidence_level": "D",
        "n_shared_bigrams": len(inter),
        "caveat": "词汇重合度，仅作为语义一致性的可复现代理指标，不等同于语义等价判断。",
    }


def overlap_alignment(short_text: str, long_text: str) -> dict[str, Any]:
    """Overlap coefficient |A∩B| / min(|A|,|B|).

    Jaccard is the wrong measure when one side is a short label (专业名、培养目标短语)
    and the other is a long document: a 20-character phrase can only ever reach a
    tiny Jaccard, which produced meaningless scores like 3.9/100. The overlap
    coefficient answers the intended question - "how much of the short side is
    covered by the long side".
    """
    a, b = _bigrams(short_text), _bigrams(long_text)
    if not a or not b:
        return {
            "similarity": None,
            "status": "insufficient_evidence",
            "reason": "one side has no usable text",
            "provider": "lexical_overlap_v1",
        }
    inter = a & b
    return {
        "similarity": round(len(inter) / min(len(a), len(b)), 4),
        "status": "ok",
        "provider": "lexical_overlap_v1",
        "evidence_level": "D",
        "caveat": "短文本被长文本覆盖的比例，作为语义一致性的可复现代理指标；越接近 1 表示短文本的用词基本都能在长文本中找到。",
    }


def term_overlap_ratio(terms: list[str], text: str) -> dict[str, Any]:
    if not terms:
        return {"ratio": None, "status": "insufficient_evidence", "matched": [], "missing": []}
    matched = [t for t in terms if t and t in (text or "")]
    return {
        "ratio": round(len(matched) / len(terms), 4),
        "status": "ok",
        "matched": matched,
        "missing": [t for t in terms if t not in matched],
        "provider": "term_overlap_v1",
    }

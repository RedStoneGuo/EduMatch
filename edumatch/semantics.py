"""Report language guard (spec §8, §36) - the "quantity claim" firewall.

The engine is already careful about missing data.  Reports drifted anyway:
"北京市人工智能专业总供给", "AI 岗位总需求", "13 所代表全市" are wording
errors, not data errors.  This module centralises the forbidden quantity claims
so both the validator and the report renderer can use one list.

Contract:

* :func:`find_forbidden_claims` - used by ``scripts/validate_edumatch.py``;
* :func:`canonicalize` - used when a report must be written from text that may
  contain the legacy wording;
* :func:`observed_demand_phrase` - the single approved phrasing for posting
  counts.
"""

from __future__ import annotations

import re
from typing import Any

OBSERVED_DEMAND_PHRASE = "条可观察岗位招聘记录（Observed Job Posting Demand）"
SUPPLY_PHRASE = "本研究覆盖高校的人工智能相关人才培养能力供给"

#: (regex, forbidden meaning, approved replacement)
FORBIDDEN_CLAIMS: tuple[tuple[str, str, str], ...] = (
    (r"北京市人工智能专业总供给",
     "把覆盖院校课程池当成全市总供给",
     SUPPLY_PHRASE),
    (r"人工智能专业总供给",
     "把覆盖院校课程池当成全市总供给",
     SUPPLY_PHRASE),
    (r"北京市[^，。；\n]{0,12}人才总供给",
     "缺乏可核查的全市人才总量，不得作总供给表述",
     SUPPLY_PHRASE),
    (r"AI\s*岗位总需求",
     "招聘记录不等于岗位总需求",
     "可观察 AI 岗位招聘记录（Observed Job Posting Demand）"),
    (r"岗位总需求",
     "招聘记录不等于岗位总需求",
     "可观察岗位招聘记录"),
    (r"总需求量",
     "招聘记录不等于总需求量",
     "可观察招聘记录量"),
    (r"人才需求总量",
     "招聘记录不等于人才需求总量",
     "可观察岗位招聘记录"),
    (r"社会岗位总需求",
     "招聘语料不能代表社会岗位总需求",
     "可观察岗位招聘记录"),
    (r"岗位真实总需求",
     "本地数据无法支持真实岗位总量",
     "可观察岗位招聘记录"),
    (r"就业总人数",
     "本地数据无法支持就业总人数",
     "本研究覆盖院校的可核查就业结果"),
    (r"16,?161\s*个岗位需求",
     "16,161 是去重后的可观察招聘记录数，不是岗位需求数",
     "16,161 条可观察岗位招聘记录"),
    (r"13\s*所[^，。；\n]{0,16}代表[^，。；\n]{0,8}北京[^，。；\n]{0,8}全部",
     "13 所是本地入库样本，不代表全市全部高校",
     "本地入库 13 所高校样本（非全市全量）"),
    (r"北京市共有[^，。；\n]{0,10}个\s*AI\s*岗位",
     "招聘记录是样本，不是全市岗位总量",
     "本数据窗口观察到 16,161 条 AI 相关可观察岗位招聘记录"),
)

_COMPILED = tuple((re.compile(pattern), meaning, replacement)
                  for pattern, meaning, replacement in FORBIDDEN_CLAIMS)

#: 否定/免责语境：紧跟其后的短语是在"澄清不是"，不是在"断言是"。
NEGATION_CUES = ("不是", "不代表", "并非", "不等于", "不能", "不得", "不应",
                 "非", "绝不", "而不是", "区别于")
_NEGATION_WINDOW = 12


def _is_disclaimer(text: str, start: int) -> bool:
    window = text[max(0, start - _NEGATION_WINDOW):start]
    return any(cue in window for cue in NEGATION_CUES)


def find_forbidden_claims(text: str) -> list[dict[str, Any]]:
    """Return every forbidden quantity claim with its position and fix."""
    findings: list[dict[str, Any]] = []
    for regex, meaning, replacement in _COMPILED:
        for match in regex.finditer(text or ""):
            if _is_disclaimer(text, match.start()):
                continue
            findings.append({
                "pattern": regex.pattern,
                "match": match.group(0),
                "position": match.start(),
                "meaning": meaning,
                "suggestion": replacement,
            })
    return findings


def canonicalize(text: str) -> str:
    """Replace every forbidden quantity claim with the approved phrasing."""
    out = text or ""
    for regex, _meaning, replacement in _COMPILED:
        out = regex.sub(lambda m: m.group(0) if _is_disclaimer(out, m.start()) else replacement, out)
    return out


def guard_report_text(text: str) -> dict[str, Any]:
    findings = find_forbidden_claims(text)
    return {"ok": not findings, "n_findings": len(findings),
            "findings": findings, "clean_text": canonicalize(text)}


def observed_demand_phrase(n: int | str) -> str:
    """The one approved way to state a posting count."""
    return f"{n}{OBSERVED_DEMAND_PHRASE}"


def supply_phrase() -> str:
    return SUPPLY_PHRASE

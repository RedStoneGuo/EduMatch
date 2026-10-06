"""Skill ontology: alias resolution, hierarchy traversal, text normalisation.

Resolution is layered so that plain string matching is only the first recall
step, not the decision step:

1. exact alias hit on a normalised surface form;
2. longest-alias containment with word-boundary guard for Latin tokens;
3. ontology propagation from child skill to ancestor skills;
4. optional semantic re-check (embedding / LLM) provided by a pluggable hook.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Sequence

import yaml

from .config import load_settings

_LATIN = re.compile(r"[A-Za-z]")
_NON_ALNUM = re.compile(r"[^0-9a-zA-Z\u4e00-\u9fff+#\.]+")


def normalize_text(text: str) -> str:
    text = (text or "").lower()
    text = _NON_ALNUM.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


class _Trie(dict):
    """Minimal alias trie: prefix -> node, with '$' marking a canonical skill."""


@dataclass
class Skill:
    skill_id: str
    name: str
    aliases: list[str] = field(default_factory=list)
    category: str = "未分类"
    parents: list[str] = field(default_factory=list)
    children: list[str] = field(default_factory=list)
    related: list[str] = field(default_factory=list)
    industries: list[str] = field(default_factory=list)


@dataclass
class SkillMention:
    surface: str
    skill_id: str
    matched_alias: str
    match_type: str  # exact | containment | propagation | semantic
    position: int


class SkillOntology:
    def __init__(self, data: dict[str, Any], source: Path | None = None) -> None:
        self.source = source
        self.skills: dict[str, Skill] = {}
        self._alias_index: dict[str, str] = {}
        self._alias_display: dict[str, str] = {}
        self.course_rules: list[dict[str, Any]] = []
        self.industry_directions: dict[str, dict[str, Any]] = {}
        self._build(data)

    # ---------- construction ----------
    def _build(self, data: dict[str, Any]) -> None:
        tree = data.get("skill_tree") or {}
        for domain_name, domain in tree.items():
            self._walk(domain_name, domain, parents=[])
        self.course_rules = list(data.get("course_skill_rules") or [])
        for name, spec in (data.get("industry_directions") or {}).items():
            spec = dict(spec or {})
            spec["name"] = name
            self.industry_directions[name] = spec

    def _walk(self, name: str, node: dict[str, Any], parents: list[str]) -> str:
        node = dict(node or {})
        skill = Skill(
            skill_id=self._sid(name),
            name=name,
            aliases=list(node.get("aliases") or []),
            category=node.get("category") or (parents[-1] if parents else "领域"),
            parents=list(parents),
        )
        self.skills[skill.skill_id] = skill
        self._register_alias(skill, name, primary=True)
        for alias in skill.aliases:
            self._register_alias(skill, str(alias))
        for child_name, child_node in (node.get("skills") or {}).items():
            child_id = self._walk(child_name, child_node or {}, parents=[*parents, name])
            skill.children.append(child_id)
        return skill.skill_id

    def _register_alias(self, skill: Skill, alias: str, primary: bool = False) -> None:
        key = normalize_text(alias)
        if not key or key in self._alias_index:
            return
        self._alias_index[key] = skill.skill_id
        self._alias_display[key] = alias if not primary else skill.name

    @staticmethod
    def _sid(name: str) -> str:
        return "skill:" + normalize_text(name).replace(" ", "_")

    # ---------- queries ----------
    def get(self, skill_id: str) -> Skill | None:
        return self.skills.get(skill_id)

    def by_name(self, name: str) -> Skill | None:
        key = normalize_text(name)
        sid = self._alias_index.get(key)
        return self.skills.get(sid) if sid else None

    def ancestors(self, skill_id: str) -> list[str]:
        skill = self.skills.get(skill_id)
        if not skill:
            return []
        out: list[str] = []
        for parent_name in skill.parents:
            pid = self._sid(parent_name)
            out.append(pid)
            out.extend(self.ancestors(pid))
        return out

    def descendants(self, skill_id: str) -> list[str]:
        out: list[str] = []
        for child in self.skills.get(skill_id, Skill("", "")).children:
            out.append(child)
            out.extend(self.descendants(child))
        return out

    def all_skills(self) -> list[Skill]:
        return list(self.skills.values())

    def leaf_skills(self) -> list[Skill]:
        return [s for s in self.skills.values() if not s.children]

    # ---------- matching ----------
    def extract(self, text: str, *, propagate: bool = True) -> list[SkillMention]:
        """Extract skill mentions from free text (course description, JD, policy)."""
        norm = normalize_text(text)
        mentions: dict[str, SkillMention] = {}
        for alias, sid in self._alias_index.items():
            if not alias:
                continue
            pos = norm.find(alias)
            if pos < 0:
                continue
            if _LATIN.search(alias):
                if not self._latin_boundary_ok(norm, pos, len(alias)):
                    continue
                match_type = "exact" if norm == alias else "containment"
            else:
                match_type = "exact" if norm == alias else "containment"
            prev = mentions.get(sid)
            if prev is None or len(alias) > len(prev.matched_alias):
                mentions[sid] = SkillMention(
                    surface=self._surface(text, alias),
                    skill_id=sid,
                    matched_alias=alias,
                    match_type=match_type,
                    position=pos,
                )
        if propagate:
            for sid in list(mentions):
                for ancestor in set(self.ancestors(sid)):
                    if ancestor in mentions or ancestor not in self.skills:
                        continue
                    mentions[ancestor] = SkillMention(
                        surface=mentions[sid].surface,
                        skill_id=ancestor,
                        matched_alias=mentions[sid].matched_alias,
                        match_type="propagation",
                        position=mentions[sid].position,
                    )
        return sorted(mentions.values(), key=lambda m: (m.position, m.skill_id))

    def match_course(self, course_name: str, description: str = "") -> list[str]:
        """Return canonical skills implied by a course, using the rule table."""
        blob = f"{course_name} {description}"
        norm = normalize_text(blob)
        hits: list[str] = []
        for rule in self.course_rules:
            patterns = [normalize_text(p) for p in rule.get("pattern", [])]
            if any(p and p in norm for p in patterns):
                for raw_skill in rule.get("skills", []):
                    skill = self.by_name(str(raw_skill))
                    if skill:
                        hits.append(skill.skill_id)
                        hits.extend(self.ancestors(skill.skill_id))
        for mention in self.extract(blob):
            hits.append(mention.skill_id)
        return sorted(set(hits))

    @staticmethod
    def _latin_boundary_ok(text: str, pos: int, length: int) -> bool:
        before = text[pos - 1] if pos > 0 else " "
        after = text[pos + length] if pos + length < len(text) else " "
        return not (_LATIN.match(before) or _LATIN.match(after))

    @staticmethod
    def _surface(text: str, alias: str) -> str:
        idx = normalize_text(text).find(alias)
        return alias if idx < 0 else alias


@lru_cache(maxsize=4)
def load_ontology(path: str | None = None) -> SkillOntology:
    settings = load_settings()
    target = Path(path) if path else settings.ontology_path
    with target.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return SkillOntology(data, source=target)


def canonical_ids(names: Iterable[str]) -> list[str]:
    onto = load_ontology()
    out: Sequence[str] = [onto.by_name(n).skill_id for n in names if onto.by_name(n)]
    return list(out)

"""Research engine: query -> plan -> tools -> metrics -> evidence -> report.

This module is the deterministic core that the agent wraps. It can be executed
without any LLM, which is what makes the numbers reproducible.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from analysis import benchmark as benchmark_mod
from analysis import demand as demand_mod
from analysis import fit as fit_mod
from analysis import matching as matching_mod
from analysis import mechanism as mechanism_mod
from analysis import metric_graph as metric_graph_mod
from analysis import occupation_match as occupation_match_mod
from analysis import objective_alignment as objective_alignment_mod
from analysis import conflict_resolution as conflict_mod
from analysis import primary_tsi as primary_mod
from analysis import simulation as simulation_mod
from analysis import skill_gap as gap_mod
from analysis import supply as supply_mod
from analysis import trend as trend_mod
from analysis import tsi as tsi_mod
from analysis import tsi_v1 as tsi_v1_mod
from analysis.embeddings import get_scorer, provider_status
from analysis.semantic_evidence import SemanticEvidenceScorer, semantic_score
from edumatch.config import Settings, load_settings
from edumatch import retrieval_sweep
from edumatch.dataset import FAMILY_MAJOR, Dataset
from edumatch.evidence import EvidenceItem, EvidenceStore
from edumatch import occupation as occupation_mod

MODE_PATTERNS: list[tuple[str, str]] = [
    ("模拟", "G_curriculum_simulation"),
    ("政策", "F_policy_mechanism"),
    ("机制", "F_policy_mechanism"),
    ("缺口", "E_skill_gap"),
    ("趋势", "D_trend"),
    ("对比", "C_benchmark"),
    ("比较", "C_benchmark"),
    ("报告", "H_full_report"),
    ("画像", "B_school_major"),
]

@dataclass
class ResearchPlan:
    query: str
    mode: str
    major: str
    family: str
    school: str | None
    year: int | None
    steps: list[dict[str, Any]] = field(default_factory=list)
    include_template: bool = False
    #: 目标岗位（模型输入之一）：院校 + 专业 + 目标岗位 → 岗位匹配度
    target_occupation: str | None = None
    #: 专业目录键（任意专业支持）：family 为空时仍可分析，用它做课程/事实作用域
    major_key: str = ""
    #: 专业数据覆盖情况（课程数/院校数/就业行数），供报告与数据质量披露
    major_coverage: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


def detect_major(query: str, dataset: Dataset | None = None, default: str = "人工智能") -> tuple[str, str | None]:
    """把问题里的专业解析到"有数据的专业"。

    解析顺序：

    1. 三个专业族的别名（ai/cs/econ）——保留族特有口径（本体、岗位关键词表）；
    2. **专业目录**（培养方案课程库 + 就业分专业行，覆盖 1,400+ 专业）——任意专业；
    3. 都没有 → 记 ``family=None``，由 ``-`` 返回"该专业无数据"的如实答复。

    返回 ``(专业名, 族或 None)``；族为 None 表示"通用专业模式"，不代表无法分析。
    """
    from edumatch.dataset import FAMILY_ALIASES

    available = dataset.available_families if dataset else {"ai": "", "cs": "", "econ": ""}
    # 1) 显性别名匹配（取最长命中，避免"智能"盖过"人工智能"）
    hits = sorted(
        ((alias, family) for alias, family in FAMILY_ALIASES.items() if alias in query),
        key=lambda kv: -len(kv[0]),
    )
    for alias, family in hits:
        if family in available:
            return _major_phrase(query, alias) or alias, family
    # 2) 用户新增的专业族（data/raw/majors_<family>.txt）直接按名字命中
    for family in available:
        if family in query:
            return family, family
    # 3) 归档没有该专业：只提取名字用于如实告知，绝不回退到别的专业族
    phrase = _major_phrase(query)
    if phrase:
        # 3.1) 先查"专业目录"（培养方案 + 就业分专业行，覆盖上千专业）
        if dataset is not None:
            hit = dataset.find_major(phrase)
            if hit:
                key, ref = hit
                return ref.name, ref.family
        return phrase, None
    # 未点名任何专业（例如"证据检索""结论溯源"这类内部查询）→ 使用默认专业族
    default_family = FAMILY_ALIASES.get(default.lower(), FAMILY_ALIASES.get(default, "ai"))
    return default, default_family


MAJOR_PHRASE = re.compile(r"([\u4e00-\u9fffA-Za-z]{2,15}?)(?:专业|学科|方向|类)")
#: 这些词出现在候选短语里，说明它不是专业名（"就业政策有哪些主要方向"）。
NOT_A_MAJOR = ("政策", "就业", "高校", "院校", "有哪些", "哪些", "主要", "如何", "怎么",
               "趋势", "情况", "建议", "方案", "报告", "缺口", "适配", "分析", "评估")


def _major_phrase(query: str, anchor: str | None = None) -> str | None:
    """Pull the major name out of a free-text question (e.g. '机械工程专业' -> '机械工程')."""
    if anchor:
        # 已知别名命中：以别名为起点向后取到"专业/学科/方向"为止，
        # 这样"北京工业大学人工智能专业"→"人工智能"，
        # "音乐人工智能与音乐信息科技专业"→"音乐人工智能与音乐信息科技"。
        idx = query.find(anchor)
        if idx >= 0:
            tail = query[idx: idx + len(anchor) + 10]
            found = MAJOR_PHRASE.match(tail)
            phrase = found.group(1) if found else anchor
            # "人工智能产业政策对…" 这类噪声里含非专业词时，退回规范别名本身
            return anchor if any(bad in phrase for bad in NOT_A_MAJOR) else phrase
    match = MAJOR_PHRASE.search(query)
    if match:
        phrase = match.group(1)
        # 先去掉可能被一起吞掉的动词前缀，再判断是不是专业名
        for prefix in ("分析", "评估", "测评", "研究", "看看", "帮我", "请", "识别", "生成", "的"):
            if phrase.startswith(prefix) and len(phrase) > len(prefix) + 1:
                phrase = phrase[len(prefix):]
        if any(bad in phrase for bad in NOT_A_MAJOR):
            return None
        return phrase or None
    return None


FAMILY_MAJOR_REVERSE = {v: k for k, v in FAMILY_MAJOR.items()}


def detect_school(query: str, schools: list[str]) -> str | None:
    """识别目标高校：先匹配数据集内校名，再识别任意"XX大学/学院"。

    关键：即使这所学校不在数据集里，也必须识别出来并标记为"该校无数据"，
    否则会被当成"未指定高校"而给出区域口径结论——那是另一种张冠李戴。
    """
    for school in schools:
        if school and school in query:
            return school
    short = {"北京大学": "北大", "清华大学": "清华", "北京工业大学": "北工大",
             "北京交通大学": "北交大", "北京邮电大学": "北邮"}
    for full, abbr in short.items():
        if abbr in query and full in schools:
            return full
    match = SCHOOL_NAME_PATTERN.search(query)
    if not match:
        return None
    name = match.group(1)
    # 去掉被正则一起吞掉的动词前缀（"分析复旦大学" → "复旦大学"）
    prefixes = ("分析", "评估", "测评", "研究", "看看", "帮我", "请", "识别", "生成",
                "对比", "比较", "关于", "针对", "查询", "检索", "评价", "调查", "了解")
    changed = True
    while changed:      # 允许多个前缀叠加（"请评估上海交通大学"）
        changed = False
        for prefix in prefixes:
            while name.startswith(prefix) and len(name) > len(prefix) + 3:
                name = name[len(prefix):]
                changed = True
    return name


#: 任意院校名（"XX大学" / "XX学院"），用于识别数据集之外的院校。
SCHOOL_NAME_PATTERN = re.compile(r"([\u4e00-\u9fff]{2,12}(?:大学|学院))")


#: 未点名具体岗位、但问题指向"岗位匹配"时，各专业族的默认目标岗位。
#: 只有人工智能族有明确的默认（=全部 AI 检索岗位）；其余族必须显式给出目标岗位。
DEFAULT_OCCUPATION_BY_FAMILY = {"ai": "人工智能相关岗位（全部）"}
JOB_INTENT_HINTS = ("岗位", "职位", "招聘", "匹配度", "对口", "能胜任", "就业方向")


def detect_occupation(query: str, family: str | None) -> str | None:
    """从问题文本解析目标岗位；解析不到就留空（不做猜测）。"""
    occupation = occupation_mod.resolve_occupation(query)
    if occupation and occupation.id != "ai_all":
        return occupation.name
    if any(hint in query for hint in JOB_INTENT_HINTS) and family:
        return DEFAULT_OCCUPATION_BY_FAMILY.get(family)
    return occupation.name if occupation else None


def build_plan(
    query: str, dataset: Dataset, *, major: str | None = None, school: str | None = None,
    occupation: str | None = None,
) -> ResearchPlan:
    detected_major, family = detect_major(query, dataset, default=major or "人工智能")
    major = major or detected_major
    hit = dataset.find_major(major) if dataset else None
    ref = hit[1] if hit else None
    analyzable = bool(ref and ref.analyzable)
    if family is None and not analyzable:
        return ResearchPlan(
            query=query, mode="X_unknown_major", major=major, family="",
            school=school, year=None,
            target_occupation=occupation or detect_occupation(query, None),
            steps=[{"id": 1, "skill": "01_evidence_retrieval",
                    "action": f"检查归档中是否存在 {major} 的数据"}],
        )
    family = family or (ref.family if ref else "") or ""
    # 学校识别用**全部**学校名（不能只看该专业族，否则"北京工业大学"会因为
    # 该校没有人工智能专业行而识别失败，进而错误回退到别的学校的数据）
    school = school or detect_school(query, dataset.schools())
    target_occupation = occupation or detect_occupation(query, family)
    schools = dataset.schools(family)
    mode = "A_major_analysis"
    for keyword, candidate in MODE_PATTERNS:
        if keyword in query:
            mode = candidate
            break
    if school:
        mode = "B_school_major_analysis" if mode == "A_major_analysis" else mode
    steps = [
        {"id": 1, "skill": "01_evidence_retrieval", "action": "检索教育、招聘、政策与文献证据"},
        {"id": 2, "skill": "05_skill_ontology", "action": "把课程与岗位文本归一化到统一技能本体"},
        {"id": 3, "skill": "02_curriculum_analysis", "action": "构建课程—技能矩阵与技能供给"},
        {"id": 4, "skill": "03_employment_analysis", "action": "从就业质量报告提取就业结果指标"},
        {"id": 5, "skill": "04_job_market_analysis", "action": "计算岗位与技能需求强度"},
        {"id": 6, "skill": "06_matching_model", "action": "计算需求加权匹配度与 Skill Gap"},
        {"id": 7, "skill": "07_policy_mechanism", "action": "政策—产业—技能关联与机制分析"},
        {"id": 8, "skill": "08_audit_and_report", "action": "生成证据链报告与审计记录"},
    ]
    if mode in {"G_curriculum_simulation", "H_full_report"}:
        steps.insert(7, {"id": 7, "skill": "06_matching_model", "action": "运行培养方案模拟（what-if）"})
        for i, step in enumerate(steps, start=1):
            step["id"] = i
    return ResearchPlan(
        query=query, mode=mode, major=major, family=family, school=school,
        year=dataset.years(family)[-1] if dataset.years(family) else None, steps=steps,
        target_occupation=target_occupation,
        major_key=(ref.key if ref else ""),
        major_coverage=(ref.to_dict() if ref else {}),
    )


class ResearchEngine:
    """Deterministic research pipeline used by the agent and the demo UI."""

    def __init__(self, dataset: Dataset | None = None, settings: Settings | None = None) -> None:
        self.settings = settings or load_settings()
        self.dataset = dataset or Dataset.build(self.settings)
        self.ontology = self.dataset.ontology
        self.tool_calls: list[dict[str, Any]] = []
        self._skill_name_cache: dict[tuple[str, str], list[str]] = {}
        #: 通用专业模式（专业族未覆盖）：用课程派生词表建统一技能空间
        self._course_derived_mode = False
        #: 共享技能词表的构建统计（供报告披露"两侧到底在不在同一套词表上"）
        self._vocabulary_stats: dict[str, Any] = {}

    # ---------- tool logging ----------
    def _call_tool(self, name: str, args: dict[str, Any], fn: Callable[[], Any]) -> Any:
        started = datetime.now(timezone.utc)
        try:
            result = fn()
            status = "ok"
            error = None
        except Exception as exc:  # noqa: BLE001
            result, status, error = None, "error", str(exc)
        self.tool_calls.append(
            {
                "tool": name,
                "arguments": args,
                "status": status,
                "error": error,
                "elapsed_ms": round((datetime.now(timezone.utc) - started).total_seconds() * 1000, 2),
                "result_summary": _summarize(result),
            }
        )
        if status == "error":
            raise RuntimeError(f"tool {name} failed: {error}")
        return result

    # ---------- 数据来源模式（local / plugin / hybrid） ----------
    def _build_skill_vocabulary(self, plan: ResearchPlan, courses: list[dict[str, Any]],
                                ds: Dataset) -> tuple[set[str], dict[str, Any]]:
        """为**任意专业**构建唯一一套技能词表（无核心/非核心之分）。

        词表 = 岗位术语挖掘 ∪ 课程语料候选 ∪ 本体种子词，按「相对背景语料的提升度」
        过滤通用词，用最长匹配吸收子串碎片。只出现在岗位、课程没教的词**保留**，
        其供给自然为 0——这正是"市场要、学校没教"的缺口信号。
        """
        from . import skills_mining

        course_texts = [
            skills_mining.clean_course_text(c.get("name") or "", c.get("description") or "",
                                            extra_noise=(plan.major or "", plan.school or ""))
            for c in courses
        ]
        scoped = ds.major_scope_jobs(plan.major)
        source_rows = scoped or ds.target_jobs()
        job_texts = [
            " ".join(str(j.get(k) or "") for k in ("position", "job_description"))
            for j in source_rows[:3000]
        ]
        # 背景语料：全库岗位抽样，用来判断"这个词是不是这个专业特有的"
        background = ds.vocabulary_background_texts(exclude_major=plan.major, limit=2000)
        seeds = [s.name for s in ds.ontology.all_skills()] if ds.ontology else []
        curated = self._load_curated_vocabulary(plan.major)
        mined = skills_mining.mine_skill_vocabulary(
            course_texts, job_texts, background_texts=background, seed_terms=seeds,
            curated_terms=curated)
        stats = {**mined["stats"], "demand_rows_used": len(job_texts),
                 "demand_source": "major_export" if scoped else "keyword_corpus"}
        vocabulary = set(mined["terms"])
        if not vocabulary:
            fallback = set()
            for course in courses:
                term = re.sub(r"[（(][^）)]{0,12}[）)]", "", str(course.get("name") or ""))
                term = re.sub(r"\s+", "", term).strip("　·-")
                if 2 <= len(term) <= 20:
                    fallback.add(term)
            stats["fallback"] = "词表为空，回退为课程名派生的能力项"
            vocabulary = fallback
        return vocabulary, stats

    def _load_curated_vocabulary(self, major: str | None) -> list[str]:
        """Agent/人工确认过的技能词表（``data/skill_vocabularies/<专业>.json``）。

        统计挖掘只能给出候选，**是不是技能由 Agent 判定**。Agent 把确认结果写进该文件，
        流水线下次就会采用；文件不存在则完全依赖统计候选，不影响跑通。
        """
        if not major:
            return []
        path = self.settings.project_root / "data" / "skill_vocabularies" / f"{major}.json"
        if not path.exists():
            return []
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return []
        terms = payload.get("terms") if isinstance(payload, dict) else payload
        return [str(t).strip() for t in (terms or []) if str(t).strip()]

    def _preview_courses(self, plan: ResearchPlan, include_template: bool) -> list[dict[str, Any]]:
        """供建词表用的课程预览，作用域与 ``_supply_context`` 保持一致。"""
        ds = self.dataset
        if plan.school:
            courses = ds.course_set(school=plan.school, family=plan.family, major=plan.major,
                                    include_template=include_template)
            if courses:
                return courses
        courses = ds.course_set(family=plan.family, major=plan.major,
                                include_template=include_template)
        if not courses:
            courses = ds.course_set(major=plan.major, include_template=include_template)
        return courses or ds.course_set(include_template=include_template)

    def _prepare_source(
        self, plan: ResearchPlan, *, source_mode: str | None, harvest: bool,
        harvest_domain: str | None = None, harvest_kinds: list[str] | None = None,
        harvest_pages: list[dict[str, str]] | None = None,
        harvest_timeout_s: int | None = None,
        peers: str | list[str] | None = None,
        peer_max: int = 3,
        peer_harvest_kinds: list[str] | None = None,
    ) -> dict[str, Any]:
        """按模式装配供给端：必要时联网跑插件收割，然后把收割数据并入 Dataset。"""
        from .source_modes import (SupplySourceReport, normalize_mode,
                                   resolve_school_domain, run_plugin_harvest, uses_harvest)

        ds = self.dataset
        root = ds.settings.project_root
        configured = (self.settings.section("data_source") or {}).get("mode") or "local"
        mode = normalize_mode(source_mode or configured)
        report = SupplySourceReport(mode=mode, harvest_school=plan.school or "")
        if not uses_harvest(mode):
            ds._apply_source_mode(mode, ())
            report.local_courses = ds.source_counts.get("local_courses", 0)
            report.local_facts = ds.source_counts.get("local_facts", 0)
            report.notes.append("供给端使用本地数据；需求端仍取本地招聘语料。")
            return report.to_dict()

        school = plan.school or ""
        if school:
            report.harvest_domain = harvest_domain or resolve_school_domain(
                ds.settings.project_root, school)
        if harvest and school:
            report.harvest_requested = True
            if not report.harvest_domain:
                report.error = (f"未核实 {school} 的官方域名；插件红线是不猜域名，"
                                f"请把域名写入 data/harvest/domains.json 或显式传入。")
            else:
                try:
                    outcome, import_result = run_plugin_harvest(
                        ds.settings, school, domain=report.harvest_domain,
                        kinds=harvest_kinds, pages=harvest_pages,
                        timeout_s=harvest_timeout_s,
                    )
                    report.harvest_performed = True
                    report.harvest_backend = outcome.backend
                    report.harvest_state = outcome.state
                    report.harvest_out_dir = outcome.out_dir
                    report.harvest_records = outcome.by_kind()
                    report.harvest_import = import_result.to_dict()
                    if outcome.n_materials == 0:
                        report.notes.append(
                            "插件未采到材料（站点无公开源/被拦截/需登录）——未做任何推断。")
                except Exception as exc:  # noqa: BLE001 - 联网失败不应中断本地可用分析
                    report.error = f"{type(exc).__name__}: {exc}"
        elif harvest and not school:
            report.notes.append("plugin/hybrid 模式需要点名院校才能定位官方域名，本次未点名。")

        # ---- 同类院校（peer benchmark）：全国口径，可解释排序 ----
        peer_schools: list[str] = []
        if school and peers != "none":
            from .peers import PeerSelector

            selector = PeerSelector.from_project(root)
            if isinstance(peers, (list, tuple)) and peers:
                report.peer_selector = "explicit"
                info: dict[str, Any] = {"note": "调用方显式指定的同类院校"}
                for name in peers:
                    uni = selector.catalog.get(str(name))
                    report.peer_candidates.append({
                        "school": str(name),
                        "domain": selector.domains.get(str(name), ""),
                        "tiers": list(uni.tiers) if uni else [],
                        "province": uni.province if uni else "",
                        "city": uni.city if uni else "",
                        "score": 0.0, "reasons": ["调用方指定"],
                        "harvestable": bool(selector.domains.get(str(name))),
                    })
            else:
                report.peer_selector = "auto"
                candidates, info = selector.resolve(school, major=plan.major, max_peers=peer_max)
                report.peer_candidates = [c.to_dict() for c in candidates]
            report.peer_note = str(info.get("note") or "")
            for item in report.peer_candidates:
                name = str(item.get("school") or "")
                if not name:
                    continue
                if (root / "data" / "harvest" / name / "courses.json").exists():
                    report.peer_reused.append(name)
                    peer_schools.append(name)
                    continue
                if not item.get("domain"):
                    report.peer_skipped.append(
                        {"school": name, "reason": "未核实官方域名（插件不猜域名）"})
                    continue
                if not harvest:
                    report.peer_skipped.append(
                        {"school": name, "reason": "未开启联网采集（需要 --harvest）"})
                    continue
                try:
                    _, imported = run_plugin_harvest(
                        ds.settings, name, domain=str(item["domain"]),
                        kinds=peer_harvest_kinds or ["培养方案"],
                        timeout_s=harvest_timeout_s,
                    )
                    if (root / "data" / "harvest" / name / "courses.json").exists():
                        report.peer_harvested.append(name)
                        peer_schools.append(name)
                    else:
                        report.peer_skipped.append({
                            "school": name,
                            "reason": f"采集完成但未解析出课程（入库 {len(imported.installed)} 份）",
                        })
                except Exception as exc:  # noqa: BLE001 - 单校失败不中断整体分析
                    report.peer_skipped.append(
                        {"school": name, "reason": f"{type(exc).__name__}: {exc}"})

        harvest_schools = tuple([school] if school else []) + tuple(peer_schools)
        ds._apply_source_mode(mode, harvest_schools)
        report.local_courses = ds.source_counts.get("local_courses", 0)
        report.harvest_courses = ds.source_counts.get("harvest_courses", 0)
        report.local_facts = ds.source_counts.get("local_facts", 0)
        report.harvest_facts = ds.source_counts.get("harvest_facts", 0)
        if not ds.harvest_schools and mode == "plugin":
            report.notes.append(
                "尚无该院校的插件收割产物：目标校供给记 insufficient_evidence，"
                "不挪用其它院校数据；可加 --harvest 联网采集。")
        return report.to_dict()

    # ---------- context builders ----------
    def _teaching_context(self, plan: ResearchPlan, evidence: EvidenceStore) -> tuple[dict[str, Any], dict[str, list[str]]]:
        ds = self.dataset
        ids: dict[str, list[str]] = {}
        out: dict[str, Any] = {}
        # 培养目标原文：从教学质量报告 + 培养方案/专业介绍正文里定位候选段落。
        # 关键：必须过滤掉"选课要求/学分/目录"这类样板文字，否则会把无关片段
        # 当成培养目标，再被旧逻辑压成 0 分（S1 历史缺陷）。
        report_text = ds.school_text(plan.school)
        major_name = plan.major or ""
        # 全面检索台账：本地正文缓存 → 规范一手材料 → 归档 → 采集产物 → 联网插件
        ledger = retrieval_sweep.sweep_sources(
            self.settings.project_root, school=plan.school, major=major_name,
            materials=("培养目标",))
        out["retrieval_ledger"] = ledger
        candidates = [
            objective_alignment_mod.ObjectiveCandidate(
                text=str(item.get("text") or ""),
                anchor=str(item.get("anchor") or ""),
                position=int(item.get("position") or -1),
                marker_hits=int(item.get("marker_hits") or 0),
                boilerplate_hits=int(item.get("boilerplate_hits") or 0),
                valid=bool(item.get("valid")),
                invalid_reason=str(item.get("invalid_reason") or ""),
                scope=str(item.get("scope") or ""),
            )
            for item in (ledger.get("objective_candidates") or [])
        ]
        candidates.sort(key=lambda c: c.score, reverse=True)
        valid_objectives = [c for c in candidates if c.valid]
        out["training_objective_text"] = (
            valid_objectives[0].text if valid_objectives
            else (candidates[0].text if candidates else "")
        )
        out["objective_candidates"] = [c.to_dict() for c in candidates[:8]]
        out["objective_found"] = bool(valid_objectives)
        out["objective_source_state"] = (
            "local_or_archive" if valid_objectives else "need_online")
        out["school_text_chars"] = len(report_text)
        # 为语义/关键词类指标登记证据条目：指向实际被读取的报告文本
        if report_text:
            text_sources = sorted(
                str(p.relative_to(self.settings.project_root))
                for root in ds.text_roots()
                for p in root.rglob("*.txt")
                if (plan.school is None or plan.school in str(p))
                and ("教学质量报告" in str(p) or "培养方案" in str(p) or "年度报告" in str(p))
            )[:3]
            eid = "ev:teaching:report_text"
            evidence.add(
                EvidenceItem(
                    evidence_id=eid,
                    source_type="document",
                    title=f"{plan.school or '全部样本高校'}教学质量报告正文",
                    locator="; ".join(text_sources) or "data/raw/pdf_text/**/教学质量报告",
                    quote=(out["training_objective_text"] or report_text[:200]).replace("\n", " ")[:300],
                    school=plan.school,
                    evidence_level="A",
                    confidence=0.8,
                )
            )
            ids.setdefault("teaching_text", []).append(eid)
        for field_name, fact_type in (
            ("senior_title_ratio", "senior_title_ratio"),
            ("student_faculty_ratio", "student_faculty_ratio"),
            ("practice_credit_ratio", "practice_credit_ratio"),
            ("training_base_count", "training_base_count"),
            ("total_hours", "total_hours"),
            ("required_course_ratio", "required_course_ratio"),
        ):
            # 师资/教学条件/实践学分在报告中多为校级或校级分专业口径，
            # 允许使用校级数值，但返回值会带 scope 标注。
            if plan.family:
                latest = ds.latest_facts(plan.family, plan.school, fact_type,
                                         major_preferred=plan.major, include_school_level=True)
            else:
                # 通用专业：按专业名取事实；无该专业口径时回退同校校级口径（可披露）
                latest = ds.latest_facts_by_major(plan.major, plan.school, fact_type,
                                                  include_school_level=True)
            out[field_name] = latest.get("value")
            out[f"{field_name}_meta"] = latest
            if latest.get("value") is not None:
                eid = f"ev:teaching:{fact_type}"
                evidence.add(
                    EvidenceItem(
                        evidence_id=eid,
                        source_type="document",
                        title=f"{fact_type} 原始记录",
                        locator=latest.get("source_document", ""),
                        quote="；".join(latest.get("raw") or [])[:300],
                        year=latest.get("year"),
                        school=latest.get("school"),
                        evidence_level=latest.get("evidence_level", "D"),  # type: ignore[arg-type]
                        confidence=0.5,
                    )
                )
                ids.setdefault("teaching", []).append(eid)
        return out, ids

    def _employment_context(self, plan: ResearchPlan, evidence: EvidenceStore) -> tuple[dict[str, Any], dict[str, list[str]]]:
        ds = self.dataset
        ids: dict[str, list[str]] = {}
        out: dict[str, Any] = {}
        mapping = {
            "placement_rate": "placement_rate",
            "signing_rate": "signing_rate",
            "further_study_rate": "further_study_rate",
            "employment_rate": "employment_rate",
        }
        for field_name, fact_type in mapping.items():
            if plan.family:
                latest = ds.latest_facts(plan.family, plan.school, fact_type,
                                         major_preferred=plan.major)
            else:
                latest = ds.latest_facts_by_major(plan.major, plan.school, fact_type)
            # 点名了学校但该校没有该专业族的口径数据时，回退到**本校校级口径**并标注，
            # 绝不使用其他学校的数据（那会得出张冠李戴的结论）。
            if latest.get("value") is None and plan.school:
                school_level = ds.latest_facts(plan.family, plan.school, fact_type,
                                               include_school_level=True)
                if school_level.get("value") is not None:
                    school_level = {**school_level, "fallback": "school_level_of_same_school"}
                    latest = school_level
            out[field_name] = latest.get("value")
            out[f"{field_name}_meta"] = latest
            if latest.get("value") is not None:
                eid = f"ev:employment:{fact_type}"
                evidence.add(
                    EvidenceItem(
                        evidence_id=eid,
                        source_type="document",
                        title=f"{plan.school or '全部样本高校'}{plan.major}{fact_type}",
                        locator=latest.get("source_document", ""),
                        quote="；".join(latest.get("raw") or [])[:300],
                        year=latest.get("year"),
                        school=latest.get("school"),
                        evidence_level="D",
                        confidence=0.5,
                    )
                )
                ids.setdefault("employment", []).append(eid)
        out["n_graduates"] = (ds.latest_facts(plan.family, plan.school, "graduates").get("value"))
        out["salary"] = None
        # 用人单位满意度：来自就业质量报告 PDF（A 级）。此前无数据源时恒为 null。
        # 用人单位满意度是全校性调查，允许使用校级口径（并在 detail 中标注 scope）
        if plan.family:
            satisfaction = ds.latest_facts(plan.family, plan.school, "employer_satisfaction",
                                           major_preferred=plan.major, include_school_level=True)
        else:
            satisfaction = ds.latest_facts_by_major(plan.major, plan.school,
                                                    "employer_satisfaction",
                                                    include_school_level=True)
        out["employer_rating"] = satisfaction.get("value")
        out["employer_rating_meta"] = satisfaction
        if satisfaction.get("value") is not None:
            eid = "ev:employment:employer_satisfaction"
            evidence.add(
                EvidenceItem(
                    evidence_id=eid,
                    source_type="document",
                    title=f"{satisfaction.get('school')}用人单位满意度",
                    locator=str(satisfaction.get("source_document", "")),
                    quote="；".join(satisfaction.get("raw") or [])[:300],
                    page=satisfaction.get("page"),
                    year=satisfaction.get("year"),
                    school=satisfaction.get("school"),
                    evidence_level="A",
                    confidence=0.85,
                )
            )
            ids.setdefault("employment", []).append(eid)
        out["source_rule"] = "就业结果指标仅取自就业质量报告；招聘数据不参与该维度。"
        return out, ids

    def _market_context(self, plan: ResearchPlan, demands, evidence: EvidenceStore) -> dict[str, Any]:
        ds = self.dataset
        me = ds.market_evidence
        confs = [d.confidence for d in demands if d.confidence]
        vals = [d.demand for d in demands if d.demand is not None]
        emerging = ["大模型", "RAG", "Agent", "MLOps", "模型部署", "深度学习"]
        emerging_hits = [d for d in demands if d.skill_name in emerging]
        stats = ds.job_statistics(emerging_skills=emerging)
        eid = "ev:market:har_jobs"
        if not demands:
            note = ds.demand_scope_note or "缺少可用的需求向量"
            evidence.add(
                EvidenceItem(
                    evidence_id="ev:market:scope",
                    source_type="job_market",
                    title="需求向量不可用（岗位语料与目标专业族不匹配）",
                    locator=str(stats.get("source") or "data/processed/jobs.json"),
                    quote=note[:200],
                    evidence_level="D",
                    confidence=0.3,
                )
            )
            return {
                "status": "insufficient_evidence",
                "raw_count": stats.get("raw_count"),
                "deduplicated_count": stats.get("deduplicated_count"),
                "effective_count": stats.get("effective_count"),
                "baseline_effective_count": None,
                "skill_demand_mean": None,
                "emerging_skill_share": None,
                "skill_trend_growth": None,
                "salary_premium": None,
                "bachelor_share": None,
                "target_city_share": None,
                "confidence": 0.0,
                "evidence_level": "D",
                "counts_status": "corpus_scope_mismatch",
                "note": note,
                "demand_scope_note": note,
                "corpus": ds.demand_corpus_profile(),
                "evidence_ids": ["ev:market:scope"],
                "education_distribution": stats.get("education_distribution"),
                "master_plus_share": stats.get("master_plus_share"),
                "median_salary_target": stats.get("median_salary_target"),
                "median_salary_baseline": stats.get("median_salary_baseline"),
                "salary_p25_target": stats.get("salary_p25_target"),
                "salary_p75_target": stats.get("salary_p75_target"),
                "salary_buckets": stats.get("salary_buckets"),
                "n_salary_target": stats.get("n_salary_target"),
                "n_daily_salary_excluded": stats.get("n_daily_salary_excluded"),
                "n_target_jobs": stats.get("n_target_jobs"),
                "n_baseline_jobs": stats.get("n_baseline_jobs"),
                "industries": stats.get("industries"),
            }
        if stats.get("status") == "ok":
            evidence.add(
                EvidenceItem(
                    evidence_id=eid,
                    source_type="job_market",
                    title=f"HAR 导入岗位数据（{stats['n_target_jobs']} 条 AI 关键词岗位）",
                    locator=str(stats.get("source") or "data/processed/jobs.json"),
                    quote=json.dumps({
                        "counts": stats.get("counts"),
                        "education": stats.get("education_distribution"),
                        "median_salary_target": stats.get("median_salary_target"),
                        "median_salary_baseline": stats.get("median_salary_baseline"),
                    }, ensure_ascii=False)[:400],
                    evidence_level="C",
                    confidence=0.7,
                )
            )
            market = {
                "raw_count": stats.get("raw_count"),
                "deduplicated_count": stats.get("deduplicated_count"),
                "effective_count": stats.get("effective_count"),
                # D1 需要时间基期；单期抓包无法构造，故留 null 并披露
                "baseline_effective_count": None,
                "skill_demand_mean": round(sum(vals) / len(vals), 4) if vals else None,
                "emerging_skill_share": stats.get("emerging_skill_share"),
                "skill_trend_growth": None,
                "salary_premium": stats.get("salary_premium"),
                "bachelor_share": stats.get("bachelor_share"),
                "target_city_share": stats.get("target_city_share"),
                "confidence": round(sum(confs) / len(confs), 4) if confs else 0.0,
                "evidence_level": "C",
                "counts_status": "har_import_three_tier",
                "note": (
                    f"岗位数据来自 HAR 导入（raw {stats.get('raw_count')} / 去重 "
                    f"{stats.get('deduplicated_count')} / 有效 {stats.get('effective_count')}）；"
                    f"AI 关键词岗位 {stats['n_target_jobs']} 条，同城基线 {stats['n_baseline_jobs']} 条。"
                    f"其中 {stats.get('n_salary_target') or 0} 条有月薪数值"
                    f"（另有 {stats.get('n_daily_salary_excluded') or 0} 条为日薪/兼职，"
                    "不并入月薪中位数）。"
                    "无第二个时间窗口，故岗位增长与技能趋势类指标记 null。"
                ),
                "evidence_ids": [eid],
                "education_distribution": stats.get("education_distribution"),
                "master_plus_share": stats.get("master_plus_share"),
                "median_salary_target": stats.get("median_salary_target"),
                "median_salary_baseline": stats.get("median_salary_baseline"),
                "salary_p25_target": stats.get("salary_p25_target"),
                "salary_p75_target": stats.get("salary_p75_target"),
                "salary_buckets": stats.get("salary_buckets"),
                "n_salary_target": stats.get("n_salary_target"),
                "n_daily_salary_excluded": stats.get("n_daily_salary_excluded"),
                "industries": stats.get("industries"),
                "publish_window": stats.get("publish_window"),
                "reported_total": stats.get("reported_total"),
                "n_target_jobs": stats.get("n_target_jobs"),
                "n_baseline_jobs": stats.get("n_baseline_jobs"),
                "corpus": ds.demand_corpus_profile(),
            }
            return market

        # fallback: aggregated legacy evidence only
        evidence.add(
            EvidenceItem(
                evidence_id=eid,
                source_type="job_market",
                title=str(me.get("title") or "招聘聚合证据"),
                locator=str(me.get("source_document") or ""),
                quote=str(me.get("compliance_note") or "")[:200],
                evidence_level="D",
                confidence=0.5,
            )
        )
        return {
            "raw_count": (me.get("counts") or {}).get("raw_count"),
            "deduplicated_count": (me.get("counts") or {}).get("deduplicated_count"),
            "effective_count": (me.get("counts") or {}).get("effective_count"),
            "baseline_effective_count": None,
            "skill_demand_mean": round(sum(vals) / len(vals), 4) if vals else None,
            "emerging_skill_share": (len(emerging_hits) / len(demands)) if demands else None,
            "skill_trend_growth": None,
            "salary_premium": None,
            "bachelor_share": None,
            "target_city_share": None,
            "confidence": round(sum(confs) / len(confs), 4) if confs else 0.0,
            "evidence_level": "D",
            "counts_status": "aggregate_only",
            "note": "未导入逐条岗位数据；raw/deduplicated/effective 均为 null。"
                    "请将 HAR 放入 data/raw/har/ 并运行 scripts/import_har_jobs.py。",
            "evidence_ids": [eid],
        }

    def _resolve_skill_names(self, course_name: str, description: str) -> list[str]:
        # 396 个技能实体的本体匹配是热点：按（课程名, 描述）缓存，避免同一门课
        # 在一次分析中被反复匹配（课程表出现多轮时尤其明显）。
        key = (course_name, description)
        cached = self._skill_name_cache.get(key)
        if cached is not None:
            return cached
        # 课程描述里带着"…培养方案 · 章节：… · 学分 3.0"这类样板文字，
        # 不清洗会让每门课都命中专业名/学分，供给向量被假信号灌满。
        from .skills_mining import clean_course_text

        clean = clean_course_text(
            course_name, description,
            extra_noise=(getattr(self, "_active_major", "") or "",
                         getattr(self, "_active_school", "") or ""))
        # 所有专业同一条路，两个来源合并、地位平等：
        # ① 该专业的数据驱动词表（岗位∪课程∪种子∪人工）在清洗文本上匹配；
        # ② 精选的"课程→技能"教学映射（本体自带，谁有谁用，非 AI 专业通常为空）。
        # 注意：映射必须作用在**清洗后**的文本上，否则"机械工程"里的"工程"会被
        # 误命中成"工程化"。
        vocabulary = self.dataset.major_vocabulary
        names: list[str] = [term for term in vocabulary if term in clean] if vocabulary else []
        if self.ontology:
            for sid in self.ontology.match_course(course_name, clean):
                skill = self.ontology.get(sid)
                if skill:
                    names.append(skill.name)
        result = sorted(set(names))
        self._skill_name_cache[key] = result
        return result

    def _matching_context(
        self, plan: ResearchPlan, supply_bundle: dict[str, Any], demand_vector: dict[str, Any],
        evidence: EvidenceStore,
    ) -> dict[str, Any]:
        """Core mainline: Supply Vector(s) + Demand Vector -> Fit -> Gap.

        The target institution and the regional peer pool are kept strictly
        apart: the target scope never borrows the peer's courses, and a skill
        that the target does not teach is reported as an observed 0 (with
        ``supply_basis='absent_in_scope'``), not silently replaced by the
        benchmark.
        """
        demand_map = demand_mod.demand_score_map(demand_vector)
        demand_meta = demand_mod.demand_meta_map(demand_vector)

        def scope_bundle(scope: str) -> dict[str, Any]:
            info = supply_bundle.get(scope) or {}
            vector = info.get("vector")
            if vector is None or not demand_map:
                return {
                    "status": "insufficient_evidence",
                    "fit": None,
                    "fit_100": None,
                    "supply_provenance": scope,
                    "supply_reliability": "none",
                    "per_skill": [],
                    "skill_gap_index": None,
                    "rows": [],
                    "coverage": 0.0,
                    "confidence": 0.0,
                    "reason": "缺少该口径的课程供给或需求向量",
                }
            fit = fit_mod.skill_fit(
                vector.score, demand_map, demand_meta=demand_meta,
                supply_provenance=scope, supply_status=vector.status,
                supply_reliability=vector.reliability, supply_reason=vector.reason,
                unlisted_supply_is_zero=True,
            )
            gaps = gap_mod.compute_skill_gaps(
                demand_map, vector.score, demand_meta=demand_meta,
                unlisted_supply_is_zero=True,
            )
            breadth = matching_mod.breadth_metrics(vector.score, demand_map)
            return {**fit, **breadth, "gaps": gaps,
                    "gap_index": gaps.get("skill_gap_index"),
                    "n_courses": info.get("n_courses"),
                    "scope": info.get("scope"),
                    "partial_supply": bool(info.get("partial")),
                    "scope_reason": info.get("reason", "")}

        target = scope_bundle("target")
        peer = scope_bundle("peer")
        used = supply_bundle.get("used", "peer")
        primary = target if used == "target" else peer

        match = {
            "matching_score": primary.get("fit"),
            "matching_score_100": primary.get("fit_100"),
            "n_skills_compared": primary.get("n_skills_compared", 0),
            "confidence": primary.get("confidence", 0.0),
            "per_skill": primary.get("per_skill", []),
            "recall": primary.get("recall"),
            "precision": primary.get("precision"),
            "jaccard": primary.get("jaccard"),
            "matched_skills": primary.get("matched_skills", []),
            "unmet_demand_skills": primary.get("unmet_demand_skills", []),
            "demand_meta": demand_meta,
            "scope": used,
            "is_target_scope": used == "target",
            "fit_closure": fit_mod.fit_gap_closure(primary),
            "demand_used": demand_map,
        }
        gaps = primary.get("gaps") or {"rows": [], "skill_gap_index": None, "n_skills": 0,
                                       "n_comparable": 0, "coverage": 0.0}
        eid = "ev:calc:matching"
        evidence.add(
            EvidenceItem(
                evidence_id=eid,
                source_type="calculation",
                title=f"Skill Fit（口径：{'目标高校' if used == 'target' else '北京同类专业基准'}）",
                locator="analysis/fit.py::skill_fit",
                quote=(f"fit={match['matching_score']}, n_skills={match['n_skills_compared']}, "
                       f"gap_index={gaps.get('skill_gap_index')}, scope={used}"),
                evidence_level="C",
                confidence=float(match.get("confidence") or 0.5),
            )
        )
        return {
            "matching": match,
            "gaps": gaps,
            "gaps_target": target.get("gaps"),
            "gaps_peer": peer.get("gaps"),
            "fit": {"target": target, "peer": peer, "primary": primary, "used": used},
            "demand_map": demand_map,
            "demand_meta": demand_meta,
            "evidence_ids": [eid],
        }

    def _occupation_context(
        self, plan: ResearchPlan, supply_bundle: dict[str, Any],
        primary_supply_scope: str, evidence: EvidenceStore,
    ) -> dict[str, Any]:
        """院校专业 × 目标岗位 的匹配分析（目标岗位只取该岗位族的岗位）。"""
        ds = self.dataset
        if not plan.target_occupation:
            return {
                "status": "not_requested",
                "occupation": None,
                "reason": "本次问题未指定目标岗位；给出目标岗位（如“大模型算法工程师”）即可输出岗位匹配度",
                "catalogue": occupation_mod.catalogue(),
                "match": None,
            }
        # 传入专业：岗位名直搜时能同时用上「通用语料 + 该专业的专业作用域语料」，
        # 而不是只看通用表（后者会漏掉按专业导出的那 25 万行）。
        demands, info = ds.occupation_demand(plan.target_occupation, major=plan.major)
        occupation_meta = {
            "requested": plan.target_occupation,
            "id": info.get("occupation_id"),
            "name": info.get("occupation_name"),
            "keywords": info.get("keywords"),
            "typical_skills": info.get("typical_skills"),
            "match_scope": info.get("match_scope"),
        }
        if not demands:
            return {
                "status": "insufficient_evidence",
                "demand_status": "insufficient_evidence",
                "occupation": occupation_meta,
                "n_jobs": info.get("n_jobs"),
               "reason": info.get("demand_note") or info.get("reason") or "目标岗位样本不足",
                "catalogue": occupation_mod.catalogue(),
                "match": None,
            }
        demand_vector = demand_mod.build_demand_vector(demands)
        evidence.add(
            EvidenceItem(
                evidence_id="ev:occupation:demand",
                source_type="job_market",
                title=f"目标岗位「{occupation_meta['name']}」需求向量（{info.get('n_jobs')} 条岗位）",
                locator=str(ds.jobs_meta.get("sources") or "data/processed/jobs.json"),
                quote=json.dumps(
                    {"occupation": occupation_meta["name"], "n_jobs": info.get("n_jobs"),
                     "match_scope": info.get("match_scope"),
                     "top_skills": [r["skill"] for r in demand_vector.get("top_skills", [])[:6]]},
                    ensure_ascii=False)[:400],
                evidence_level="C",
                confidence=0.7,
            )
        )
        # 供给口径与 Primary TSI 保持一致：点名高校→该校；未点名→区域课程池
        scope_key = "target" if primary_supply_scope == "target_school" else "peer"
        matrix = supply_bundle[scope_key].get("matrix") if primary_supply_scope != "none" else None
        fit_scope = matching_scope = None
        supply_score: dict[str, float] = {}
        supply_status = "insufficient_evidence"
        if matrix is not None:
            supply_score = matrix.supply
            supply_status = matrix.supply_status
            fit_scope = matrix.provenance
            matching_scope = matrix.reliability
        match = occupation_match_mod.match_occupation(
            supply_score,
            demand_mod.demand_score_map(demand_vector),
            demand_meta=demand_mod.demand_meta_map(demand_vector),
            supply_status=supply_status,
            supply_reliability=matching_scope or "none",
            supply_reason=(
                "" if matrix is not None else
                (supply_bundle["target"].get("reason") or "缺少研究对象自身的可核查课程")
            ),
            supply_provenance=fit_scope or "none",
            occupation=occupation_meta,
            extra_demand=info.get("typical_skills"),
        )
        # 对照口径：北京同类专业课程池与该目标岗位的匹配度（明确标注为基准，不代表该校）
        benchmark_match = None
        benchmark_matrix = supply_bundle["peer"].get("matrix") if plan.school else None
        if benchmark_matrix is not None and primary_supply_scope != "region_pool":
            benchmark_match = occupation_match_mod.match_occupation(
                benchmark_matrix.supply,
                demand_mod.demand_score_map(demand_vector),
                demand_meta=demand_mod.demand_meta_map(demand_vector),
                supply_status=benchmark_matrix.supply_status,
                supply_reliability=benchmark_matrix.reliability,
                supply_reason=benchmark_matrix.reason,
                supply_provenance="peer_benchmark",
                occupation=occupation_meta,
                extra_demand=info.get("typical_skills"),
            )
        return {
            "status": match.get("status"),
            "demand_status": "ok",
            "occupation": occupation_meta,
            "n_jobs": info.get("n_jobs"),
            "match_scope": info.get("match_scope"),
            "n_demand_skills": demand_vector.get("n_skills"),
            "demand_top": demand_vector.get("top_skills", [])[:10],
            "demand_method_note": demand_vector.get("method_note"),
            "requirements": {
                **(info.get("requirements") or {}),
            },
            "supply_scope": {
                "used_for_primary": primary_supply_scope,
                "n_courses": supply_bundle[scope_key].get("n_courses") if primary_supply_scope != "none" else 0,
                "reliability": matching_scope,
            },
            "match": match,
            "benchmark_match": benchmark_match,
            "reason": match.get("reason") or "",
            "evidence_ids": ["ev:occupation:demand"],
            "catalogue": occupation_mod.catalogue(),
        }

    def _policy_context(self, plan: ResearchPlan, evidence: EvidenceStore) -> tuple[dict[str, Any], dict[str, list[str]]]:
        ds = self.dataset
        related = [p for p in ds.policies if plan.major in p.title or plan.major in (p.key_terms or [])]
        if not related:
            related = [p for p in ds.policies if any(k in (p.industry_direction or []) for k in ("人工智能", "数字经济"))]
        ids: dict[str, list[str]] = {}
        for p in related[:5]:
            eid = f"ev:policy:{p.policy_id}"
            evidence.add(
                EvidenceItem(
                    evidence_id=eid,
                    source_type="policy",
                    title=p.title,
                    locator=f"data/source/政策文件/{p.relative_path}",
                    quote=(p.evidence_quote or p.policy_goal)[:300],
                    year=p.year,
                    evidence_level="A" if p.text_status == "ok" else "E",
                    confidence=0.9 if p.text_status == "ok" else 0.0,
                )
            )
            ids.setdefault("policy", []).append(eid)
        industries: dict[str, int] = {}
        for p in ds.policies:
            for i in p.industry_direction or []:
                industries[i] = industries.get(i, 0) + 1
        return {
            "n_documents": len(ds.policies),
            "n_matched_documents": len(related),
            "industry_direction": sorted(industries, key=lambda k: -industries[k])[:8],
            "industry_counts": industries,
            "skills_related": sorted({s for p in ds.policies for s in (p.skills_related or [])}),
            "text_status_counts": _count_by(p.text_status for p in ds.policies),
            "duplicates_removed": ds.policy_duplicates,
        }, ids

    def _semantic_context(
        self, plan: ResearchPlan, courses: list[dict[str, Any]], demands, teaching: dict, policy: dict
    ) -> dict[str, Any]:
        ds = self.dataset
        objective_text = teaching.get("training_objective_text") or ""
        job_text = " ".join(d.skill_name for d in demands)
        course_text = " ".join(f"{c['name']} {c.get('description','')}" for c in courses)
        industry_text = " ".join(policy.get("industry_direction") or [])
        demand_map = {
            d.skill_name: float(getattr(d, "demand", 0.0) or 0.0)
            for d in demands if getattr(d, "skill_name", None)
        }
        # 向量余弦打分（纯 Python，可复现）；LLM 不参与任何数值
        scorer = get_scorer(str(self.settings.raw.get("semantic", {}).get("provider", "tfidf")))
        background = [ds.school_text(plan.school)[:4000], industry_text]
        objective_lexical = scorer.score(objective_text, job_text, background=background).to_dict()
        objective_result = objective_alignment_mod.objective_job_alignment(
            teaching.get("objective_candidates") or ([objective_text] if objective_text else []),
            demand_map,
            resolve_skills=self._resolve_skill_names,
            lexical_score=objective_lexical,
        )
        return {
            "objective_job_alignment": objective_result,
            "major_industry_alignment": scorer.score(f"{plan.major} {job_text}", industry_text,
                                                     background=background).to_dict(),
            "curriculum_market_alignment": scorer.score(course_text, job_text,
                                                        background=background).to_dict(),
            "providers": provider_status(),
            "scorer": scorer.provider,
            **self._semantic_signals(plan, teaching),
        }

    def _semantic_signals(self, plan: ResearchPlan, teaching: dict) -> dict[str, Any]:
        """Anchor-based semantic evidence for the qualitative indicators."""
        try:
            scorer = _embedding_scorer_singleton()
        except Exception as exc:  # noqa: BLE001 - 缺模型时退回关键词规则
            return {"semantic_signals": {}, "semantic_provider": f"unavailable:{type(exc).__name__}"}
        if scorer is None:
            return {"semantic_signals": {}, "semantic_provider": "unavailable"}
        text = teaching.get("school_text") or self.dataset.school_text(plan.school)
        # 同一份报告反复打分（评测会跑很多轮）时命中缓存，避免重复向量化
        cache_dir = self.settings.processed_dir / "semantic_cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha1(
            (getattr(scorer, "model_name", "") + text).encode("utf-8")).hexdigest()[:16]
        cache_file = cache_dir / f"{digest}.json"
        if cache_file.exists():
            try:
                cached = json.loads(cache_file.read_text(encoding="utf-8"))
                return {"semantic_signals": cached["signals"],
                        "semantic_provider": cached["provider"],
                        "semantic_model": cached.get("model", ""), "cache": "hit"}
            except (json.JSONDecodeError, KeyError):
                pass
        results = scorer.score(text)
        payload = {k: v.to_dict() for k, v in results.items()}
        cache_file.write_text(
            json.dumps({"signals": payload, "provider": scorer.provider,
                        "model": getattr(scorer, "model_name", "")}, ensure_ascii=False),
            encoding="utf-8")
        return {
            "semantic_signals": payload,
            "semantic_provider": scorer.provider,
            "semantic_model": getattr(scorer, "model_name", ""),
            "cache": "miss",
        }

    # ---------- run ----------
    def run(
        self,
        query: str,
        *,
        include_template: bool = False,
        persist: bool = False,
        simulation: bool = False,
        target_occupation: str | None = None,
        source_mode: str | None = None,
        harvest: bool = False,
        harvest_domain: str | None = None,
        harvest_kinds: list[str] | None = None,
        harvest_pages: list[dict[str, str]] | None = None,
        harvest_timeout_s: int | None = None,
        peers: str | list[str] | None = None,
        peer_max: int = 3,
        peer_harvest_kinds: list[str] | None = None,
    ) -> dict[str, Any]:
        self.tool_calls = []
        started = datetime.now(timezone.utc)
        evidence = EvidenceStore()
        ds = self.dataset

        plan = self._call_tool(
            "plan_research_task", {"query": query, "occupation": target_occupation},
            lambda: build_plan(query, ds, occupation=target_occupation),
        )
        if plan.mode == "X_unknown_major":
            return self._unavailable_major_result(query, plan, started)
        self._active_major = plan.major or ""
        self._active_school = plan.school or ""
        source_report = self._call_tool(
            "prepare_supply_source",
            {"mode": source_mode, "school": plan.school, "harvest": harvest},
            lambda: self._prepare_source(
                plan, source_mode=source_mode, harvest=harvest, harvest_domain=harvest_domain,
                harvest_kinds=harvest_kinds, harvest_pages=harvest_pages,
                harvest_timeout_s=harvest_timeout_s, peers=peers, peer_max=peer_max,
                peer_harvest_kinds=peer_harvest_kinds,
            ),
        )
        # ---- 技能空间必须在算供给之前定好 ----
        # 所有专业走同一条路：词表由数据构建（岗位术语 ∪ 课程候选 ∪ 本体种子），
        # 供需两侧使用同一套词表与同一抽取函数。没有"本体专业/通用专业"的分级。
        # 词表是"本次分析"的属性，不是 Dataset 的持久属性：记下旧值，结束前还原，
        # 否则同一个 Dataset 被多次分析时会互相污染（A 专业的词表泄漏到 B 专业）。
        _prev_vocab = (ds.vocabulary_mode, ds.major_vocabulary)
        preview = self._preview_courses(plan, include_template)
        ds.vocabulary_mode = "data_driven"
        ds.major_vocabulary, self._vocabulary_stats = self._build_skill_vocabulary(
            plan, preview, ds)
        self._course_derived_mode = True
        # 课程→技能缓存依赖当前词表，换专业必须清空，否则会拿到上一个专业的映射
        self._skill_name_cache.clear()
        teaching, teaching_ids = self._call_tool("query_teaching_metrics", {"school": plan.school},
                                                 lambda: self._teaching_context(plan, evidence))
        # 培养目标通道也使用同一套词表（不再单独走本体）
        skill_names = sorted(ds.major_vocabulary) or [s.name for s in self.ontology.all_skills()]
        objective_skills = supply_mod.objective_skill_hits(
            teaching.get("training_objective_text") or "", skill_names)
        supply_bundle = self._call_tool(
            "query_curriculum",
            {"school": plan.school, "include_template": include_template},
            lambda: self._supply_context(plan, include_template, objective_skills),
        )
        courses = supply_bundle["courses"]
        course_scope = supply_bundle["course_scope"]
        # 需求侧：通用专业用"课程派生词表"抽取技能，三族专业用本体
        demands = self._call_tool(
            "query_skill_frequency",
            {"source": "job_postings", "family": plan.family or None, "major": plan.major},
            lambda: ds.demand_vector(family=plan.family or None, major=plan.major),
        )
        demand_vector = demand_mod.build_demand_vector(demands)
        employment, employment_ids = self._call_tool("query_employment", {"school": plan.school},
                                                     lambda: self._employment_context(plan, evidence))
        market = self._call_tool("query_job_statistics", {"city": "北京"},
                                 lambda: self._market_context(plan, demands, evidence))
        policy, policy_ids = self._call_tool("search_policy", {"major": plan.major},
                                             lambda: self._policy_context(plan, evidence))
        literature = self._call_tool("search_literature", {"keyword": ""},
                                     lambda: self._literature_context(evidence))
        matching_bundle = self._call_tool(
            "calculate_matching", {"n_courses": len(courses), "scope": supply_bundle["used"]},
            lambda: self._matching_context(plan, supply_bundle, demand_vector, evidence),
        )
        gaps = matching_bundle["gaps"]
        gaps["reported_gap_crosscheck"] = self._crosscheck_reported_gaps(gaps, demands)
        semantic = self._semantic_context(plan, courses, demands, teaching, policy)
        matrix = (supply_bundle["target"] if supply_bundle["used"] == "target"
                  else supply_bundle["peer"])["matrix"]
        conflict_result = self._resolve_evidence_conflicts(
            plan, courses, supply_bundle, matching_bundle)

        benchmark_values = {
            "placement_rate": ds.benchmark(plan.family, "placement_rate").get("value"),
            "signing_rate": ds.benchmark(plan.family, "signing_rate").get("value"),
            "further_study_rate": ds.benchmark(plan.family, "further_study_rate").get("value"),
            "practice_credit_ratio": ds.benchmark(plan.family, "practice_credit_ratio").get("value"),
            "senior_title_ratio": ds.benchmark(plan.family, "senior_title_ratio").get("value"),
            "student_faculty_ratio": ds.benchmark(plan.family, "student_faculty_ratio").get("value"),
            "employer_rating": ds.benchmark("school", "employer_satisfaction").get("value"),
        }
        # 专业族样本太少时（n<3），基准改用校级口径并在 benchmark_detail 中标注来源
        for key, fact_type in (("placement_rate", "placement_rate"), ("signing_rate", "signing_rate"),
                               ("further_study_rate", "further_study_rate"),
                               ("practice_credit_ratio", "practice_credit_ratio"),
                               ("senior_title_ratio", "senior_title_ratio"),
                               ("student_faculty_ratio", "student_faculty_ratio")):
            family_stat = ds.benchmark(plan.family, fact_type)
            if (family_stat.get("n") or 0) < 3:
                school_stat = ds.benchmark("school", fact_type)
                if (school_stat.get("n") or 0) >= 3:
                    benchmark_values[key] = school_stat["value"]
        benchmark_values = {k: v for k, v in benchmark_values.items() if v is not None}
        benchmark_detail = {
            k: ds.benchmark(plan.family, k) for k in
            ("placement_rate", "signing_rate", "practice_credit_ratio", "senior_title_ratio", "student_faculty_ratio")
        }

        context = {
            "teaching": teaching,
            "retrieval_ledger": teaching.get("retrieval_ledger"),
            "employment": employment,
            "matching": matching_bundle["matching"],
            "gaps": gaps,
            "market": market,
            "policy": policy,
            "literature": literature,
            "semantic": semantic,
            "evidence_ids": {
                **teaching_ids,
                **employment_ids,
                "policy": policy_ids.get("policy", []),
                "jobs": [market["evidence_ids"][0]] if market.get("evidence_ids") else [],
                "courses": [],
            },
        }
        metrics = self._call_tool(
            "calculate_tsi", {"n_indicators": len(tsi_mod.SPECS)},
            lambda: tsi_mod.score_indicators(context, benchmark_values),
        )
        tsi_result = tsi_mod.compute_tsi(metrics)
        # ---- Primary TSI（正式主指标）：供需适配维只用"研究对象本身"的供给 ----
        # 点名高校 → 研究对象是该校：只能用该校证据，证据不足就该维记 null。
        # 未点名高校 → 研究对象就是北京同类专业课程池（区域口径），它是主体而非替代品。
        target_fit = matching_bundle["fit"]["target"]
        school_level = bool(plan.school)
        if school_level:
            primary_supply_scope = "target_school" if supply_bundle["used"] == "target" else "none"
            primary_fit = target_fit if primary_supply_scope == "target_school" else target_fit
            primary_gaps = (matching_bundle.get("gaps_target")
                            if primary_supply_scope == "target_school" else {})
            primary_matrix = (supply_bundle["target"].get("matrix")
                              if primary_supply_scope == "target_school" else None)
        else:
            primary_supply_scope = "region_pool"
            primary_fit = matching_bundle["fit"]["peer"]
            primary_gaps = matching_bundle.get("gaps_peer") or {}
            primary_matrix = supply_bundle["peer"].get("matrix")
        primary_context = {
            **context,
            "fit": primary_fit,
            "gaps": primary_gaps,
            "supply_channels": (primary_matrix.supply_channels if primary_matrix else {}),
        }
        primary_metrics = self._call_tool(
            "calculate_primary_tsi", {"n_indicators": len(primary_mod.SPECS)},
            lambda: primary_mod.score_indicators(primary_context, benchmark_values,
                                                 legacy_metrics=metrics),
        )
        primary_result = primary_mod.compute(primary_metrics)
        primary_result["supply_scope"] = {
            "used_for_legacy_fit": supply_bundle["used"],
            "used_for_primary": primary_supply_scope,
            "target_status": target_fit.get("status"),
            "target_reliability": target_fit.get("supply_reliability"),
            "target_n_courses": supply_bundle["target"].get("n_courses"),
            "peer_n_courses": supply_bundle["peer"].get("n_courses"),
            "provisional": bool(primary_supply_scope != "none" and primary_fit.get("partial_supply")),
            "provisional_note": (
                "目标高校课程证据少于门槛，供需适配维按'可核查证据的保守下界'计算，"
                "不代表完整培养体系；同类基准与市场需求另列对照。"
                if primary_supply_scope != "none" and primary_fit.get("partial_supply") else ""
            ),
            "scope_note": (
                "未指定高校：研究对象即北京同类专业课程池（区域口径），该流向为主体口径。"
                if primary_supply_scope == "region_pool" else
                "点名高校且该校有可核查课程：供需适配维只用该校真实供给。"
                if primary_supply_scope == "target_school" else
                "点名高校但该校无可核查课程：供需适配维记 null 并整维剔除，不使用同类基准替代。"
            ),
            "note": (
                "Primary TSI 的供需适配维只采用研究对象自身的供给：点名高校时=该校证据"
                "（不足则整维剔除，不使用同类基准替代）；未点名高校时=北京同类专业课程池"
                "（区域口径即研究对象）。同类基准另用于 Benchmark 与三角比较。"
            ),
        }
        # Core TSI Engine V1（27 指标 A/B/C）：与 V2 并行输出，便于对照与版本切换
        text = self.dataset.school_text(plan.school)
        signals = tsi_v1_mod.detect_signals(text)
        v1_context = {**context, "evidence": {"text_signals": signals}}
        # 指标 → 精确证据ID：每条证据ID都是确定性的（ev:<侧>:<指标>），
        # 这里只保留真实存在的那些，保证"分数 → 证据"一一对应。
        existing_evidence = {item.evidence_id for item in evidence.all()}

        def pick(*candidate_ids: str) -> list[str]:
            return [i for i in candidate_ids if i in existing_evidence]

        policy_ids = sorted(i for i in existing_evidence if i.startswith("ev:policy:"))

        v1_result = tsi_v1_mod.compute_v1(v1_context, benchmark_values, {
            "text_signals": signals,
            "evidence_map": {
                "employment.placement_rate": pick("ev:employment:placement_rate"),
                "employment.signing_rate": pick("ev:employment:signing_rate"),
                "employment.employer_rating": pick("ev:employment:employer_satisfaction"),
                "teaching.senior_title_ratio": pick("ev:teaching:senior_title_ratio"),
                "teaching.student_faculty_ratio": pick("ev:teaching:student_faculty_ratio"),
                "teaching.practice_credit_ratio": pick("ev:teaching:practice_credit_ratio"),
                "teaching.training_base_count": pick("ev:teaching:training_base_count"),
                "matching": pick("ev:calc:matching"),
                "market": pick("ev:market:har_jobs"),
                "policy": policy_ids[:5],
                # 语义与关键词类指标统一指向被读取的报告正文
                "text.report": pick("ev:teaching:report_text"),
            },
        })
        v1_result["signals"] = signals
        v1_result["signal_source_chars"] = len(text)

        primary_result["versions"] = primary_mod.version_registry(
            primary_result, v1_result, tsi_result
        )

        occupation_bundle = self._call_tool(
            "query_occupation_match",
            {"occupation": plan.target_occupation},
            lambda: self._occupation_context(plan, supply_bundle, primary_supply_scope, evidence),
        )
        if occupation_bundle.get("match"):
            metrics.append(occupation_match_mod.to_metric(occupation_bundle["match"]))

        trends = self._trend_context(plan, courses)
        bench = self._benchmark_context(plan, supply_bundle, matching_bundle, market)
        mechanism = self._mechanism_context(plan, policy, demand_vector, supply_bundle,
                                            matching_bundle)
        sim_result = None
        if simulation or include_template or plan.mode in {"G_curriculum_simulation", "H_full_report"}:
            sim_result = self._call_tool(
                "simulate_curriculum_change",
                {"add": ["大模型应用开发", "MLOps 与模型部署实践"]},
                lambda: self._simulation_context(plan, courses, matching_bundle, context,
                                                 supply_bundle, benchmark_values),
            )

        v1_compare = None
        if ds.legacy and ds.legacy.replay:
            stated = {"stated_final_tsi": ds.legacy.stated_final_tsi, **ds.legacy.replay}
            v1_compare = tsi_mod.compare_with_v1(tsi_result, stated)
            v1_compare["missing_as_zero"] = {
                "n_zero": ds.legacy.replay["n_zero_scores"],
                "n_indicators": ds.legacy.replay["n_indicators"],
                "zero_indicators": ds.legacy.replay["zero_indicators"],
            }

        run_id = "run:" + hashlib.sha1(
            f"{query}|{plan.mode}|{plan.major}|{plan.school}|{started.isoformat()}".encode()
        ).hexdigest()[:12]
        result = {
            "run_id": run_id,
            "query": query,
            "mode": plan.mode,
            "plan": plan.to_dict(),
            "dataset_summary": ds.summary(),
            "data_source": source_report,
            "teaching": teaching,
            "retrieval_ledger": teaching.get("retrieval_ledger"),
            "employment": employment,
            "market": market,
            "policy": policy,
            "literature": literature,
            "semantic": semantic,
            "matching": matching_bundle["matching"],
            "course_skill_matrix": matrix.to_dict() if matrix else {},
            "courses": courses,
            "course_scope": course_scope,
            "skill_gaps": gaps,
            "skill_gaps_target": matching_bundle.get("gaps_target"),
            "skill_gaps_peer": matching_bundle.get("gaps_peer"),
            "skill_fit": {
                "target": matching_bundle["fit"]["target"],
                "peer": matching_bundle["fit"]["peer"],
                "primary": primary_fit,
                "used_for_primary": primary_supply_scope,
                "used_for_legacy_fit": supply_bundle["used"],
                "note": ("target 为目标高校真实供给口径；peer 为北京同类专业（区域）口径；"
                         "点名高校时两者不互相替代，未点名高校时区域口径即研究对象。"),
            },
            "supply": {
                "target": (supply_bundle["target"]["vector"].to_dict()
                           if supply_bundle["target"].get("vector") else None),
                "peer": (supply_bundle["peer"]["vector"].to_dict()
                         if supply_bundle["peer"].get("vector") else None),
                # 按院校拆分区域池：宏观层必须能说清"这份区域池由哪些学校组成"
                "peer_by_school": supply_bundle["peer"].get("by_school") or [],
                "peer_n_schools": supply_bundle["peer"].get("n_schools"),
                "target_by_school": supply_bundle["target"].get("by_school") or [],
                "used_for_legacy_fit": supply_bundle["used"],
                "target_scope": supply_bundle["target"].get("scope"),
                "reason": supply_bundle["target"].get("reason", ""),
            },
            "supply_channels": (
                matrix.supply_channels if matrix else {}
            ),
            "demand_vector": demand_vector,
            "demand_rows": [d.to_dict() for d in demands],
            "demand_scope": {
                "note": ds.demand_scope_note,
                "corpus": ds.demand_corpus_profile(),
                # 需求侧到底用了哪套口径（岗位族 / 专业导出语料 / 全量兜底），
                # 报告标题与"数据不足"提示都据此措辞，避免说反话。
                "coverage": dict(getattr(ds, "demand_coverage", {}) or {}),
            },
            "vocabulary": {
                "mode": ds.vocabulary_mode,
                "n_terms": len(ds.major_vocabulary),
                **self._vocabulary_stats,
            },
            "occupation": occupation_bundle,
            "occupation_match": occupation_bundle.get("match"),
            "metrics": [m.to_dict() for m in metrics],
            "primary_tsi": primary_result,
            "tsi_v2": tsi_result,
            "tsi_v1": v1_result,
            "metric_graph": {
                "primary": primary_result.get("dependency_graph"),
                "v2_audit": metric_graph_mod.v2_graph(
                    tsi_mod.SPECS, {k: v["weight"] for k, v in tsi_mod.DIMENSIONS.items()}
                ).double_counting_report(),
            },
            "benchmark": bench,
            "benchmark_medians": benchmark_values,
            "benchmark_detail": benchmark_detail,
            "trends": trends,
            "mechanism": mechanism,
            "simulation": sim_result,
            "legacy_comparison": v1_compare,
            "conflict_resolution": conflict_result,
            "evidence": evidence.to_dicts(),
            "tool_calls": list(self.tool_calls),
            "skill_calls": [{"skill": s["skill"], "action": s["action"]} for s in plan.steps],
            "started_at": started.isoformat(),
            "finished_at": datetime.now(timezone.utc).isoformat(),
        }
        result["data_quality"] = self._data_quality(
            plan=plan, supply_bundle=supply_bundle, matching_bundle=matching_bundle,
            demand_vector=demand_vector, employment=employment, trends=trends,
            occupation_bundle=occupation_bundle,
            primary_result=primary_result, tsi_result=tsi_result,
        )
        result["retrieval"] = self._retrieval_context(
            plan=plan, courses=courses, demand_vector=demand_vector,
            occupation_bundle=occupation_bundle, literature=literature, policy=policy,
            source_report=source_report,
        )
        result["coverage"] = self._coverage_context(plan, courses)
        if persist:
            self._persist(result)
        ds.vocabulary_mode, ds.major_vocabulary = _prev_vocab
        return result

    # ---------- secondary analyses ----------
    def _unavailable_major_result(self, query: str, plan: ResearchPlan, started) -> dict[str, Any]:
        """Honest answer when the requested major has no data in the archive.

        No numbers are produced: the previous behaviour silently analysed the AI
        family instead, which is exactly the kind of unverifiable answer this
        project is built to prevent.
        """
        coverage = self.dataset.major_coverage(None)
        run_id = "run:" + hashlib.sha1(f"{query}|unavailable|{started.isoformat()}".encode()).hexdigest()[:12]
        return {
            "run_id": run_id,
            "query": query,
            "mode": "X_unknown_major",
            "status": "insufficient_evidence",
            "plan": plan.to_dict(),
            "message": f"归档与本地数据中没有「{plan.major}」专业的可用数据，因此不给出适配度结论。",
            "reason": "该项目前只有 ai / cs / econ 三个专业族的结构化数据；其余结果会退化成对错误的专业作答。",
            "major_coverage": coverage,
            "what_is_available_instead": {
                "known_families": coverage["known_families"],
                "school_level_facts": coverage["school_level_facts_available"],
                "note": "校级口径的就业率/满意度可用于全校基线，但不能代表某个专业的专业口径指标。",
            },
            "how_to_enable": [
                coverage["how_to_add"],
                "若有该专业的就业质量/教学质量报告 PDF，放入归档目录后运行 "
                "python scripts/extract_archive_pdfs.py --school <学校>，会得到 A 级事实。",
                "若有招聘数据，按关键词导出 HAR 放入 data/raw/har/，运行 python scripts/import_har_jobs.py。",
                "随后重新运行 python scripts/run_full_analysis.py。",
            ],
            "dataset_summary": self.dataset.summary(),
            "tool_calls": list(self.tool_calls),
            "started_at": started.isoformat(),
            "finished_at": datetime.now(timezone.utc).isoformat(),
        }

    def _supply_context(
        self, plan: ResearchPlan, include_template: bool, objective_skills: list[str],
    ) -> dict[str, Any]:
        """Build the Target supply vector and the Peer Benchmark supply vector.

        Target = only what the selected institution's own evidence shows.
        Peer    = 北京同类专业课程池（含 E 级模板课程，模板不属于任何目标高校）。

        The two are never merged. When the target has too little evidence the
        target vector is published as ``insufficient_evidence`` and the report
        falls back to a *disclosed* benchmark scope instead of a silent
        substitution.
        """
        ds = self.dataset
        core_cfg = (self.settings.raw.get("core_model") or {}) if isinstance(self.settings.raw, dict) else {}
        min_courses = int(core_cfg.get("min_target_courses", 3))
        reference_credits = float(core_cfg.get("reference_credits", 6.0))

        # 通用专业（family 为空）：按专业名作用域；三族专业：族 + 专业双重作用域
        family = plan.family or None
        if family:
            all_courses = ds.course_set(include_template=include_template, family=family)
        else:
            all_courses = ds.course_set(include_template=include_template, major=plan.major)
            if not all_courses:
                all_courses = ds.course_set(include_template=include_template)
        # 目标校供给只取"该专业自己的培养方案"（major 过滤），
        # 避免把同校其他专业（如智能制造工程）的课程算成人工智能专业的供给。
        target_courses: list[dict[str, Any]] = (
            ds.course_set(school=plan.school, family=family, major=plan.major,
                          include_template=include_template)
            if plan.school else []
        )
        peer_courses: list[dict[str, Any]] = []
        for course in all_courses:
            school = str(course.get("school") or "")
            if course.get("template"):
                peer_courses.append(course)          # E 级模板：只进基准池
            elif plan.school and school == plan.school:
                continue                              # 目标校课程由上面的 major 过滤决定
            else:
                peer_courses.append(course)
        # 通用专业：基准池优先"同一专业、其他院校"，这是同类专业基准的正确口径
        if not family:
            same_major = [c for c in ds.course_set(major=plan.major, include_template=False)
                          if str(c.get("school") or "") != (plan.school or "")]
            if same_major:
                peer_courses = same_major + [c for c in peer_courses if c.get("template")]
        # 学校未识别（"未识别"）的课程无法归属到某所高校，只能进基准池
        if not plan.school:
            target_courses = []

        def vector_for(courses: list[dict[str, Any]], provenance: str):
            if not courses:
                return None
            return supply_mod.build_supply_vector(
                courses, self._resolve_skill_names, provenance=provenance,
                reference_credits=reference_credits, objective_skills=objective_skills,
                min_courses=min_courses,
            )

        target_vector = vector_for(target_courses, "target")
        peer_vector = vector_for(peer_courses, "peer")
        target_ok = bool(target_vector and target_vector.status == "ok")
        used = "target" if target_ok else "peer"

        def scope_info(courses, vector, scope: str, reason: str = "") -> dict[str, Any]:
            matrix = None
            if courses:
                matrix = matching_mod.build_course_skill_matrix(
                    courses, self._resolve_skill_names, provenance=scope,
                    reference_credits=reference_credits, objective_skills=objective_skills,
                    min_courses=min_courses, vector=vector,
                )
            by_school: dict[str, int] = {}
            for course in courses:
                name = str(course.get("school") or "").strip() or "未标注院校"
                by_school[name] = by_school.get(name, 0) + 1
            return {
                "courses": courses,
                "vector": vector,
                "matrix": matrix,
                "n_courses": len(courses),
                # 按院校拆分：宏观/区域口径必须能说清"这份课程池由哪些学校组成"
                "by_school": [{"school": k, "n_courses": v}
                              for k, v in sorted(by_school.items(), key=lambda kv: -kv[1])],
                "n_schools": len(by_school),
                "scope": scope,
                "partial": bool(getattr(vector, "partial", False)) if vector else False,
                "reason": reason or (vector.reason if vector else "无课程证据"),
            }

        target_reason = ""
        if not plan.school:
            target_reason = "未指定目标高校，不存在目标供给口径"
        elif target_vector is None:
            target_reason = f"{plan.school} 无可核查课程证据"
        elif not target_ok:
            target_reason = target_vector.reason or "目标高校课程证据不足"
        target = scope_info(target_courses, target_vector,
                            "school_specific" if plan.school else "none", target_reason)
        peer = scope_info(peer_courses, peer_vector, "cross_school_pool")
        if used == "peer" and plan.school:
            peer["reason"] = (
                f"{plan.school} 目标供给为 insufficient_evidence（{target_reason}），"
                "Skill Fit 以北京同类专业基准口径计算并在此披露；目标校真实供给单列。"
            )

        course_scope = {
            "scope": "school_specific" if plan.school else "cross_school_pool",
            "used_for_fit": used,
            "target_status": "ok" if target_ok else "insufficient_evidence",
            "target_partial": bool(target.get("partial")),
            "n_school_specific": len(target_courses),
            "n_pool": len([c for c in peer_courses if not c.get("template")]),
            "n_template": len([c for c in peer_courses if c.get("template")]),
            "reason": self._scope_reason(plan, target, peer, target_ok, used),
            "evidence_level": "D",
        }
        return {
            "target": target, "peer": peer, "used": used,
            "course_scope": course_scope, "courses": (target if used == "target" else peer)["courses"],
        }

    @staticmethod
    def _scope_reason(
        plan: ResearchPlan, target: dict[str, Any], peer: dict[str, Any],
        target_ok: bool, used: str,
    ) -> str:
        if not plan.school:
            return ("未指定目标高校，Skill Fit 使用北京同类专业课程池口径；"
                    "若需目标校口径请在问题中点名高校")
        if target_ok and target.get("partial"):
            return (f"{plan.school} 目标供给为 partial_evidence（{target.get('reason')}）；"
                    "Skill Fit 以该校可核查课程为保守下界，同时给出北京同类专业基准对照")
        if target_ok:
            return f"Skill Fit 使用 {plan.school} 本校可核查课程口径"
        return peer.get("reason", "" ) or (
            f"{plan.school} 目标供给为 insufficient_evidence，已改用北京同类专业基准口径并披露")

    def _school_records(self, plan: ResearchPlan, metrics: list[str]) -> list[dict[str, Any]]:
        ds = self.dataset
        by_school: dict[str, dict[str, list[float]]] = {}
        for f in ds.facts:
            if f.value is None or f.fact_type not in metrics:
                continue
            if plan.family:
                if f.family != plan.family:
                    continue
            else:
                # 通用专业（非 ai/cs/econ 三族）`plan.family` 为空，若仍按族过滤会把
                # 该校该专业的就业事实整体丢掉——「多校就业结果对比」会整块消失。
                # 这里改按**专业名**匹配（事实里带 major 字段）。
                from edumatch.dataset import major_matches

                if plan.major and not major_matches(str(f.major or ""), plan.major):
                    continue
            by_school.setdefault(f.school, {}).setdefault(f.fact_type, []).append(f.value)
        records: list[dict[str, Any]] = []
        for school, values in by_school.items():
            row: dict[str, Any] = {"school": school}
            for metric in metrics:
                vals = values.get(metric) or []
                row[metric] = round(sum(vals) / len(vals), 4) if vals else None
                row[f"{metric}_n"] = len(vals)
            records.append(row)
        return records

    def _crosscheck_reported_gaps(self, gaps: dict[str, Any], demands) -> dict[str, Any]:
        """Compare model-computed gaps with gaps explicitly recorded in the archive."""
        me = self.dataset.market_evidence
        reported = list(me.get("reported_gaps") or [])
        high_pay = list(me.get("high_pay_weak_curriculum") or [])
        computed = {r["skill"]: r for r in gaps.get("rows", [])}
        alias = {"数据架构": "数据工程", "数据治理": "数据工程", "数据中台开发": "数据工程",
                 "TensorFlow": "TensorFlow", "PyTorch": "PyTorch",
                 "AI应用开发": "大模型", "智能体方向": "Agent", "智慧运维": "模型部署",
                 "医疗影像处理": "计算机视觉"}
        rows = []
        for item in reported + high_pay:
            key = alias.get(item, item)
            row = computed.get(key)
            rows.append(
                {
                    "archive_reported": item,
                    "mapped_skill": key,
                    "computed_gap": None if not row else row["gap"],
                    "computed_status": "unknown" if not row else row["status"],
                    "agreement": (
                        "unknown" if not row or row["gap"] is None
                        else "consistent" if row["gap"] > 0 else "model_disagrees"
                    ),
                }
            )
        return {
            "rows": rows,
            "n_reported": len(reported) + len(high_pay),
            "evidence_level": "D",
            "source": me.get("source_document"),
            "note": "归档缺口为旧版工作流给出的语义判断（D 级）；此处与 2.0 定量结果交叉核对，便于发现分歧。",
        }

    def _literature_context(self, evidence: EvidenceStore) -> dict[str, Any]:
        """Load cached literature retrieved automatically from open APIs."""
        path = self.settings.processed_dir / "literature.json"
        if not path.exists():
            return {
                "status": "insufficient_evidence",
                "reason": "尚未检索文献；运行 python scripts/fetch_literature.py（OpenAlex，robots 允许）",
                "source": None,
            }
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {"status": "insufficient_evidence", "reason": "literature.json 解析失败"}
        works = payload.get("works") or []
        for work in works[:5]:
            evidence.add(
                EvidenceItem(
                    evidence_id=f"ev:literature:{hashlib.sha1(str(work.get('work_id')).encode()).hexdigest()[:10]}",
                    source_type="literature",
                    title=str(work.get("title") or "")[:120],
                    locator=str(work.get("doi") or work.get("work_id") or ""),
                    quote=str(work.get("venue") or "") + f" ({work.get('year')})",
                    year=work.get("year"),
                    url=work.get("open_access_url") or work.get("url"),
                    retrieval_time=payload.get("retrieval_time"),
                    evidence_level="B",
                    confidence=0.7,
                )
            )
        years = [w.get("year") for w in works if w.get("year")]
        return {
            "status": "ok" if works else "insufficient_evidence",
            "source": payload.get("source"),
            "robots": payload.get("robots"),
            "retrieval_time": payload.get("retrieval_time"),
            "n_works": len(works),
            "queries": payload.get("queries"),
            "year_range": [min(years), max(years)] if years else None,
            "top_by_citation": [
                {"title": w.get("title"), "year": w.get("year"),
                 "cited_by_count": w.get("cited_by_count"), "doi": w.get("doi")}
                for w in works[:5]
            ],
            "note": "文献用于方法论与机制假设的学术依据，不替代本项目的一手数据结论。",
        }

    def _benchmark_context(
        self, plan: ResearchPlan, supply_bundle: dict[str, Any],
        matching_bundle: dict[str, Any], market: dict[str, Any],
    ) -> dict[str, Any]:
        """教育背景横向比较（保留）+ 技能级供需基准与三角比较（核心）。"""
        metrics = ["placement_rate", "signing_rate", "further_study_rate",
                   "practice_credit_ratio", "senior_title_ratio"]
        records = self._school_records(plan, metrics)
        table = benchmark_mod.benchmark_table(records, metrics, entity_key="school", min_n=1)
        bench = dict(table)
        bench["education_background"] = dict(table)
        bench["interpretation"] = (
            "教育背景指标（就业率/师资/实践学分）仅作背景；核心基准是技能级供需比较，"
            "用于解释同类需求下不同高校为何形成不同供给结构。缺失值显示 null，不参与排序。"
        )
        target_matrix = supply_bundle["target"].get("matrix")
        peer_matrix = supply_bundle["peer"].get("matrix")
        target_fit = matching_bundle["fit"]["target"]
        peer_fit = matching_bundle["fit"]["peer"]
        target_gaps = (matching_bundle.get("gaps_target") or {})
        peer_gaps = (matching_bundle.get("gaps_peer") or {})
        bench["skill_benchmark"] = benchmark_mod.skill_benchmark(
            demand=matching_bundle["demand_map"],
            target_supply=(target_matrix.supply if target_matrix else {}),
            peer_supply=(peer_matrix.supply if peer_matrix else {}),
            target_gaps={r["skill"]: r["gap"] for r in target_gaps.get("rows", [])},
            peer_gaps={r["skill"]: r["gap"] for r in peer_gaps.get("rows", [])},
        )
        bench["triangle"] = benchmark_mod.triangle(
            target={
                "scope": supply_bundle["target"].get("scope"),
                "n_courses": supply_bundle["target"].get("n_courses"),
                "reliability": target_fit.get("supply_reliability"),
                "fit": target_fit, "gap": target_gaps,
            },
            peer={
                "scope": supply_bundle["peer"].get("scope"),
                "n_courses": supply_bundle["peer"].get("n_courses"),
                "reliability": peer_fit.get("supply_reliability"),
                "fit": peer_fit, "gap": peer_gaps,
            },
            market={
                "scope": "北京招聘市场（HAR 导入岗位）",
                "reliability": market.get("evidence_level"),
                "n_effective_jobs": market.get("effective_count"),
            },
        )
        return bench

    def _trend_context(self, plan: ResearchPlan, courses: list[dict[str, Any]]) -> dict[str, Any]:
        ds = self.dataset
        out: dict[str, Any] = {}
        for fact_type in ("placement_rate", "signing_rate", "further_study_rate", "practice_credit_ratio"):
            series = ds.fact_series(plan.family, fact_type, plan.school)
            out[fact_type] = trend_mod.series_summary(series, label=fact_type)
        # 培养侧：课程按年份计数（覆盖面的年度轨迹）
        by_year: dict[int, float] = {}
        for course in courses:
            year = course.get("year")
            if isinstance(year, int):
                by_year[year] = by_year.get(year, 0.0) + 1.0
        curriculum = trend_mod.series_summary(
            sorted(by_year.items()), label="curriculum_course_count")
        out["curriculum_supply"] = curriculum
        # 市场侧：单期抓包无法构成时间序列，如实记 insufficient_evidence
        out["market_skill_demand"] = {
            "label": "market_skill_demand",
            "status": "insufficient_evidence",
            "n_periods": 1,
            "reason": "招聘数据只有一个抓取时间窗口，无法构成技能需求时间序列",
        }
        out["response"] = trend_mod.response_analysis(
            out["market_skill_demand"], curriculum, skill=f"{plan.major}技能需求")
        return out

    def _mechanism_context(
        self, plan: ResearchPlan, policy: dict[str, Any], demand_vector: dict[str, Any],
        supply_bundle: dict[str, Any], matching_bundle: dict[str, Any],
    ) -> dict[str, Any]:
        metrics = ["placement_rate", "practice_credit_ratio", "senior_title_ratio", "student_faculty_ratio"]
        records = [r for r in self._school_records(plan, metrics)]
        pairs = [(r.get("practice_credit_ratio"), r.get("placement_rate")) for r in records]
        pairs = [p for p in pairs if p[0] is not None and p[1] is not None]
        corr = mechanism_mod.pearson([p[0] for p in pairs], [p[1] for p in pairs])
        features = {
            "practice_credit_ratio": [r.get("practice_credit_ratio") for r in records],
            "senior_title_ratio": [r.get("senior_title_ratio") for r in records],
            "student_faculty_ratio": [r.get("student_faculty_ratio") for r in records],
        }
        target = [r.get("placement_rate") for r in records]
        importance = mechanism_mod.permutation_importance(features, target)
        used_matrix = (supply_bundle["target"] if supply_bundle["used"] == "target"
                       else supply_bundle["peer"]).get("matrix")
        used_gaps = matching_bundle["gaps"] or {}
        path = mechanism_mod.association_path(
            policy_topics=policy.get("industry_direction") or [],
            policy_skills=policy.get("skills_related") or [],
            demand=demand_vector.get("score") or {},
            supply=(used_matrix.supply if used_matrix else {}),
            gaps={r["skill"]: r["gap"] for r in used_gaps.get("rows", [])},
            industry_counts=policy.get("industry_counts") or {},
        )
        return {
            "association_practice_vs_placement": corr,
            "importance_on_placement_rate": importance,
            "n_schools": len(records),
            "n_paired_observations": len(pairs),
            "policy_industry_counts": policy.get("industry_counts") or {},
            "association_path": path,
            "language_guard": "以下表述均已按『关联/解释路径』口径生成，不做因果断言。",
        }

    def _simulation_context(
        self,
        plan: ResearchPlan,
        courses: list[dict[str, Any]],
        matching_bundle: dict[str, Any],
        context: dict[str, Any],
        supply_bundle: dict[str, Any],
        benchmark_values: dict[str, float],
    ) -> dict[str, Any]:
        demand_map = matching_bundle["demand_map"]
        demand_meta = matching_bundle["demand_meta"]
        names = {s.skill_id: s.name for s in self.ontology.all_skills()}

        def tsi_pair(ctx: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
            """(TSI 2.0 research comparison, Primary TSI) for one scenario context."""
            v2_metrics = tsi_mod.score_indicators(ctx, benchmark_values)
            v2 = tsi_mod.compute_tsi(v2_metrics)
            primary_metrics = primary_mod.score_indicators(
                ctx, benchmark_values, legacy_metrics=v2_metrics)
            return v2, primary_mod.compute(primary_metrics)

        def scenario_context(similarity: dict[str, Any], gaps: dict[str, Any],
                             channels: dict[str, Any]) -> dict[str, Any]:
            return {
                **context,
                "matching": similarity,
                "fit": {
                    "fit": similarity.get("matching_score"),
                    "fit_100": similarity.get("matching_score_100"),
                    "per_skill": similarity.get("per_skill") or [],
                    "confidence": similarity.get("confidence") or 0.0,
                    "status": "ok",
                    "supply_provenance": matching_bundle["matching"].get("scope", "target"),
                    "supply_reliability": "medium",
                },
                "gaps": gaps,
                "supply_channels": channels or {},
            }

        def evaluate(sim: dict[str, Any]) -> dict[str, Any]:
            before_ctx = scenario_context(sim["matching_before"], sim["gaps_before"],
                                          sim.get("base_channels") or {})
            after_ctx = scenario_context(sim["matching_after"], sim["gaps_after"],
                                         sim.get("new_channels") or {})
            v2_before, primary_before = tsi_pair(before_ctx)
            v2_after, primary_after = tsi_pair(after_ctx)
            sim["tsi_before"] = primary_before.get("primary_tsi")
            sim["tsi_after"] = primary_after.get("primary_tsi")
            sim["tsi_delta"] = (
                None if sim["tsi_before"] is None or sim["tsi_after"] is None
                else round(sim["tsi_after"] - sim["tsi_before"], 2)
            )
            sim["primary_tsi_before_detail"] = primary_before
            sim["primary_tsi_after_detail"] = primary_after
            sim["v2_tsi_before"] = v2_before.get("tsi_v2")
            sim["v2_tsi_after"] = v2_after.get("tsi_v2")
            return sim

        scenario_courses = list(courses)
        additions = [
            simulation_mod.CurriculumChange(
                kind="add_course", course_name="大模型应用开发", credits=3.0,
                skills=["大模型", "RAG", "Prompt工程", "Agent"],
                note="企业岗位与政策均指向的新兴技能",
            ),
            simulation_mod.CurriculumChange(
                kind="add_course", course_name="MLOps 与模型部署实践", credits=2.5,
                skills=["MLOps", "Docker", "模型部署"], practice_hours=32,
                note="工程化能力缺口",
            ),
        ]
        results = []
        for change in additions:
            results.append(evaluate(
                simulation_mod.simulate_curriculum_change(
                    courses=scenario_courses,
                    change=change,
                    resolve_skills=self._resolve_skill_names,
                    demand=demand_map,
                    demand_meta=demand_meta,
                    skill_names=names,
                )
            ))
        combined = evaluate(
            simulation_mod.simulate_curriculum_change(
                courses=scenario_courses,
                change=simulation_mod.CurriculumChange(
                    kind="add_course", course_name="大模型应用开发 + MLOps 组合方案", credits=5.5,
                    skills=["大模型", "RAG", "Prompt工程", "Agent", "MLOps", "Docker", "模型部署"],
                    practice_hours=32,
                    note="组合方案：同时补齐应用层与工程化缺口",
                ),
                resolve_skills=self._resolve_skill_names,
                demand=demand_map,
                demand_meta=demand_meta,
                skill_names=names,
            )
        )
        return {
            "single_scenarios": results,
            "combined_scenario": combined,
            "base_course_source": (
                "target_school_evidence" if supply_bundle["used"] == "target"
                else "beijing_peer_pool"
            ),
            "base_scope": supply_bundle["used"],
            "assumptions": simulation_mod.ASSUMPTIONS,
            "disclaimer": "模拟结果基于当前数据与模型假设，不是对未来就业结果的预测。",
        }

    def _retrieval_context(
        self,
        *,
        plan: ResearchPlan,
        courses: list[dict[str, Any]],
        demand_vector: dict[str, Any],
        occupation_bundle: dict[str, Any],
        literature: dict[str, Any],
        policy: dict[str, Any],
        source_report: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """本轮"定点检索清单"：把该院校/专业实际用到的每一类数据列出来，便于核对与审计。

        回答的问题是"模型是否真的把这批数据用上了"——每一类都给出实际命中的数量与来源样例。
        """
        ds = self.dataset
        school = plan.school or ""
        major = plan.major

        def text_files(*categories: str) -> list[str]:
            if not school:
                return []
            return sorted({
                str(p.relative_to(ds.settings.project_root))
                for root in ds.text_roots()
                for p in root.rglob("*.txt")
                if school in str(p) and any(c in str(p) for c in categories)
            })

        plan_sources = sorted({str(c.get("source_document") or "") for c in courses if c.get("source_document")})
        facts = [f for f in ds.facts
                 if (not school or f.school == school)
                 and f.major and (major in str(f.major) or str(f.major) in major)]
        fact_types = sorted({f.fact_type for f in facts})
        fact_docs = sorted({str(f.source_document) for f in facts})
        school_facts = [f for f in ds.facts
                        if (not school or f.school == school) and f.family == "school"]
        school_fact_types = sorted({f.fact_type for f in school_facts})
        report_texts = text_files("就业质量报告", "教学质量报告")
        syllabus_texts = text_files("课程大纲")
        intro_texts = text_files("专业介绍", "培养方案")
        policies = list(policy.get("industry_direction") or [])
        return {
            "target": {"school": school or "（区域口径）", "major": major,
                       "family": plan.family or "通用"},
            "supply": {
                "plan_pdfs": len(plan_sources), "courses": len(courses),
                "samples": plan_sources[:3],
            },
            "curriculum_texts": {
                "syllabi": len(syllabus_texts), "major_intro_or_plan": len(intro_texts),
                "samples": (syllabus_texts[:2] + intro_texts[:1]),
            },
            "employment": {
                "major_facts": len(facts), "fact_types": fact_types,
                "source_reports": len(fact_docs), "samples": fact_docs[:2],
                "school_level_facts": len(school_facts),
                "school_level_fact_types": school_fact_types,
                "fallback": ("该专业口径无分专业行，按同校校级口径回退（已标注）"
                             if not facts and school_facts else ""),
            },
            "school_reports": {
                "texts": len(report_texts),
                "categories": sorted({("就业质量报告" if "就业质量报告" in t else "教学质量报告")
                                      for t in report_texts}),
                "samples": report_texts[:2],
            },
            "policy": {"matched_documents": policy.get("n_matched_documents"),
                       "industry_topics": policies[:6]},
            "market": {"demand_skills": demand_vector.get("n_skills"),
                       "occupation": (occupation_bundle.get("occupation") or {}).get("name"),
                       "occupation_jobs": occupation_bundle.get("n_jobs")},
            "literature": {"n_works": literature.get("n_works")},
            "data_source": source_report or {"mode": ds.source_mode},
            "note": ("以上为该院校/专业本次实际命中的数据类别；某类为 0 表示本地数据未覆盖该口径，"
                     "报告中相应指标按证据不足处理。"),
        }

    #: 冲突修正时，用与供给向量同一公式（Σ课程权重 / C_ref）重算，而不是拍一个数字。
    def _resolve_evidence_conflicts(
        self,
        plan: ResearchPlan,
        courses: list[dict[str, Any]],
        supply_bundle: dict[str, Any],
        matching_bundle: dict[str, Any],
    ) -> dict[str, Any]:
        """引擎结果 vs 课程原始证据的冲突消解，只重算受影响技能及其上层指标。"""
        key = "target" if supply_bundle.get("used") == "target" else "peer"
        info = supply_bundle.get(key) or {}
        vector = info.get("vector")
        supply_score = dict(getattr(vector, "score", None) or {})
        demand_map = matching_bundle.get("demand_map") or {}
        demand_meta = matching_bundle.get("demand_meta") or {}
        if not supply_score or not demand_map or not courses:
            return {"status": "skipped", "changed_skills": [], "records": [],
                    "reason": "缺少供给/需求向量或课程证据"}
        evidence = self._conflict_evidence(courses, demand_map, supply_score)
        if not evidence:
            return {"status": "no_conflict", "changed_skills": [], "records": [],
                    "note": "引擎供给与课程原始证据未发现冲突"}
        result = conflict_mod.resolve_conflicts(
            supply_score, demand_map, evidence, demand_meta=demand_meta,
            supply_provenance=str(getattr(vector, "provenance", "") or key),
            supply_reliability=str(getattr(vector, "reliability", "") or "medium"),
            unlisted_supply_is_zero=True,
        )
        if result.get("status") == "reconciled":
            corrected = result["reconciled_supply"]
            corrected_fit = fit_mod.skill_fit(
                corrected, demand_map, demand_meta=demand_meta,
                supply_provenance=str(getattr(vector, "provenance", "") or key),
                supply_reliability=str(getattr(vector, "reliability", "") or "medium"),
                unlisted_supply_is_zero=True,
            )
            matching_bundle.setdefault("fit", {})[key] = corrected_fit
            corrected_gaps = gap_mod.compute_skill_gaps(
                demand_map, corrected, demand_meta=demand_meta, unlisted_supply_is_zero=True)
            if key == "target":
                matching_bundle["gaps_target"] = corrected_gaps
            else:
                matching_bundle["gaps_peer"] = corrected_gaps
            result["applied_to"] = f"fit.{key}"
        return result

    def _conflict_evidence(
        self,
        courses: list[dict[str, Any]],
        demand_map: Mapping[str, float],
        supply_score: Mapping[str, float | None],
    ) -> dict[str, dict[str, Any]]:
        """对"引擎记为 0/缺失、但课程原文明确出现"的技能构造高等级证据。"""
        out: dict[str, dict[str, Any]] = {}
        ref = supply_mod.DEFAULT_REFERENCE_CREDITS
        for skill, demand in demand_map.items():
            if not skill or not isinstance(demand, (int, float)) or demand <= 0:
                continue
            current = supply_score.get(skill)
            if current is not None and current >= 0.05:
                continue
            matched: list[dict[str, Any]] = []
            for course in courses:
                text = f"{course.get('name') or ''} {course.get('description') or ''}"
                if skill in text:
                    matched.append(course)
            if not matched:
                continue
            weight = 0.0
            for course in matched:
                w, _audit = supply_mod.course_supply_weight(course)
                weight += w
            value = min(weight / ref, 1.0) if ref else 0.0
            if value <= 0:
                continue
            out[str(skill)] = {
                "value": round(value, 4),
                "evidence_level": "B",
                "evidence_id": f"ev:courses:{skill}",
                "quote": str(matched[0].get("name") or "")[:80],
                "mapping_reason": (
                    f"课程材料明确出现「{skill}」({len(matched)} 门) 但结构化技能映射未命中；"
                    "按同一供给公式 Σw/C_ref 重算该技能供给"),
            }
        return out

    def _coverage_context(self, plan: ResearchPlan, courses: list[dict[str, Any]]) -> dict[str, Any]:
        """高校覆盖快照：覆盖样本口径 + 点名院校时的材料级状态机。"""
        from collections import Counter

        counter = Counter(str(c.get("school") or "") for c in courses if c.get("school"))
        light: dict[str, Any] = {
            "mode": "coverage_sample",
            "n_schools": len(counter),
            "n_courses": len(courses),
            "schools": [{"school": k, "n_courses": v} for k, v in counter.most_common()],
            "note": "覆盖高校样本口径（本地入库样本），非全市全量，不得表述为区域总供给。",
        }
        if not plan.school:
            light["tip"] = ("需要逐校材料级覆盖审计时运行 "
                            "`python scripts\\audit_university_coverage.py --major <专业>`")
            return light
        try:
            from edumatch.coverage_pipeline import audit_university_coverage

            audit = audit_university_coverage(
                self.settings.project_root, major=plan.major or "人工智能",
                schools=[plan.school])
            school_info = (audit.get("per_school") or {}).get(plan.school) or {}
            light["school_audit"] = {
                "school": plan.school,
                "ready": school_info.get("ready"),
                "ready_materials": school_info.get("ready_materials") or [],
                "missing_materials": school_info.get("missing_materials") or [],
                "materials": school_info.get("materials") or {},
                "coverage_rate": audit.get("coverage_rate"),
                "note": audit.get("note"),
            }
        except Exception as exc:  # noqa: BLE001 - 覆盖审计失败不影响主分析
            light["school_audit"] = {"status": "unavailable",
                                     "reason": f"{type(exc).__name__}: {exc}"}
        return light

    def _data_quality(
        self,
        *,
        plan: ResearchPlan,
        supply_bundle: dict[str, Any],
        matching_bundle: dict[str, Any],
        demand_vector: dict[str, Any],
        employment: dict[str, Any],
        trends: dict[str, Any],
        occupation_bundle: dict[str, Any],
        primary_result: dict[str, Any],
        tsi_result: dict[str, Any],
    ) -> dict[str, Any]:
        """Data coverage and credibility, so a low score is never mistaken for a finding."""
        target = supply_bundle["target"]
        peer = supply_bundle["peer"]
        target_fit = matching_bundle["fit"]["target"]

        def status(ok: bool) -> str:
            return "ok" if ok else "insufficient_evidence"

        checks = [
            {"item": "目标高校课程供给", "status": status(target_fit.get("status") == "ok"),
             "detail": f"{target.get('n_courses', 0)} 门可核查课程；"
                       f"可靠度 {target_fit.get('supply_reliability')}；{target.get('reason') or ''}"},
            {"item": "北京同类专业基准供给", "status": status(peer.get("n_courses", 0) > 0),
             "detail": f"{peer.get('n_courses', 0)} 门课程（含 E 级模板课程）"},
            {"item": "市场需求向量", "status": status(demand_vector.get("n_skills", 0) > 0),
             "detail": f"{demand_vector.get('n_skills', 0)} 个技能；"
                       f"缺失分量 {demand_vector.get('unavailable_components')}；"
                       f"{self.dataset.demand_scope_note or '语料范围匹配'}"},
            {"item": "就业结果（就业质量报告）",
             "status": status(employment.get("placement_rate") is not None),
             "detail": (f"落实率 {'可用' if employment.get('placement_rate') is not None else '缺失'}；"
                        f"签约率 {'可用' if employment.get('signing_rate') is not None else '缺失'}"
                        "（只取自就业质量报告，招聘数据不参与该维度）")},
            {"item": "用人单位评价", "status": status(employment.get("employer_rating") is not None),
             "detail": (f"满意度 {employment.get('employer_rating')}"
                        if employment.get("employer_rating") is not None
                        else "无调查数据记 null，不用 JD 反推")},
            {"item": "多期趋势", "status": status(any(t.get("status") == "ok" for t in trends.values())),
             "detail": f"{sum(1 for t in trends.values() if t.get('status') == 'ok')}/"
                       f"{len(trends)} 个序列达到 ≥2 个不同年份"},
        ]
        occ_match = occupation_bundle.get("match") or {}
        occ_name = (occupation_bundle.get("occupation") or {}).get("name")
        checks.append({
            "item": "目标岗位样本",
            "status": (
                "ok" if occ_match.get("match_score") is not None
                else "insufficient_evidence"
            ),
            "detail": (
                f"目标岗位「{occ_name}」，语料匹配 {occupation_bundle.get('n_jobs')} 条岗位"
                f"（{occupation_bundle.get('match_scope') or '—'}）；"
                f"匹配度 {occ_match.get('match_100')}"
                if occ_match.get("match_score") is not None
                else (occupation_bundle.get("reason") or "未指定目标岗位或岗位样本不足")
            ),
        })
        n_ok = sum(1 for c in checks if c["status"] == "ok")
        peer_available = bool(peer.get("n_courses"))
        demand_ok = bool(demand_vector.get("n_skills"))
        supply_ok = bool(target.get("n_courses"))
        if not demand_ok:
            reliability = (
                "需求侧证据不足：岗位语料未覆盖该专业，仅给出供给画像、同类基准与就业侧结论"
                if supply_ok else
                "证据不足：目标校供给与岗位需求均不可用，无法给出适配结论"
            )
        elif not plan.school and peer_available:
            reliability = "区域口径（未点名高校）：结论基于北京同类专业课程池与市场需求"
        elif target_fit.get("status") == "ok" and target_fit.get("supply_reliability") in {"high", "medium"}:
            reliability = "可支撑结论"
        elif target_fit.get("status") == "ok":
            reliability = "结论需谨慎（目标校课程证据偏少）"
        elif peer_available:
            reliability = "目标校口径证据不足，只能给出区域基准与需求侧结论"
        else:
            reliability = "证据不足（目标校与同类基准均无可核查课程，无法给出适配结论）"
        return {
            "checks": checks,
            "n_ok": n_ok,
            "n_checks": len(checks),
            "reliability": reliability,
            "primary_tsi_coverage": primary_result.get("weighted_coverage"),
            "primary_tsi_missing": primary_result.get("missing_indicators"),
            "v2_coverage": tsi_result.get("weighted_coverage"),
            "evidence_strategy": "缺失一律记 null 并披露，不补 0、不用其他口径顶替。",
            "major": plan.major,
            "school": plan.school,
        }

    def _persist(self, result: dict[str, Any]) -> None:
        try:
            from . import db

            with db.connect(self.settings) as conn:
                db.init_schema(self.settings)
                db.save_run(conn, {
                    "run_id": result["run_id"], "user_query": result["query"], "mode": result["mode"],
                    "plan": result["plan"], "tool_calls": result["tool_calls"],
                    "skill_calls": result["skill_calls"], "input_data": result["dataset_summary"],
                    "metrics": result["metrics"], "scores": result["tsi_v2"],
                    "evidence": result["evidence"], "final_answer": result.get("report", ""),
                    "started_at": result["started_at"], "finished_at": result["finished_at"],
                })
                db.save_evidence(conn, result["run_id"], result["evidence"])
                db.save_metrics(conn, result["run_id"], result["metrics"])
        except Exception as exc:  # noqa: BLE001 - persistence must not break analysis
            result.setdefault("persistence_errors", []).append(str(exc))


def include_template_used(courses: list[dict[str, Any]]) -> bool:
    return any(c.get("template") for c in courses)


def _count_by(values) -> dict[str, int]:
    out: dict[str, int] = {}
    for v in values:
        out[str(v)] = out.get(str(v), 0) + 1
    return out


def _summarize(result: Any) -> Any:
    if isinstance(result, dict):
        keys = list(result)[:8]
        return {"type": "dict", "keys": keys}
    if isinstance(result, list):
        return {"type": "list", "n": len(result)}
    return {"type": type(result).__name__, "repr": str(result)[:120]}


def _extract_section(text: str, anchors: tuple[str, ...], window: int = 300) -> str:
    """Pull the prose that follows an anchor such as '培养目标' from report text."""
    if not text:
        return ""
    for anchor in anchors:
        index = text.find(anchor)
        while index >= 0:
            snippet = text[index + len(anchor): index + len(anchor) + window]
            snippet = snippet.strip(" ：:，,。\n\t")
            if len(snippet) >= 30:      # 太短说明只是标题或目录项
                return snippet.replace("\n", " ")
            index = text.find(anchor, index + 1)
    return ""


_EMBEDDING_SCORER = None
_EMBEDDING_TRIED = False


def _embedding_scorer_singleton():
    """Load the local sentence-embedding model once; return None when unavailable."""
    global _EMBEDDING_SCORER, _EMBEDDING_TRIED
    if _EMBEDDING_TRIED:
        return _EMBEDDING_SCORER
    _EMBEDDING_TRIED = True
    import os

    if os.environ.get("EDUMATCH_DISABLE_EMBEDDINGS", "").strip() in {"1", "true", "yes"}:
        return None
    try:
        os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
        # 模型已缓存到本地：强制离线加载，避免每次启动去 Hub 做 HEAD 检查
        # （沙箱内该请求会失败并重试 5 次，白白等待 30 秒）
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
        from sentence_transformers import SentenceTransformer

        name = os.environ.get("EDUMATCH_EMBEDDING_MODEL", "BAAI/bge-small-zh-v1.5")
        try:
            model = SentenceTransformer(name, local_files_only=True)
        except TypeError:      # 旧版本不支持该参数
            model = SentenceTransformer(name)
        model._edumatch_name = name  # type: ignore[attr-defined]
        _EMBEDDING_SCORER = SemanticEvidenceScorer(model, model_name=name)
    except Exception:  # noqa: BLE001 - 模型缺失时保持可用（回退 TF-IDF / 关键词）
        _EMBEDDING_SCORER = None
    return _EMBEDDING_SCORER

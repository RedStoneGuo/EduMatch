"""In-memory research dataset assembled from the legacy archive.

``Dataset`` is the single access point used by both the analysis engine and the
tool layer, so the same numbers appear whether a tool is called through MCP,
through the agent, or from a notebook.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field, fields
from pathlib import Path
from statistics import median
from typing import Any

from .config import Settings, load_settings
from .ingest.courses import CourseRecord, extract_courses, extract_courses_from_texts
from .ingest.education_facts import EducationFact, extract_documents
from .ingest.legacy import LegacyArtifacts, load_legacy
from .ingest.policy import PolicyRecord, deduplicate, ingest_policy_dir
from .jobs.demand import SkillDemand, demand_from_aggregate, load_market_evidence
from . import occupation as occupation_mod
from .ontology import SkillOntology, load_ontology
from .source_modes import load_harvest_bundle, normalize_mode, uses_harvest

FAMILY_MAJOR = {"ai": "人工智能", "cs": "计算机", "econ": "经济管理"}

#: 常见写法 → 归档已有的专业族。仅用于消歧，不再作为"未知即兜底"的依据。
FAMILY_ALIASES: dict[str, str] = {
    "人工智能": "ai", "智能科学与技术": "ai", "ai": "ai", "机器学习": "ai",
    "计算机": "cs", "软件": "cs", "信息安全": "cs", "网络空间安全": "cs",
    "数据科学": "cs", "物联网": "cs", "网络工程": "cs",
    "经济": "econ", "金融": "econ", "会计": "econ", "财务": "econ",
    "管理": "econ", "贸易": "econ", "工商": "econ",
    # 信息管理与信息系统属经济管理族（管理学门类），但名字里带"信息"，
    # 若只按"管理"命中会把专业名截成"管理与信息系统"，故显式登记完整名称。
    "信息管理与信息系统": "econ", "信息管理": "econ",
}

#: 各专业族在岗位文本中的检索词。用于把"该专业的岗位需求"从全部岗位里筛出来，
#: 避免会计学专业复用人工智能岗位的需求向量。
FAMILY_JOB_KEYWORDS: dict[str, list[str]] = {
    "ai": ["人工智能", "算法", "机器学习", "深度学习", "大模型", "AI", "智能"],
    "cs": ["计算机", "软件", "开发", "前端", "后端", "测试", "运维", "数据", "网络", "信息安全"],
    "econ": ["会计", "财务", "审计", "金融", "经济", "税务", "投资", "风控", "管理培训"],
}

#: 岗位语料对某专业族关键词的覆盖率低于该阈值时，认为语料不覆盖该族：
#: 需求侧记 insufficient_evidence，而不是用其他族的岗位充当需求。
DEMAND_FAMILY_MIN_SHARE = 0.30

#: 招聘薪资只在**月薪**口径下可比。低于此值基本是"元/天"的实习/兼职报价，
#: 若当成月薪混进中位数，会把"目标岗位中位薪资"从两万拉到几百元。
MONTHLY_SALARY_FLOOR = 1000.0

#: 月薪分档（与 edumatch/jobs/normalize.py::parse_salary 的 bucket 口径一致）
SALARY_BUCKETS: list[tuple[str, float, float]] = [
    ("<8k", 0.0, 8000.0),
    ("8k-15k", 8000.0, 15000.0),
    ("15k-25k", 15000.0, 25000.0),
    ("25k-40k", 25000.0, 40000.0),
    (">40k", 40000.0, float("inf")),
]

_DAILY_SALARY = re.compile(r"(元|块)?\s*/\s*(天|日|小时|时)")


def salary_is_daily(row: dict[str, Any]) -> bool:
    """判断一条岗位的薪资是否为日薪/时薪口径（不可与月薪同池比较）。"""
    if str(row.get("salary_bucket") or "") == "daily":
        return True
    detail = str(row.get("salary_detail") or "")
    return bool(_DAILY_SALARY.search(detail)) or "元/天" in detail


def row_monthly_salary(row: dict[str, Any]) -> float | None:
    """取一条岗位的**月薪中值**；日薪/时薪与低于下限的报价返回 None。

    HAR 导入的岗位里 ``salary_min_norm`` / ``salary_max_norm`` 常为 null，
    真正可用的是 ``salary_min`` / ``salary_max``，这里两套都认。
    """
    if salary_is_daily(row):
        return None
    values: list[float] = []
    for norm_key, raw_key in (("salary_min_norm", "salary_min"),
                              ("salary_max_norm", "salary_max")):
        value = row.get(norm_key)
        if not isinstance(value, (int, float)):
            value = row.get(raw_key)
        if isinstance(value, (int, float)) and value > 0:
            values.append(float(value))
    if not values:
        return None
    midpoint = sum(values) / len(values)
    return midpoint if midpoint >= MONTHLY_SALARY_FLOOR else None


def salary_bucket_of(midpoint: float | None) -> str:
    if not isinstance(midpoint, (int, float)):
        return "unknown"
    for label, low, high in SALARY_BUCKETS:
        if low <= midpoint < high:
            return label
    return "unknown"


def percentile(values: list[float], q: float) -> float | None:
    """线性插值分位数（q ∈ [0,1]）；空列表返回 None，不做任何补位。"""
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    pos = q * (len(ordered) - 1)
    low = int(pos)
    high = min(low + 1, len(ordered) - 1)
    frac = pos - low
    return ordered[low] + (ordered[high] - ordered[low]) * frac


def summarize_salaries(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """岗位薪资画像：中位数 / 四分位 / 分档分布 / 剔除口径，全部可披露。"""
    values: list[float] = []
    n_daily = 0
    n_unknown = 0
    for row in rows:
        if salary_is_daily(row):
            n_daily += 1
            continue
        value = row_monthly_salary(row)
        if value is None:
            n_unknown += 1
            continue
        values.append(value)
    buckets = Counter(salary_bucket_of(v) for v in values)
    return {
        "median_salary": (median(values) if values else None),
        "p25_salary": percentile(values, 0.25),
        "p75_salary": percentile(values, 0.75),
        "n_with_salary": len(values),
        "n_daily_excluded": n_daily,
        "n_salary_unknown": n_unknown,
        "salary_buckets": dict(sorted(buckets.items(), key=lambda kv: -kv[1])),
        "salary_note": (
            "" if values else
            ("该批岗位全部为日薪/兼职报价或未披露薪资，月薪口径记 null（不估算）"
             if n_daily else "该批岗位语料未提供可用月薪数值，薪资口径记 null")
        ),
    }


@dataclass
class Dataset:
    settings: Settings
    facts: list[EducationFact] = field(default_factory=list)
    courses: list[CourseRecord] = field(default_factory=list)
    policies: list[PolicyRecord] = field(default_factory=list)
    policy_duplicates: list[dict[str, str]] = field(default_factory=list)
    market_evidence: dict[str, Any] = field(default_factory=dict)
    legacy: LegacyArtifacts | None = None
    ontology: SkillOntology | None = None
    template_courses: list[dict[str, Any]] = field(default_factory=list)
    jobs: list[dict[str, Any]] = field(default_factory=list)
    jobs_meta: dict[str, Any] = field(default_factory=dict)
    pdf_facts_count: int = 0
    available_families: dict[str, str] = field(default_factory=dict)  # family -> curated file
    golden_facts: list[EducationFact] = field(default_factory=list)   # 仅用于人工/自动校验
    major_rows_count: int = 0
    #: 需求语料与目标专业族不匹配时写入的原因（供报告与数据质量披露）
    demand_scope_note: str = ""
    #: 检索缓存：课程池与"课程→技能"映射在一次进程内复用，避免每次分析重算 4000+ 门课
    _course_cache: dict[Any, list[dict[str, Any]]] = field(default_factory=dict, repr=False)
    #: 专业目录缓存（任意专业支持）
    _major_catalog: dict[str, Any] | None = None
    #: 任意专业的"课程派生词表"：本体未覆盖的领域（机械/土木/材料…）用它建统一技能空间
    major_vocabulary: set[str] = field(default_factory=set)
    #: 技能词表模式：``data_driven``=按专业数据构建（所有专业同一条路）；``ontology``=回退
    vocabulary_mode: str = "ontology"
    # ---------- 数据来源模式（local / plugin / hybrid） ----------
    #: 供给端数据来源：local=纯本地库；plugin=只用插件收割；hybrid=本地+插件合并
    source_mode: str = "local"
    #: 已装载的插件收割院校；供报告披露与定点检索
    harvest_schools: tuple[str, ...] = ()
    #: 插件收割的正文缓存根目录（data/harvest/<校>/texts）
    harvest_text_roots: list[Path] = field(default_factory=list)
    #: 各来源的规模（供报告披露，不代表权重）
    source_counts: dict[str, int] = field(default_factory=dict)
    #: 本地数据快照（首次装配前保存，保证模式可反复切换而不叠加）
    _local_snapshot: dict[str, Any] = field(default_factory=dict, repr=False)

    # ---------- construction ----------
    @classmethod
    def build(cls, settings: Settings | None = None, *, with_policies: bool = True,
              with_golden: bool = True, source_mode: str = "local",
              harvest_schools: tuple[str, ...] | list[str] = ()) -> "Dataset":
        settings = settings or load_settings()
        ds = cls(settings=settings, ontology=load_ontology())
        raw_dir = settings.project_root / "data" / "raw"
        # 专业族注册表优先读 config.families——这样三份策展总结文档（majors_*.txt）
        # 即使被删除也不影响"能分析哪些专业族"；它们仅作为可选的校核金标准。
        # 未配置时回退到旧的"按文件名发现"行为。
        configured = settings.section("families")
        if configured:
            curated = []
            ds.available_families = {}
            for family, meta in configured.items():
                meta = meta or {}
                path = settings.resolve(str(meta.get("curated") or ""))
                ds.available_families[family] = str(path)
                if path.exists():
                    curated.append((path, family))
        else:
            curated = [(path, path.stem.split("_", 1)[1]) for path in sorted(raw_dir.glob("majors_*.txt"))]
            ds.available_families = {family: str(path) for path, family in curated}
        # 三份策展文档是**人工核查用的金标准**，不进入分析数据源。
        ds.golden_facts = extract_documents(curated) if with_golden else []
        # 分析数据源 = 从官方报告 PDF 中自行抽取的事实（校级 + 分专业）
        ds.facts = []
        ds._load_pdf_facts()          # 校级口径：就业率/满意度/师资/实践学分等
        ds._load_pdf_major_rows()
        ds.courses = extract_courses([p for p, _ in curated])
        ds.courses.extend(ds._legacy_courses())
        ds._tag_course_families()
        ds._load_supplementary_courses()
        if with_policies:
            policy_dir = settings.resolve(
                settings.raw.get("ingestion", {}).get("policy_dir", "")
            )
            # 只有"真的是政策原文"才算有原文——否则发布包里的占位 README.md 会被
            # 当成一条政策吃进去（实测：政策库只剩 1 条、命中 0、报告该节变空）。
            has_raw = policy_dir.exists() and any(
                p.is_file() and p.suffix.lower() in {".docx", ".doc", ".pdf", ".xls", ".xlsx"}
                for p in policy_dir.rglob("*"))
            if has_raw:
                # 本地/全量场景：按原文实时解析（行为与历史一致）
                records = ingest_policy_dir(
                    policy_dir,
                    max_chars=int(settings.raw.get("ingestion", {}).get("max_policy_chars", 20000)),
                )
                ds.policies, ds.policy_duplicates = deduplicate(records)
            else:
                # 发布包场景：不携带 147 个政策原文，改读预解析缓存
                # （由 scripts/export_policy_cache.py 生成；口径与实时解析同源）
                ds.policies, ds.policy_duplicates = _load_policy_cache(settings)
        market_path = raw_dir / "jobs_market_evidence.json"
        if market_path.exists():
            ds.market_evidence = load_market_evidence(market_path)
        template_path = raw_dir / "curriculum_template_ai.json"
        if template_path.exists():
            ds.template_courses = json.loads(template_path.read_text(encoding="utf-8")).get("courses", [])
        jobs_path = settings.processed_dir / "jobs.json"
        if jobs_path.exists():
            try:
                ds.jobs = json.loads(jobs_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                ds.jobs = []
        jobs_meta_path = settings.processed_dir / "jobs_meta.json"
        if jobs_meta_path.exists():
            ds.jobs_meta = json.loads(jobs_meta_path.read_text(encoding="utf-8"))
        record_dir = settings.archive_dir / "输出过程记录"
        if record_dir.exists():
            ds.legacy = load_legacy(record_dir)
        ds._local_snapshot = {
            "courses": list(ds.courses), "facts": list(ds.facts),
            "template_courses": list(ds.template_courses), "legacy": ds.legacy,
            "golden_facts": list(ds.golden_facts),
        }
        ds._apply_source_mode(source_mode, harvest_schools)
        return ds

    # ---------- 数据来源模式 ----------
    def _apply_source_mode(self, source_mode: str, harvest_schools) -> None:
        """按模式装配供给端：local 原样；plugin 只用收割数据；hybrid 合并去重。"""
        mode = normalize_mode(source_mode)
        self.source_mode = mode
        snapshot = self._local_snapshot or {
            "courses": list(self.courses), "facts": list(self.facts),
            "template_courses": list(self.template_courses), "legacy": self.legacy,
            "golden_facts": list(self.golden_facts),
        }
        self._local_snapshot = snapshot
        local_courses = list(snapshot["courses"])
        local_facts = list(snapshot["facts"])
        if not uses_harvest(mode):
            self.courses, self.facts = local_courses, local_facts
            self.template_courses = list(snapshot["template_courses"])
            self.legacy = snapshot["legacy"]
            self.golden_facts = list(snapshot["golden_facts"])
            self.harvest_schools = ()
            self.harvest_text_roots = []
            self.source_counts = {
                "local_courses": len(local_courses), "harvest_courses": 0,
                "local_facts": len(local_facts), "harvest_facts": 0,
            }
            self._course_cache.clear()
            self._major_catalog = None
            return
        bundle = load_harvest_bundle(self.settings.project_root, harvest_schools)
        harvested_courses = [self._course_from_harvest(row) for row in bundle["courses"]]
        harvested_facts = [self._fact_from_harvest(row) for row in bundle["facts"]]
        self.harvest_schools = tuple(bundle["schools"])
        self.harvest_text_roots = [Path(p) for p in bundle["text_roots"]]
        self.source_counts = {
            "local_courses": len(local_courses), "harvest_courses": len(harvested_courses),
            "local_facts": len(local_facts), "harvest_facts": len(harvested_facts),
        }
        if mode == "plugin":
            # 目标院校/专业的数据完全来自插件收割，不掺本地库
            self.courses = harvested_courses
            self.facts = harvested_facts
            self.template_courses = []
            self.legacy = None
            self.golden_facts = []
        else:
            self.courses = harvested_courses + local_courses
            self.facts = harvested_facts + local_facts
            self.template_courses = list(snapshot["template_courses"])
            self.legacy = snapshot["legacy"]
            self.golden_facts = list(snapshot["golden_facts"])
        self._course_cache.clear()
        self._major_catalog = None

    @staticmethod
    def _course_from_harvest(row: dict[str, Any]) -> CourseRecord:
        return CourseRecord(
            course_id=str(row.get("course_id")),
            school=str(row.get("school") or "未识别"),
            year=row.get("year"),
            major=row.get("major"),
            name=str(row.get("name")),
            category=str(row.get("category") or "理论"),
            credits=row.get("credits"),
            practice_hours=row.get("practice_hours"),
            is_practice=bool(row.get("is_practice")),
            description=str(row.get("description") or ""),
            source_document=str(row.get("source_document") or ""),
            evidence_level=str(row.get("evidence_level") or "A"),
            family=row.get("family"),
            is_required=row.get("is_required"),
        )

    @staticmethod
    def _fact_from_harvest(row: dict[str, Any]) -> EducationFact:
        major = str(row.get("major") or "").strip() or None
        return EducationFact(
            fact_id=str(row.get("fact_id")),
            family=str(row.get("family") or (major_family(major) if major else "school") or "school"),
            year=row.get("year"),
            school=str(row.get("school") or ""),
            major=major,
            section=str(row.get("section") or "harvested_quality_report"),
            fact_type=str(row.get("fact_type")),
            value=row.get("value"),
            unit=str(row.get("unit") or "ratio"),
            raw_text=str(row.get("raw_text") or ""),
            source_document=str(row.get("source_document") or ""),
            source_line=int(row.get("source_line") or row.get("page") or 0),
            upstream_source=str(row.get("upstream_source") or "edu-material-harvest 收割"),
            evidence_level=str(row.get("evidence_level") or "A"),
            confidence=float(row.get("confidence") or 0.85),
        )

    def text_roots(self) -> list[Path]:
        """当前模式下可检索的正文缓存根目录（plugin 模式不含本地库正文）。"""
        roots: list[Path] = []
        if self.source_mode != "plugin":
            roots.append(self.settings.project_root / "data" / "raw" / "pdf_text")
        roots.extend(self.harvest_text_roots)
        return [root for root in roots if root.exists()]

    def source_summary(self) -> dict[str, Any]:
        return {"mode": self.source_mode, "harvest_schools": list(self.harvest_schools),
                **self.source_counts}

    def _legacy_courses(self) -> list[CourseRecord]:
        return self._legacy_course_records()

    def _tag_course_families(self) -> None:
        """Derive each course's major family from the curated file it came from.

        Without this tag the course pool mixes AI / CS / 经济管理 courses, so a
        软件工程 analysis would be scored against AI-major courses. That is the
        same scope substitution the supply/demand separation is meant to stop.
        """
        for course in self.courses:
            course.family = course_family_of(course.source_document)

    def _load_supplementary_courses(self) -> None:
        """把《数据整理与补采》导入的课程库合并进课程池（A 级、带学分/实践/必修）。

        默认只取每个（院校, 专业）**最新年份**的培养方案，避免把 2021/2022/2024/2025
        四个年级的培养方案当成四门课程叠加；旧年份仍保留在 JSON 中可供趋势使用。
        解析结果前置，使同名课程优先采用 A 级培养方案记录（带学分）而不是策展文本。
        """
        path = self.settings.project_root / "data" / "raw" / "supplementary_courses.json"
        if not path.exists():
            return
        try:
            rows = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return
        policy = str((self.settings.raw.get("core_model") or {}).get(
            "supplementary_course_policy", "latest_year"))
        selected = rows
        if policy == "latest_year":
            latest: dict[tuple[str, str], int] = {}
            for row in rows:
                key = (str(row.get("school")), str(row.get("major")))
                year = row.get("year") or 0
                latest[key] = max(latest.get(key, 0), year)
            selected = [r for r in rows
                        if (r.get("year") or 0) == latest.get((str(r.get("school")), str(r.get("major"))), 0)]
        courses: list[CourseRecord] = []
        for row in selected:
            courses.append(CourseRecord(
                course_id=str(row.get("course_id")),
                school=str(row.get("school") or "未识别"),
                year=row.get("year"),
                major=row.get("major"),
                name=str(row.get("name")),
                category=str(row.get("category") or "理论"),
                credits=row.get("credits"),
                practice_hours=row.get("practice_hours"),
                is_practice=bool(row.get("is_practice")),
                description=str(row.get("description") or ""),
                source_document=str(row.get("source_document") or ""),
                evidence_level=str(row.get("evidence_level") or "A"),
                family=row.get("family"),
                is_required=row.get("is_required"),
            ))
        self.courses = courses + self.courses

    def _load_pdf_facts(self) -> None:
        """Merge A-level facts parsed from the archived official PDF reports.

        These are primary sources; the curated docx台账 stays as a D-level
        cross-check. ``latest_facts`` prefers the higher evidence level.
        """
        path = self.settings.processed_dir / "pdf_facts.json"
        if not path.exists():
            return
        try:
            rows = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return
        converted: list[EducationFact] = []
        family_of_type = {
            # 归档 PDF 报告的数值多为"全校/全校分学历"口径，不区分专业，
            # 因此统一标记为 family="school"，消费方必须显式声明是否接受校级口径。
            "placement_rate": "school", "employment_rate": "school", "signing_rate": "school",
            "further_study_rate": "school", "domestic_study_rate": "school",
            "overseas_study_rate": "school", "employer_satisfaction": "school",
            "graduates_total": "school", "graduates_level": "school",
            "beijing_employment_ratio": "school",
            # 教学质量报告类指标：师资/条件/课程结构，报告多为校级口径
            "faculty_total": "school", "senior_title_count": "school",
            "senior_title_ratio": "school", "student_faculty_ratio": "school",
            "dual_teacher_count": "school", "industry_teacher_count": "school",
            "training_base_count": "school", "total_hours": "school",
            "practice_credit": "school", "lab_credit": "school",
            "practice_credit_ratio": "school", "lab_credit_ratio": "school",
            "required_course_ratio": "school", "elective_course_ratio": "school",
            "physical_test_pass_rate": "school",
        }
        for row in rows:
            converted.append(EducationFact(
                fact_id=row["fact_id"],
                family=family_of_type.get(row["fact_type"], "cs"),
                year=row.get("year"),
                school=row.get("school") or "",
                major=None,
                section="employment_quality_report_pdf",
                fact_type=row["fact_type"],
                value=row.get("value"),
                unit=row.get("unit", "ratio"),
                raw_text=row.get("raw_text", ""),
                source_document=row.get("source_document", ""),
                source_line=int(row.get("page") or 0),
                upstream_source=f"PDF p{row.get('page')}",
                evidence_level=row.get("evidence_level", "A"),
                confidence=float(row.get("confidence", 0.9)),
            ))
        self.facts.extend(converted)
        self.pdf_facts_count = len(converted)

    def _load_pdf_major_rows(self) -> None:
        """Load per-major rows extracted from the reports (primary major-level data).

        Family is inferred from the major name so that a query about 人工智能 uses
        only AI-major rows, not the school aggregate.
        """
        path = self.settings.processed_dir / "pdf_major_rows.json"
        if not path.exists():
            return
        try:
            rows = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return
        converted: list[EducationFact] = []
        for row in rows:
            major = str(row.get("major") or "").strip()
            school = str(row.get("school") or "")
            # 就业报告的分专业行覆盖 297 个专业，**不再按三个专业族丢弃**：
            # 非三族专业统一标 family="major"，供 latest_facts_by_major 定点检索，
            # 且不会被当成校级口径（family="school"）混进其它查询。
            if not major or major == school or major.endswith(("大学", "学院", "学部")):
                continue
            family = major_family(major) or "major"
            base = {
                "family": family,
                "year": row.get("year"),
                "school": school,
                "major": major,
                "section": "employment_quality_report_major_table",
                "source_document": row.get("source_document", ""),
                "source_line": int(row.get("page") or 0),
                "upstream_source": f"报告分专业表（{row.get('layout')}）",
                "evidence_level": "A",
                "confidence": float(row.get("confidence", 0.85)),
            }
            for fact_type, value in (
                ("graduates", row.get("graduates")),
                ("further_study_rate", row.get("further_study_rate")),
                ("signing_rate", row.get("signing_rate")),
                ("placement_rate", row.get("placement_rate")),
            ):
                if value is None:
                    continue
                converted.append(EducationFact(
                    fact_id=f"pmaj:{row.get('school')}:{row.get('year')}:{major}:{fact_type}",
                    fact_type=fact_type,
                    value=float(value),
                    unit="人" if fact_type == "graduates" else "ratio",
                    raw_text=row.get("raw_text", ""),
                    **base,
                ))
        self.facts.extend(converted)
        self.major_rows_count = len(converted)

    def _legacy_course_records(self) -> list[CourseRecord]:
        settings = self.settings
        record_dir = settings.archive_dir / "输出过程记录"
        path = record_dir / "教学.txt"
        if not path.exists():
            return []
        try:
            payload = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        except Exception:  # noqa: BLE001
            return []
        texts: list[tuple[str, str, int | None, str]] = []
        for item in (payload.get("_input") or {}).get("input") or []:
            output = str(item.get("output") or "")
            school = output.splitlines()[0].strip() if output else ""
            source = f"AI竞赛数据归档/输出过程记录/教学.txt#{item.get('documentId')}"
            for line in output.splitlines():
                texts.append((line, school, 2024, source))
        return extract_courses_from_texts(texts)

    # ---------- queries ----------
    def fact_series(self, family: str, fact_type: str, school: str | None = None) -> list[tuple[int, float]]:
        out = []
        for f in self.facts:
            if f.fact_type != fact_type or f.value is None or f.year is None:
                continue
            if f.family != family:
                continue
            if school and f.school != school:
                continue
            out.append((f.year, f.value))
        return out

    def benchmark(self, family: str, fact_type: str, *, min_n: int = 3) -> dict[str, Any]:
        vals = [v for _, v in self.fact_series(family, fact_type)]
        if len(vals) < min_n:
            return {"value": None, "n": len(vals), "status": "insufficient_evidence"}
        return {"value": round(median(vals), 4), "n": len(vals), "status": "ok",
                "min": min(vals), "max": max(vals), "statistic": "median"}

    def schools(self, family: str | None = None) -> list[str]:
        names = {f.school for f in self.facts if f.school and (family is None or f.family == family)}
        return sorted(names)

    def school_text(self, school: str | None, *, category: str = "教学质量报告",
                    categories: tuple[str, ...] | None = None,
                    max_chars: int = 200_000) -> str:
        """Concatenated report text for one school (used by rule-based signals).

        Reads the cached page-separated text, so no PDF parsing is involved.
        ``categories`` overrides ``category``；默认同时纳入教学质量报告与培养方案，
        这样补采的培养方案正文也能为"培养目标/课程体系"类语义指标提供证据。
        """
        # 默认纳入：教学质量报告 + 培养方案 + 课程大纲 + 专业介绍（均为随包可检索文本）
        wanted = tuple(categories) if categories else (
            category, "培养方案", "课程大纲", "专业介绍", "年度报告", "就业质量报告")
        roots = self.text_roots()
        if not roots:
            return ""
        matches: list[Path] = []
        for root in roots:
            for path in sorted(root.rglob("*.txt")):
                if not any(name in str(path) for name in wanted):
                    continue
                if school and school not in str(path):
                    continue
                matches.append(path)
        if school is None:
            matches = matches[:40]
        chunks: list[str] = []
        used = 0
        for path in matches:
            text = path.read_text(encoding="utf-8", errors="replace")
            chunks.append(text)
            used += len(text)
            if used >= max_chars:
                break
        return "\n".join(chunks)[:max_chars]

    def major_coverage(self, family: str | None) -> dict[str, Any]:
        """What data exists for a given major family? Used for honest reporting."""
        # "school" 是校级口径的存储桶，不是一个可分析的专业族
        families = sorted({f.family for f in self.facts if f.family != "school"})
        if not family or family not in families:
            return {
                "family": family,
                "available": False,
                "known_families": families,
                "curated_files": self.available_families,
                "school_level_facts_available": any(f.family == "school" for f in self.facts),
                "how_to_add": (
                    "把该专业的整理文本放到 data/raw/majors_<family>.txt（可用 "
                    "scripts/archive_extract_text.py 从 docx 抽取），再运行 "
                    "python scripts/build_database.py。"
                ),
            }
        facts = [f for f in self.facts if f.family == family]
        jobs = self.target_jobs()
        keyword = FAMILY_MAJOR.get(family, family)
        matching_jobs = [
            j for j in jobs
            if keyword in (j.get("position") or "") or keyword in (j.get("job_description") or "")
            or family in (j.get("search_keyword") or "")
        ]
        return {
            "family": family,
            "available": True,
            "n_facts": len(facts),
            "facts_by_type": dict(Counter(f.fact_type for f in facts).most_common()),
            "schools": len({f.school for f in facts if f.school}),
            "years": sorted({f.year for f in facts if f.year}),
            "evidence_levels": dict(Counter(f.evidence_level for f in facts)),
            "curated_file": self.available_families.get(family),
            "n_courses": len({c.name for c in self.courses}),
            "n_jobs_matching": len(matching_jobs),
            "school_level_facts_available": any(f.family == "school" for f in self.facts),
            "computable_dimensions": _computable_dimensions(facts),
        }
    def years(self, family: str | None = None) -> list[int]:
        return sorted({f.year for f in self.facts if f.year and (family is None or f.family == family)})

    def latest_facts(
        self, family: str, school: str | None, fact_type: str, *,
        major_preferred: str | None = None, include_school_level: bool = False,
    ) -> dict[str, Any]:
        def applies(fact) -> bool:
            if fact.family == family:
                return True
            # 校级口径的官方 PDF 数值只在调用方明确接受时才参与
            return include_school_level and fact.family == "school"

        candidates = [
            f for f in self.facts
            if applies(f) and f.fact_type == fact_type and f.value is not None
            and (school is None or f.school == school)
        ]
        if not candidates:
            return {"value": None, "status": "insufficient_evidence", "n": 0}
        if major_preferred:
            focused = [f for f in candidates if f.major and major_preferred in f.major]
            if focused:
                candidates = focused
        # 同一（学校,年份,指标）可能同时来自官方 PDF（A）与策展台账（D）：
        # 先取最新年份，再在同年份内优先采用证据等级更高的一条。
        rank = {"A": 0, "B": 1, "C": 2, "D": 3, "E": 4}
        latest_year = max(f.year or 0 for f in candidates)
        same_year = [f for f in candidates if (f.year or 0) == latest_year]
        best_rank = min(rank.get(f.evidence_level, 9) for f in same_year)
        chosen = [f for f in same_year if rank.get(f.evidence_level, 9) == best_rank]
        values = [f.value for f in chosen]
        use_mean = len(values) > 1 and len({f.major for f in chosen}) > 1
        value = round(sum(values) / len(values), 4) if use_mean else round(float(values[0]), 4)
        return {
            "value": value,
            "status": "ok",
            "n": len(chosen),
            "year": latest_year,
            "aggregation": "mean_of_majors" if use_mean else "single_observation",
            "school": chosen[0].school,
            "majors": sorted({c.major for c in chosen if c.major}),
            "facts": [c.fact_id for c in chosen],
            "raw": [c.raw_text for c in chosen],
            "source_document": chosen[0].source_document,
            "upstream_source": chosen[0].upstream_source,
            "evidence_level": chosen[0].evidence_level,
            "page": chosen[0].source_line if chosen[0].section.endswith("_pdf") else None,
            "pdf_backed": chosen[0].section.endswith("_pdf"),
            "scope": "major_level" if chosen[0].family == family else "school_level",
        }

    def latest_facts_by_major(
        self, major: str, school: str | None, fact_type: str, *,
        include_school_level: bool = False,
    ) -> dict[str, Any]:
        """按**专业名**取事实（不限三个专业族），用于任意专业的就业/教学口径。

        事实里的 `major` 字段来自就业质量报告的分专业行，覆盖 1,400+ 个专业；
        没有任何匹配时返回 `insufficient_evidence`，绝不回退到别的专业。
        """
        name = str(major or "")
        if not name:
            return {"value": None, "status": "insufficient_evidence", "n": 0}
        candidates = [
            f for f in self.facts
            if f.fact_type == fact_type and f.value is not None
            and f.major and (name in f.major or f.major in name)
            and (school is None or f.school == school)
        ]
        if not candidates and include_school_level:
            candidates = [
                f for f in self.facts
                if f.fact_type == fact_type and f.value is not None and f.family == "school"
                and (school is None or f.school == school)
            ]
        if not candidates:
            return {"value": None, "status": "insufficient_evidence", "n": 0}
        rank = {"A": 0, "B": 1, "C": 2, "D": 3, "E": 4}
        latest_year = max(f.year or 0 for f in candidates)
        same_year = [f for f in candidates if (f.year or 0) == latest_year]
        best_rank = min(rank.get(f.evidence_level, 9) for f in same_year)
        chosen = [f for f in same_year if rank.get(f.evidence_level, 9) == best_rank]
        values = [f.value for f in chosen]
        return {
            "value": round(sum(values) / len(values), 4),
            "status": "ok", "n": len(chosen), "year": latest_year,
            "school": chosen[0].school, "major": chosen[0].major,
            "source_document": chosen[0].source_document,
            "evidence_level": chosen[0].evidence_level,
            "raw": [c.raw_text for c in chosen],
            "scope": "major_level_by_name",
        }

    def policy_relevance(self, skills: list[str]) -> dict[str, float]:
        if not self.policies or not skills:
            return {}
        counts = {s: 0 for s in skills}
        for policy in self.policies:
            related = set(policy.skills_related or [])
            for s in skills:
                if s in related:
                    counts[s] += 1
        top = max(counts.values()) if counts else 0
        return {s: round(c / top, 4) for s, c in counts.items()} if top else {}

    def industry_weight(self, skills: list[str]) -> dict[str, float]:
        if not self.ontology:
            return {}
        weights = {s: 0.0 for s in skills}
        for direction in self.ontology.industry_directions.values():
            related = direction.get("related_skills") or []
            for s in skills:
                if any(r in s or s in r for r in related):
                    weights[s] = max(weights[s], 1.0)
        return weights

    def demand_vector(
        self,
        *,
        family: str | None = None,
        major: str | None = None,
        emerging_skills: list[str] | None = None,
    ) -> list[SkillDemand]:
        """Demand vector: real job postings when available, else aggregated evidence.

        ``major`` 支持任意专业（不限于三个专业族）：检索词按"人工词表 → 词干表 → 专业名"
        三级推导（见 ``edumatch/majors.py``），并用覆盖率闸门判断语料是否真的覆盖该专业。
        """
        self.demand_scope_note = ""
        self.demand_coverage = {}
        label = major or family or "目标专业"
        # 检索词：任意专业走 keywords 推导；只有族时才退回族关键词表。
        spec: dict[str, Any] | None = None
        # 三族专业沿用族关键词表（业界验证过的检索词，覆盖面更准）；
        # 通用专业才按专业名/词干/课程词推导检索词。
        if major and not family:
            from . import majors as majors_mod

            curated: dict[str, list[str]] = {}
            curated_path = self.settings.project_root / "data" / "raw" / "major_keywords.json"
            if curated_path.exists():
                try:
                    curated = json.loads(curated_path.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    curated = {}
            spec = majors_mod.job_keywords(major, curated=curated)
            self.demand_keyword_source = spec
        keywords = list(spec["keywords"]) if spec else (
            list(FAMILY_JOB_KEYWORDS.get(family, [])) if family else [])
        if spec is None and family:
            self.demand_keyword_source = {"keywords": keywords, "source": "family_map",
                                          "major": major, "family": family}

        if self.jobs:
            from .jobs.demand import demand_from_jobs

            # 专业作用域语料优先：按专业导出的岗位表直接决定"这个专业的市场需要什么"，
            # 不再依赖关键词在 JD 文本里恰好出现（那正是非 AI/CS 专业被误判"语料不覆盖"的原因）。
            # 通用语料已覆盖的专业族（AI/计算机）**优先用通用语料**：
            # 它是按关键词检索的全量岗位，比"按专业导出的几百条"更全。
            # 专业作用域语料只在该族不被通用语料覆盖时（经济管理/工科/文科…）才启用。
            family = major_family(str(major or ""))
            scoped = (self.major_scope_jobs(major)
                      if major and family not in ("ai", "cs") else [])
            if scoped:
                skills = sorted({s for job in scoped for s in (job.get("skills") or [])})
                self.demand_coverage = {
                    "label": label, "n_jobs": len(scoped), "n_matched": len(scoped),
                    "share": 1.0, "keywords": keywords,
                    "keyword_source": "major_export",
                    "threshold": DEMAND_FAMILY_MIN_SHARE,
                }
                self.demand_scope_note = (
                    f"需求侧使用「{label}」的按专业导出语料 {len(scoped)} 条"
                    "（专业作用域，非关键词碰巧命中）。"
                )
                return demand_from_jobs(
                    scoped,
                    extract_skills=self._skills_from_text,
                    policy_relevance=self.policy_relevance(skills),
                    industry_weight=self.industry_weight(skills),
                    evidence_level="C",
                )

            rows = self.target_jobs()
            matched = rows
            if keywords:
                matched = [
                    job for job in rows
                    if any(k in f"{job.get('position') or ''}{job.get('job_description') or ''}"
                           for k in keywords)
                ]
                share = len(matched) / len(rows) if rows else 0.0
                self.demand_coverage = {
                    "label": label, "n_jobs": len(rows), "n_matched": len(matched),
                    "share": round(share, 4), "keywords": keywords,
                    "keyword_source": (spec or {}).get("source", "family_map"),
                    "threshold": DEMAND_FAMILY_MIN_SHARE,
                }
                if share < DEMAND_FAMILY_MIN_SHARE:
                    # 兜底：该专业既不在 AI/CS 目标语料覆盖内，也不在那 68 个专业作用域里
                    # （如「信息管理与信息系统」）时，用**本地全量招聘语料**按专业关键词切片，
                    # 规则固定、命中率与关键词全部披露，绝不与其他专业混用。
                    fallback = self._full_corpus_demand(major, keywords, label)
                    if fallback is not None:
                        return fallback
                    self.demand_scope_note = (
                        f"岗位语料中仅 {share:.1%} 的岗位匹配「{label}」相关关键词"
                        f"（阈值 {DEMAND_FAMILY_MIN_SHARE:.0%}；检索词来源 "
                        f"{(spec or {}).get('source', '族关键词表')}），"
                        "不能代表该专业的市场需求，需求侧记 insufficient_evidence。"
                    )
                    return []
            if not matched:
                self.demand_scope_note = (
                    f"岗位语料中没有匹配「{label}」的岗位，需求侧记 insufficient_evidence，"
                    "不挪用其他专业的需求向量。"
                )
                return []
            skills = sorted({s for job in matched for s in (job.get("skills") or [])})
            return demand_from_jobs(
                matched,
                extract_skills=self._skills_from_text,
                policy_relevance=self.policy_relevance(skills),
                industry_weight=self.industry_weight(skills),
                evidence_level="C",
            )
        # 无逐条岗位数据：归档聚合证据只覆盖人工智能族
        if family and family != "ai":
            self.demand_scope_note = (
                f"归档聚合招聘证据只覆盖人工智能族，不能用于「{label}」；"
                "请按该专业关键词导出 HAR 后重新导入。"
            )
            return []
        if major:
            self.demand_scope_note = f"没有「{label}」的岗位语料，需求侧记 insufficient_evidence。"
            return []
        skills = list((self.market_evidence.get("skill_frequency_tiers") or {}).keys())
        return demand_from_aggregate(
            self.market_evidence,
            policy_relevance=self.policy_relevance(skills),
            industry_weight=self.industry_weight(skills),
        )

    # ---------- 任意专业支持 ----------
    def major_catalog(self) -> dict[str, Any]:
        """专业目录：从课程库（培养方案）与就业分专业行自动发现，**不依赖硬编码族**。"""
        if self._major_catalog is None:
            from . import majors as majors_mod

            employment = [str(f.major) for f in self.facts if f.major]
            rows = []
            try:
                path = self.settings.processed_dir / "pdf_major_rows.json"
                if path.exists():
                    rows = json.loads(path.read_text(encoding="utf-8"))
                    employment += [str(r.get("major") or "") for r in rows]
            except (json.JSONDecodeError, OSError):
                pass
            self._major_catalog = majors_mod.build_catalog(
                courses=self.courses, employment_majors=employment,
                family_of=major_family,
                exclude_schools=self.schools(),
            )
        return self._major_catalog

    def find_major(self, query: str):
        """在问题文本中匹配专业目录；返回 (major_key, MajorRef) 或 None。"""
        from . import majors as majors_mod

        ref = majors_mod.match_major(query, self.major_catalog())
        return (ref.key, ref) if ref else None

    def demand_corpus_profile(self) -> dict[str, Any]:
        """Which major family the current job corpus actually covers.

        The corpus is collected with one keyword set (here: 人工智能). Measuring
        each family's keyword coverage lets the engine refuse to reuse an AI
        posting corpus as 经济管理 demand instead of silently substituting it.
        """
        return self._demand_corpus_profile()

    def occupation_slice(self, occupation: str | None) -> dict[str, Any]:
        """目标岗位族对应的岗位切片（语料为空时如实返回证据不足）。"""
        slice_info = occupation_mod.slice_jobs(self.target_jobs(), occupation)
        occ = slice_info.get("occupation")
        return {
            **{k: v for k, v in slice_info.items() if k != "rows"},
            "occupation_id": getattr(occ, "id", None),
            "occupation_name": getattr(occ, "name", None),
            "rows": slice_info.get("rows") or [],
        }

    def occupation_demand(self, occupation: str | None,
                          major: str | None = None) -> tuple[list[SkillDemand], dict[str, Any]]:
        """目标岗位族的需求向量：只由该岗位族的岗位计算。"""
        info = self.occupation_slice(occupation)
        rows = info.pop("rows")
        if info.get("status") != "ok" or not rows:
            # 岗位族未登记（会计/结构工程师/护士…）时**不放弃**：用岗位名在全量招聘表里直搜。
            # 岗位族只是"一组人工检索词 + 典型技能"，不是分析的前提。
            fallback = self._occupation_title_search(occupation or "", major=major)
            info = {**info, **{k: v for k, v in fallback.items() if k != "rows"}}
            rows = fallback.get("rows") or []
            if not rows:
                info["demand"] = []
                info["demand_note"] = (fallback.get("reason") or info.get("reason")
                                       or "目标岗位样本不足")
                return [], info
        from .jobs.demand import demand_from_jobs

        skills = sorted({s for job in rows for s in (job.get("skills") or [])})
        demands = demand_from_jobs(
            rows,
            extract_skills=self._skills_from_text,
            policy_relevance=self.policy_relevance(skills),
            industry_weight=self.industry_weight(skills),
            evidence_level="C",
        )
        education: dict[str, int] = {}
        for job in rows:
            key = str(job.get("education") or "未知")
            education[key] = education.get(key, 0) + 1
        salary_stats = summarize_salaries(rows)
        info["demand"] = demands
        info["n_demand_skills"] = len(demands)
        if info.get("resolved_by") == "title_search":
            info["demand_note"] = (
                f"岗位族未登记「{occupation}」，改用**岗位名在全量招聘表直搜**"
                f"（检索词 {'、'.join(info.get('matched_terms') or [])[:60]}，"
                f"命中 {info.get('n_jobs')} 条，口径 {info.get('match_scope')}）；"
                "未使用其他岗位族的数据。"
            )
        else:
            info["demand_note"] = "目标岗位族岗位需求向量（未使用其他岗位族数据）"
        info["requirements"] = {
            "education_distribution": dict(sorted(education.items(), key=lambda kv: -kv[1])[:6]),
            **salary_stats,
        }
        return demands, info

    def _occupation_title_search(self, occupation: str,
                                 major: str | None = None) -> dict[str, Any]:
        """不依赖岗位族：用岗位名（含去后缀变体）在**全量招聘表**里直搜对口岗位。

        检索范围＝**通用语料 + 该专业的专业作用域语料**（后者按专业惰性加载），
        这才是"把招聘数据文件夹下的各张表都用上"。

        为什么需要：`edumatch/occupation.py` 只登记了 10 个 AI/计算机方向的岗位族，
        会计/财务/机械/土木/护理等岗位一律解析失败 → 岗位级 Match 直接不可算，
        而本地招聘表里这类岗位其实有几千条（实测会计/财务 4,071 条）。
        这里按「原词 + 去后缀变体」在 position 上检索，不足门槛再放宽到职责文本，
        口径与用到的检索词全部写进 `info`，报告据此披露。
        """
        from . import occupation as occupation_mod

        min_jobs = occupation_mod.MIN_OCCUPATION_JOBS
        raw = str(occupation or "").strip()
        terms = [t.lower() for t in occupation_mod.title_variants(raw) if t]
        # 模糊/大类岗位扩展：「AI产品经理」→ 再试「产品经理」；「数据分析/算法」→ 拆成两词。
        for extra in re.split(r"[、,，/|\s]+", raw):
            extra = extra.strip()
            if len(extra) >= 2 and extra.lower() not in terms:
                terms.append(extra.lower())
            # 注意：**不要**再做"取末尾 N 字"这类启发式——"航天器总体设计"会被截成
            # "总体设计"，匹配到一堆无关岗位，等于编造需求。大类岗位（技术岗/管理岗）
            # 由 title_variants 去后缀处理，已经覆盖。
        if not terms:
            return {"status": "unresolved", "rows": [], "n_jobs": 0,
                    "reason": "目标岗位为空"}

        pool = list(self.jobs)
        if major:
            pool += self.major_export_for(major)

        def scan(fields: tuple[str, ...], use_terms: list[str]) -> list[dict[str, Any]]:
            out: list[dict[str, Any]] = []
            for job in pool:
                text = " ".join(str(job.get(f) or "") for f in fields)
                lowered = text.lower()
                if any(term in lowered for term in use_terms):
                    out.append(job)
            return out

        # 级联顺序＝证据强度：先本岗位名 → 再用数据自带的人工映射列（岗位-映射后/岗位类型-映射后）
        # → 用**子词**在岗位名/映射列上放宽（"大类岗位"场景）→ 最后才连岗位职责整词匹配。
        # 每条记录里都写清用了哪些词、哪个口径。
        matched: list[dict[str, Any]] = []
        scope, used_terms = "", terms
        stages = (
            ("position", ("position",), terms),
            ("position_mapped", ("position_mapped", "position_type"), terms),
            # 子词放宽只允许落在"岗位名/映射列"——落到职责里会把"总体设计"这类词
            # 匹配到一堆无关 AI 岗位，等于编造需求（实测踩过）。
            ("position", ("position", "position_mapped", "position_type"), terms[1:] or terms),
        )
        for scope_name, fields, use_terms in stages:
            hit = scan(fields, use_terms)
            if len(hit) > len(matched):
                matched, scope, used_terms = hit, scope_name, use_terms
            if len(matched) >= min_jobs:
                break
        if len(matched) < min_jobs:
            # 最后才允许看岗位职责，但必须**整词**命中且样本量足够大，避免宽词误伤。
            hit = scan(("position", "job_description"), terms)
            if len(hit) >= min_jobs * 3:
                matched, scope, used_terms = hit, "position+description", terms
        if len(matched) < min_jobs:
            return {
                "status": "insufficient_evidence", "rows": [], "n_jobs": len(matched),
                "reason": (f"招聘语料（通用 {len(self.jobs):,} 条"
                           + (f" + 本专业 {len(pool) - len(self.jobs):,} 条" if major else "")
                           + f"）里按「{occupation}」"
                           f"（检索词 {'、'.join(terms[:4])}）只检索到 {len(matched)} 条岗位，"
                           f"低于 {min_jobs} 条门槛，"
                           "不输出岗位匹配结论"),
            }
        skills = sorted({s for job in matched for s in (job.get("skills") or [])})
        return {
            "status": "ok", "rows": matched, "n_jobs": len(matched),
            "occupation_id": "title_search",
            "occupation_name": f"{occupation}（岗位名直搜）",
            "match_scope": scope,
            "keywords": list(used_terms),
            "typical_skills": skills[:20],
            "matched_terms": list(used_terms),
            "generalized": scope != "position",
            "resolved_by": "title_search",
            "search_pool": {"general": len(self.jobs),
                            "major_scoped": len(pool) - len(self.jobs)},
            "reason": "",
        }

    def _demand_corpus_profile(self) -> dict[str, Any]:
        """Which major family the current job corpus actually covers.

        The corpus is collected with one keyword set (here: 人工智能). Measuring
        each family's keyword coverage lets the engine refuse to reuse an AI
        posting corpus as 经济管理 demand instead of silently substituting it.
        """
        if not self.jobs:
            return {"status": "no_raw_jobs", "n_jobs": 0, "corpus_family": None,
                    "family_match_share": {}}
        rows = self.target_jobs()
        total = len(rows)
        if not total:
            return {"status": "insufficient_evidence", "n_jobs": 0, "corpus_family": None,
                    "family_match_share": {}}
        shares: dict[str, float] = {}
        for family, keywords in FAMILY_JOB_KEYWORDS.items():
            hits = 0
            for job in rows:
                text = f"{job.get('position') or ''}{job.get('job_description') or ''}"
                if any(k in text for k in keywords):
                    hits += 1
            shares[family] = round(hits / total, 4)
        dominant = max(shares, key=lambda k: shares[k]) if shares else None
        return {
            "status": "ok",
            "n_jobs": total,
            "corpus_family": dominant,
            "family_match_share": shares,
            "note": (
                "语料主轴=" + str(dominant) + "；某专业族关键词覆盖率低于 "
                f"{DEMAND_FAMILY_MIN_SHARE:.0%} 时该族需求记 insufficient_evidence。"
            ),
        }

    # ---------- job-market helpers ----------
    def _skills_of_job(self, job: dict[str, Any]) -> list[str]:
        """Skills for one posting: cached from import, else extracted on the fly."""
        cached = job.get("skills")
        if cached:
            return list(cached)
        return self._skills_from_text(
            " ".join(str(job.get(k) or "") for k in ("position", "job_description"))
        )

    def _skills_from_text(self, text: str) -> list[str]:
        """技能抽取：**所有专业走同一条路**——用当前专业的数据驱动词表匹配文本。

        词表由 ``ResearchEngine._build_skill_vocabulary`` 用「岗位术语 ∪ 课程候选 ∪
        本体种子」构建，供需两侧共用同一套词表与同一函数，不存在"本体专业/通用专业"
        的分级。没有词表时回退到本体匹配（仅用于词表构建失败的极端情况）。
        """
        haystack = str(text)
        if self.vocabulary_mode == "data_driven" and self.major_vocabulary:
            return sorted({term for term in self.major_vocabulary if term in haystack})
        names: list[str] = []
        if self.ontology:
            for mention in self.ontology.extract(haystack):
                skill = self.ontology.get(mention.skill_id)
                if skill:
                    names.append(skill.name)
        return sorted(set(names))

    def target_jobs(self) -> list[dict[str, Any]]:
        """Jobs from keyword searches (the demand-relevant set)."""
        return [j for j in self.jobs
                if (j.get("search_keyword") or "").strip()
                and j.get("corpus") != "major_export"]

    def _full_corpus_demand(self, major: str | None, keywords: list[str],
                            label: str) -> list[Any] | None:
        """本地全量语料兜底：按专业关键词切片后建需求向量（不达标返回 None）。"""
        if not major or not keywords:
            return None
        try:
            from . import majors as majors_mod
            from .major_demand import major_scoped_demand
            from .jobs.demand import demand_from_jobs

            # 用**专业自己**的检索词（词干表/专业名），而不是家族词表——
            # 家族词表（如 econ 的会计/金融）对"信息管理与信息系统"这类专业命中率极低，
            # 会把这个兜底也一起卡掉。
            spec = majors_mod.job_keywords(major) or {}
            kws = list(spec.get("keywords") or []) or list(keywords or [])
            scoped = major_scoped_demand(self.settings.project_root, major, kws)
            if scoped is None:
                return None
            skills = sorted({s for row in scoped.rows for s in
                             (row.get("skills") or [])})
            self.demand_coverage = {
                "label": label, "n_jobs": scoped.n_total, "n_matched": scoped.n_matched,
                "share": round(scoped.share, 4), "keywords": scoped.keywords,
                "keywords_source": spec.get("source") or "family_map",
                "keyword_source": "full_corpus_keyword_scope",
                "threshold": 0.05, "n_used": len(scoped.rows),
            }
            self.demand_scope_note = (
                f"AI/计算机目标语料不覆盖「{label}」；改用**本地全量招聘语料**"
                f"（{scoped.n_total:,} 条）按该专业关键词切片 {scoped.n_matched:,} 条"
                f"（命中率 {scoped.share:.1%}，取前 {len(scoped.rows):,} 条建模；"
                f"关键词来源 majors.job_keywords）。这是可复现的本地兜底口径，"
                "与其它专业的需求向量互不混用。")
            return demand_from_jobs(
                scoped.rows,
                extract_skills=self._skills_from_text,
                policy_relevance=self.policy_relevance(skills),
                industry_weight=self.industry_weight(skills),
                evidence_level="D",
            )
        except Exception:  # noqa: BLE001 - 兜底失败仍按证据不足处理
            return None

    def baseline_jobs(self) -> list[dict[str, Any]]:
        """同城基线岗位（薪资/占比基线）。

        优先用通用语料里"不带检索词"的行（历史 HAR 导入）；**没有时退到**
        ``data/processed/jobs_baseline_sample.json``——那是从全量招聘表（含会计/销售/
        护理等非 AI 岗位）蓄水池抽样 2 万条得到的同城市场基线，比旧的 53 条大得多。
        无论走哪条，口径都写进 ``jobs_meta``/``market.note``，不静默换口径。
        """
        rows = [j for j in self.jobs
                if not (j.get("search_keyword") or "").strip()
                and j.get("corpus") != "major_export"]
        if rows:
            return rows
        path = self.settings.processed_dir / "jobs_baseline_sample.json"
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                return []
        return []

    def major_scope_jobs(self, major: str | None) -> list[dict[str, Any]]:
        """按专业导出的"专业作用域"岗位语料（非 AI/CS 专业的需求侧来源）。

        这些行由"按专业检索导出"产生，``major_scopes`` 记录该行是为哪些专业导出的；
        与 AI/计算机语料物理隔离，只在分析对应专业时使用。

        存储是 ``data/processed/major_jobs/<专业>.json``（当前 274 个专业、25 万行），
        **按专业惰性加载**：一次分析只读该专业的切片，不把 25 万行全读进内存。
        旧布局（major_export 行直接写在 jobs.json 里）仍然兼容。
        """
        if not major:
            return []
        return self.major_export_for(major)

    def _major_jobs_dir(self) -> Path:
        return self.settings.processed_dir / "major_jobs"

    def _major_export_total(self) -> int:
        """专业作用域语料总行数：优先读按专业分文件的索引，旧布局则扫 jobs。"""
        index = self._major_jobs_dir() / "_index.json"
        if index.exists():
            try:
                return sum(int(v) for v in json.loads(index.read_text(encoding="utf-8")).values())
            except (json.JSONDecodeError, TypeError, ValueError):
                return 0
        return sum(1 for j in self.jobs if j.get("corpus") == "major_export")

    @staticmethod
    def _safe_major_name(major: str) -> str:
        return "".join(ch if ch not in '\\/:*?"<>|' else "_" for ch in str(major))

    def major_export_for(self, major: str) -> list[dict[str, Any]]:
        """取该专业的专业作用域岗位语料（惰性加载 + 进程内缓存）。"""
        cache = getattr(self, "_major_export_cache_cache", None)
        if cache is None:
            cache = {}
            self._major_export_cache_cache = cache
        safe = self._safe_major_name(major)
        if safe in cache:
            return cache[safe]
        path = self._major_jobs_dir() / f"{safe}.json"
        rows: list[dict[str, Any]] = []
        if path.exists():
            try:
                rows = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                rows = []
        if not rows:      # 兼容旧布局：profession 语料仍混在 jobs.json 里
            rows = [job for job in self.jobs if job.get("corpus") == "major_export"
                    and any(major_matches(scope, major) or major_matches(major, scope)
                            for scope in (job.get("major_scopes") or []))]
        cache[safe] = rows
        return rows

    def vocabulary_background_texts(self, *, exclude_major: str | None = None,
                                    limit: int = 2000) -> list[str]:
        """全库岗位抽样，作为"专业性提升度"的背景语料（跨专业、跨语料）。"""
        rows = [
            job for job in self.jobs
            if not exclude_major or not any(
                major_matches(scope, exclude_major) or major_matches(exclude_major, scope)
                for scope in (job.get("major_scopes") or []))
        ]
        if len(rows) <= limit:
            sample = rows
        else:
            step = len(rows) / limit
            sample = [rows[int(i * step)] for i in range(limit)]
        return [" ".join(str(j.get(k) or "") for k in ("position", "job_description"))
                for j in sample]

    @staticmethod
    def _median(values: list[float]) -> float | None:
        if not values:
            return None
        ordered = sorted(values)
        mid = len(ordered) // 2
        return ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2

    def job_statistics(self, *, emerging_skills: list[str] | None = None) -> dict[str, Any]:
        """Real market statistics derived from the imported postings."""
        emerging_skills = emerging_skills or ["大模型", "RAG", "Agent", "MLOps", "模型部署", "深度学习"]
        target, baseline = self.target_jobs(), self.baseline_jobs()
        if not target:
            return {"status": "insufficient_evidence",
                    "reason": "没有关键词检索岗位数据；请把 HAR 放入 data/raw/har/ 后运行 scripts/import_har_jobs.py"}

        target_salary_stats = summarize_salaries(target)
        baseline_salary_stats = summarize_salaries(baseline)
        target_salary = target_salary_stats["median_salary"]
        baseline_salary = baseline_salary_stats["median_salary"]
        premium = None
        if target_salary and baseline_salary:
            premium = max(0.0, round(target_salary / baseline_salary - 1, 4))
        education = {}
        for row in target:
            key = row.get("education") or "未知"
            education[key] = education.get(key, 0) + 1
        bachelor = sum(v for k, v in education.items() if k in {"本科", "学士"})
        master_plus = sum(v for k, v in education.items() if k in {"硕士", "博士", "研究生"})
        beijing = sum(1 for r in target if (r.get("city_norm") or "") == "北京")
        emerging_rows = [
            r for r in target
            if any(s in (r.get("skills") or []) for s in emerging_skills)
        ]
        counts = self.jobs_meta.get("counts") or {}
        if not counts:
            # 元信息缺失时按当前岗位表回算，保证三口径始终可披露
            counts = {
                "raw_count": len(self.jobs),
                "deduplicated_count": len(self.jobs),
                "effective_count": sum(1 for r in self.jobs
                                       if r.get("job_description") or r.get("skills")),
                "note": "由当前岗位表回算（导入元信息缺失）",
            }
        return {
            "status": "ok",
            "counts": counts,
            "raw_count": counts.get("raw_count"),
            "deduplicated_count": counts.get("deduplicated_count"),
            "effective_count": counts.get("effective_count"),
            "n_target_jobs": len(target),
            "n_baseline_jobs": len(baseline),
            "reported_total": (self.jobs_meta.get("datasets") or [{}])[0].get("reported_count"),
            "education_distribution": education,
            "bachelor_share": round(bachelor / len(target), 4),
            "master_plus_share": round(master_plus / len(target), 4),
            "target_city_share": round(beijing / len(target), 4),
            "median_salary_target": target_salary,
            "median_salary_baseline": baseline_salary,
            "salary_p25_target": target_salary_stats["p25_salary"],
            "salary_p75_target": target_salary_stats["p75_salary"],
            "salary_buckets": target_salary_stats["salary_buckets"],
            "n_salary_target": target_salary_stats["n_with_salary"],
            "n_daily_salary_excluded": target_salary_stats["n_daily_excluded"],
            "salary_premium": premium,
            "emerging_skill_share": round(len(emerging_rows) / len(target), 4),
            "emerging_skills_used": emerging_skills,
            "industries": Counter(r.get("industry") or "未知" for r in target).most_common(8),
            "publish_window": self.jobs_meta.get("publish_time_range"),
            "evidence_level": "C",
            "source": "data/processed/jobs.json（HAR 导入，平台公开岗位数据）",
        }

    def course_set(
        self, *, school: str | None = None, include_template: bool = False,
        family: str | None = None, major: str | None = None,
    ) -> list[dict[str, Any]]:
        """Course pool for one analysis scope.

        ``family`` restricts the pool to that major family (see
        :func:`course_family_of`); without it the pool mixes AI / CS / 经济管理
        courses and would score a major against other majors' curricula.
        ``major`` further restricts to courses that belong to the analysed major
        itself（培养方案里标注的专业），未标注专业来源的课程（策展文本/旧版教学）保留，
        它们不是"别的专业"的证据。
        """
        cache_key = (school, include_template, family, major)
        cached = self._course_cache.get(cache_key)
        if cached is not None:
            return cached
        out: list[dict[str, Any]] = []
        seen: set[str] = set()
        for c in self.courses:
            if family and c.family != family:
                continue
            if major and c.major and not major_matches(c.major, major):
                continue
            if school and c.school not in {school, "未识别"}:
                continue
            if c.name in seen:
                continue
            seen.add(c.name)
            out.append(
                {
                    "course_id": c.course_id,
                    "name": c.name,
                    "credits": c.credits,
                    "is_practice": c.is_practice,
                    "practice_hours": c.practice_hours,
                    "description": c.description,
                    "school": c.school,
                    "year": c.year,
                    "major": c.major,
                    "source_document": c.source_document,
                    "template": False,
                    "evidence_level": c.evidence_level,
                    "is_required": c.is_required,
                }
            )
        # 模板课程来自人工智能族的通用课程模板，只服务于 ai 族
        # 且不归属任何高校：点名院校时一律不加（E 级通用模板不能当作该校真实供给）
        if include_template and school is None and family in (None, "ai"):
            for i, c in enumerate(self.template_courses):
                if c["name"] in seen:
                    continue
                seen.add(c["name"])
                out.append({**c, "course_id": f"template:{i:03d}", "template": True, "evidence_level": "E"})
        self._course_cache[cache_key] = out
        return out

    def summary(self) -> dict[str, Any]:
        return {
            "n_documents": self._document_count(),
            "n_education_facts": len(self.facts),
            "n_pdf_facts": self.pdf_facts_count,
            "n_courses": len({c.name for c in self.courses}),
            "n_policies": len(self.policies),
            "n_policy_duplicates": len(self.policy_duplicates),
            "schools_ai": len({f.school for f in self.facts if f.family == "ai"}),
            "years": self.years(),
            "market_dataset": self.market_evidence.get("dataset_id"),
            "market_counts": (self.market_evidence.get("counts") or {}),
            # 专业作用域语料已按专业分文件存储，按索引求和（不再扫全量 jobs）
            "market_major_scoped_jobs": self._major_export_total(),
            "source_mode": self.source_mode,
            "source_counts": self.source_counts,
            "harvest_schools": list(self.harvest_schools),
        }

    def _document_count(self) -> int:
        path = self.settings.processed_dir / "archive_documents.json"
        if not path.exists():
            return 0
        try:
            return len(json.loads(path.read_text(encoding="utf-8")))
        except Exception:  # noqa: BLE001
            return 0


def _load_policy_cache(settings) -> tuple[list[PolicyRecord], list[dict[str, str]]]:
    """读 `data/processed/policies.json`（政策原文的预解析缓存）。

    只有 `data/source/政策文件/` 为空时才走到这里——公开发布包不带 147 个原文，
    用这份缓存等价替代；解析口径由 `scripts/export_policy_cache.py` 固定，可复现。
    """
    path = settings.processed_dir / "policies.json"
    if not path.exists():
        return [], []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return [], []
    known = {f.name for f in fields(PolicyRecord)}
    records = [PolicyRecord(**{k: v for k, v in row.items() if k in known})
               for row in (payload.get("records") or [])]
    return deduplicate(records)


def _computable_dimensions(facts: list[EducationFact]) -> dict[str, str]:
    """Which TSI dimensions a major family can support at all."""
    types = {f.fact_type for f in facts}
    return {
        "A_人才培养基础": "ok" if types & {"senior_title_ratio", "student_faculty_ratio",
                                          "training_base_count", "faculty_total"} else "insufficient_evidence",
        "B_人才培养过程": "ok" if types & {"practice_credit_ratio", "required_course_ratio",
                                          "total_hours"} else "insufficient_evidence",
        "C_人才培养结果": "ok" if types & {"placement_rate", "employment_rate", "signing_rate",
                                          "further_study_rate"} else "insufficient_evidence",
        "D_市场需求": "needs_job_postings",
    }


#: 专业名 → 专业族（用于把报告里的分专业行归到对应专业族）
MAJOR_NAME_TO_FAMILY: list[tuple[str, str]] = [
    # 只把真正的人工智能类专业归入 ai；智能制造/智能建造属机械与土木，
    # 误归会导致"某校人工智能"实际取到智能制造工程的数据。
    ("人工智能", "ai"), ("智能科学与技术", "ai"), ("智能感知", "ai"), ("机器学习", "ai"),
    ("计算机", "cs"), ("软件工程", "cs"), ("信息安全", "cs"), ("网络空间安全", "cs"),
    ("物联网", "cs"), ("数据科学", "cs"), ("大数据", "cs"), ("数字媒体技术", "cs"),
    ("电子信息", "cs"), ("通信工程", "cs"), ("自动化", "cs"), ("微电子", "cs"),
    ("经济", "econ"), ("金融", "econ"), ("会计", "econ"), ("财务", "econ"),
    ("工商管理", "econ"), ("管理", "econ"), ("贸易", "econ"), ("市场营销", "econ"),
]


_BRACKETS = re.compile(r"[（）()\s·\-—]")


def major_matches(course_major: str, target_major: str) -> bool:
    """课程所属专业与目标专业是否同一专业（忽略括号/空格差异）。

    例如 "计算机类（计算机科学与技术）" vs "计算机科学与技术" → True；
    "智能制造工程" vs "人工智能" → False（绝不因为都含"智能"而混用）。
    """
    left = _BRACKETS.sub("", str(course_major or ""))
    right = _BRACKETS.sub("", str(target_major or ""))
    if not left or not right:
        return False
    return left in right or right in left


def course_family_of(source_document: str) -> str | None:
    """Which major family a course record belongs to, derived from its source.

    ``majors_<family>.txt`` → that family; 旧版 ``教学.txt`` 与模板课程来自
    人工智能族的工作流 → ``ai``；其余来源无法判定 → ``None``（不得据此推断成
    其他专业族的课程）。
    """
    text = str(source_document or "").replace("/", "\\")
    for family in ("ai", "cs", "econ"):
        if f"majors_{family}" in text:
            return family
    if "教学.txt" in text or "curriculum_template_ai" in text:
        return "ai"
    return None


def major_family(major_name: str) -> str | None:
    """Map a major name found inside a report to a major family (None = not analysed)."""
    for keyword, family in MAJOR_NAME_TO_FAMILY:
        if keyword in major_name:
            return family
    return None

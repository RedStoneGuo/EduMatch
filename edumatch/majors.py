"""专业目录（Major Catalog）：把"只支持 3 个专业族"升级为"支持任意有数据的专业"。

原始设计里，专业族（ai/cs/econ）同时承担了四件事，导致新增专业必须改代码：

1. 判断"能不能分析这个专业"；2. 决定课程池；3. 决定岗位关键词；4. 决定就业事实口径。

本模块把第 1、3 项从硬编码族里解耦出来：

* **专业目录**由数据自动发现——培养方案课程库（`supplementary_courses.json`）中的专业名、
  就业报告分专业行的专业名（`pdf_major_rows.json`），两者都是官方材料，不依赖人工登记；
* **岗位关键词**按专业名与课程词表推导：先查可选的人工词表 `data/raw/major_keywords.json`，
  再退回"专业名 + 专业名词干 + 该专业课程高频词"，并记录来源，便于审计；
* 专业族（family）降级为**可选元数据**：只有 ai/cs/econ 三族有专门的本体与岗位语料，
  其它专业照样能出供给画像，需求侧若语料不覆盖则如实记 `insufficient_evidence`。

判定"能否分析某专业"的唯一标准变成：**该专业是否存在可核查数据**（课程或就业事实），
而不是它是否属于某个硬编码的族。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

#: 专业名里的通用后缀/修饰词，用于归并"机械工程（实验班）"与"机械工程"
_PAREN = re.compile(r"[（(][^）)]{0,20}[）)]")
_SPACE = re.compile(r"[\s·]")
SUFFIXES = ("专业", "方向", "大类", "实验班", "卓越工程师计划", "中外合作办学", "强基班",
            "双学士学位", "类", "班")

#: 专业名词干 → 岗位检索词。只登记"专业名本身不足以检索岗位"的情形；
#: 未登记的专业退回"专业名 + 词干"作为关键词（宁少勿多，再用覆盖率闸门兜底）。
STEM_KEYWORDS: dict[str, list[str]] = {
    "智能": ["人工智能", "智能", "大模型", "算法", "机器学习"],
    "数据": ["数据", "数据分析", "大数据", "数据工程"],
    "计算机": ["计算机", "软件开发", "后端开发", "算法"],
    "软件": ["软件", "软件开发", "测试", "运维"],
    "网络": ["网络", "网络安全", "运维", "网络优化"],
    "信息": ["信息", "信息系统", "数据", "网络"],
    "机械": ["机械", "机械设计", "机械工程", "结构设计", "机械制造"],
    "车辆": ["车辆", "汽车", "整车", "底盘", "动力总成"],
    "材料": ["材料", "金属材料", "高分子", "复合材料", "材料工程"],
    "化工": ["化工", "化学工程", "工艺", "石油化工"],
    "土木": ["土木", "结构工程", "施工", "桥梁", "岩土"],
    "建筑": ["建筑", "建筑设计", "规划设计"],
    "环境": ["环境工程", "环境科学", "环保", "水处理"],
    "能源": ["能源", "动力", "热能", "新能源", "储能"],
    "电气": ["电气", "电力", "电气工程", "供配电"],
    "电子": ["电子", "电子信息", "电路", "硬件"],
    "通信": ["通信", "无线", "网络优化", "射频"],
    "自动化": ["自动化", "控制", "PLC", "运动控制"],
    "会计": ["会计", "财务", "审计", "税务"],
    "金融": ["金融", "投资", "风控", "量化"],
    "经济": ["经济", "经济分析", "产业研究"],
    "管理": ["管理", "运营", "项目管理", "工商管理"],
    "营销": ["市场", "营销", "品牌", "销售"],
    "法学": ["法务", "律师", "合规", "法律"],
    "英语": ["英语", "翻译", "外贸", "英语教师"],
    "医学": ["临床", "医师", "药学", "护理", "医学"],
    "生物": ["生物", "生物技术", "生物工程", "实验"],
    "食品": ["食品", "食品工程", "质量检测"],
    "数学": ["数学", "统计", "数据分析", "量化"],
    "物理": ["物理", "光学", "电子", "半导体"],
    "化学": ["化学", "分析化学", "材料化学"],
    "设计": ["设计", "工业设计", "视觉设计", "产品设计"],
    "体育": ["体育", "运动", "教练", "康复"],
    "音乐": ["音乐", "作曲", "演奏", "音乐制作"],
    "新闻": ["新闻", "传媒", "编辑", "记者"],
    "教育": ["教师", "教育", "教学", "课程研发"],
}

#: 单字/虚词不单独作为关键词
STOPWORDS = {"与", "及", "和", "的", "类", "专业", "方向", "工程", "技术", "科学", "管理"}


@dataclass
class MajorRef:
    name: str                      # 展示名（取数据中最常见的写法）
    key: str                       # 归一化键
    family: str | None = None      # ai/cs/econ 或 None（通用专业）
    n_courses: int = 0
    n_course_schools: int = 0
    n_employment_rows: int = 0
    schools: list[str] = field(default_factory=list)
    aliases: list[str] = field(default_factory=list)

    @property
    def analyzable(self) -> bool:
        """有任一侧可核查数据即可分析（而不是"必须属于某个族"）。"""
        return self.n_courses > 0 or self.n_employment_rows > 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name, "key": self.key, "family": self.family,
            "n_courses": self.n_courses, "n_course_schools": self.n_course_schools,
            "n_employment_rows": self.n_employment_rows,
            "n_schools": len(self.schools), "schools": self.schools[:12],
            "aliases": self.aliases[:6], "analyzable": self.analyzable,
        }


def normalize_major(name: str) -> str:
    text = _SPACE.sub("", _PAREN.sub("", str(name or "")))
    changed = True
    while changed:
        changed = False
        for suffix in SUFFIXES:
            if text.endswith(suffix) and len(text) > len(suffix) + 1:
                text = text[: -len(suffix)]
                changed = True
    return text


def stems_of(name: str) -> list[str]:
    """中文专业名的词干切分：按 2–4 字滑窗取候选，供岗位关键词与目录匹配用。"""
    text = normalize_major(name)
    out: list[str] = []
    for size in (4, 3, 2):
        for i in range(0, max(len(text) - size + 1, 0)):
            piece = text[i:i + size]
            if piece in STOPWORDS or all(ch in STOPWORDS for ch in piece):
                continue
            out.append(piece)
    return list(dict.fromkeys(out))


def build_catalog(
    *,
    courses: Sequence[Any] = (),
    employment_majors: Iterable[str] = (),
    family_of=None,
    exclude_schools: Iterable[str] = (),
) -> dict[str, MajorRef]:
    """从课程库与就业分专业行自动发现专业目录。"""
    catalog: dict[str, MajorRef] = {}
    schools = {str(s) for s in exclude_schools}

    def bucket(name: str) -> MajorRef | None:
        key = normalize_major(name)
        if not key or len(key) < 2:
            return None
        # 校名不是专业：就业行/课程行里偶发混入的"XX大学/学院"必须剔除
        if key in schools or key.endswith(("大学", "学院", "学校")):
            return None
        ref = catalog.get(key)
        if ref is None:
            ref = MajorRef(name=str(name).strip(), key=key,
                           family=(family_of or (lambda _n: None))(key))
            catalog[key] = ref
        elif len(str(name)) < len(ref.name):
            ref.name = str(name).strip()
        return ref

    for course in courses:
        major = getattr(course, "major", None) if not isinstance(course, dict) else course.get("major")
        if not major:
            continue
        ref = bucket(str(major))
        if ref is None:
            continue
        ref.n_courses += 1
        school = getattr(course, "school", None) if not isinstance(course, dict) else course.get("school")
        if school and school not in ref.schools:
            ref.schools.append(str(school))
    for ref in catalog.values():
        ref.n_course_schools = len(ref.schools)
    for major in employment_majors:
        ref = bucket(str(major))
        if ref is not None:
            ref.n_employment_rows += 1
    return catalog


def match_major(query: str, catalog: dict[str, MajorRef]) -> MajorRef | None:
    """在问题文本里匹配已知专业：优先长键命中，其次词干命中。"""
    text = _SPACE.sub("", str(query or ""))
    best: tuple[int, MajorRef] | None = None
    for ref in catalog.values():
        if ref.key.endswith(("大学", "学院", "学校")):
            continue
        if len(ref.key) >= 2 and ref.key in text:
            if best is None or len(ref.key) > best[0]:
                best = (len(ref.key), ref)
    if best:
        return best[1]
    for ref in catalog.values():
        for stem in stems_of(ref.name):
            if len(stem) >= 3 and stem in text:
                if best is None or len(stem) > best[0]:
                    best = (len(stem), ref)
    return best[1] if best else None


def job_keywords(
    major: str | MajorRef,
    *,
    curated: dict[str, list[str]] | None = None,
    course_terms: Sequence[str] = (),
    limit: int = 8,
) -> dict[str, Any]:
    """按专业推导岗位检索词，并说明来源（人工词表 / 词干表 / 专业名 / 课程词）。"""
    name = major.name if isinstance(major, MajorRef) else str(major)
    key = normalize_major(name)
    curated = curated or {}
    if key in curated:
        return {"keywords": list(curated[key]), "source": "curated",
                "major": name, "stem": key}
    for stem, words in STEM_KEYWORDS.items():
        if stem in key:
            extra = [t for t in course_terms if t not in words][: max(0, limit - len(words))]
            return {"keywords": (words + extra)[:limit], "source": "stem_map",
                    "major": name, "stem": stem}
    # 没有词干表时只回到"专业名本身 + 去除通用后缀的核心词"，不再使用滑窗碎片
    core = key
    for suffix in ("工程", "技术", "科学", "管理", "教育", "学"):
        if core.endswith(suffix) and len(core) > len(suffix) + 1:
            core = core[: -len(suffix)]
            break
    words = [key] + ([core] if core != key and len(core) >= 2 else [])
    return {"keywords": list(dict.fromkeys(words))[:limit], "source": "name_only",
            "major": name, "stem": key}


#: 明显不是专业名的片段（培养方案文件名、就业行里的企业与统计噪声等）
NOISE_PATTERNS = ("培养方案", "修读指南", "课程一览", "教学计划", "指导意见", "实施方案",
                  "专业介绍", "招生", "简章", "汇编", "通知", "名单", "目录", "书院",
                  "教务处", "学院2024", "高校", "一流", "建设项目", "计划", "专项", "项目",
                  "学院", "大学", "学部", "手册", "指南", "概要", "简介",
                  "研究院", "中心", "基地", "平台",
                  # 企业/机构名：就业报告表格里常见错位产物
                  "公司", "集团", "银行", "有限", "股份", "保险", "证券", "电信", "移动",
                  "联通", "石化", "烟草", "铁路", "电网", "医院", "学校", "中学", "小学", "幼儿园")
NOISE_RE = re.compile(r"[\d%（）()\[\]——]|\s")

#: 像专业名的后缀（如 机械工程 / 会计学 / 教育技术学）
MAJOR_SUFFIXES = ("学", "工程", "技术", "管理", "科学", "教育", "设计", "艺术", "专业")


def is_plausible_major(name: str) -> bool:
    """专业名的合理性闸门：剔除文件名、企业名、统计行等明显不是专业的条目。

    判定依据（保守，宁可漏掉可疑项也不放进清单）：

    1. 2–16 个字符、无数字/百分号/括号、无空格；
    2. 不含企业/机构/文件名特征词；
    3. 以专业常见后缀结尾，或含已知学科词干（机械/会计/英语/音乐…）。
    """
    text = str(name or "").strip()
    if not (2 <= len(text) <= 16):
        return False
    if NOISE_RE.search(text):
        return False
    if any(token in text for token in NOISE_PATTERNS) and "专业" not in text:
        return False
    han = len(re.findall(r"[\u4e00-\u9fff]", text))
    if han < 2:
        return False
    if text.endswith(MAJOR_SUFFIXES):
        return True
    return any(stem in text for stem in STEM_KEYWORDS)

"""按用户需求选择分析层级（宏观 / 中观 / 微观 / 三视图）。

产品约定：

* 用户通常只关心**一个**层级；第一版只产出该层级的详实报告 + 只含该层级的 HTML；
* Agent 生成第一版后，再询问是否需要**完整的三视角**报告与 HTML；
* 原有问询交互保留（仍可用 --query/--occupation 直接提问）。
"""

from __future__ import annotations

from dataclasses import dataclass

SCALES: tuple[str, ...] = ("macro", "meso", "micro")
ALL_SCOPES: tuple[str, ...] = ("macro", "meso", "micro", "all")

SCALE_LABEL: dict[str, str] = {
    "macro": "宏观 · 区域/覆盖高校 × 岗位大类",
    "meso": "中观 · 某校某专业 × 目标岗位",
    "micro": "微观 · 个人证据 × 具体岗位",
    "all": "三视角 · 宏观 + 中观 + 微观",
}

SCALE_AUDIENCE: dict[str, str] = {
    "macro": "政府 / 主管部门",
    "meso": "专业负责人 / 教师",
    "micro": "学生本人",
    "all": "跨角色",
}

ALIASES: dict[str, str] = {
    "macro": "macro", "宏观": "macro", "区域": "macro", "政府": "macro",
    "meso": "meso", "中观": "meso", "专业": "meso", "院校": "meso", "教师": "meso",
    "micro": "micro", "微观": "micro", "个人": "micro", "学生": "micro", "简历": "micro",
    "all": "all", "全部": "all", "三视图": "all", "三视角": "all", "完整": "all",
}

#: 关键词 → 层级（用于从自然语言 query 推断默认层级）
KEYWORDS: dict[str, tuple[str, ...]] = {
    "micro": ("我学过", "我的", "本人", "简历", "个人", "适合什么岗位",
              "学生", "还差什么", "怎么补", "学习路径"),
    "meso": ("专业", "培养方案", "课程体系", "专业负责人", "毕业要求",
             "本专业", "该专业", "学院"),
    "macro": ("北京", "区域", "全市", "宏观", "政策", "政府", "产业",
              "总供给", "大类岗位"),
}


@dataclass(frozen=True)
class ScopeSpec:
    scale: str
    label: str
    audience: str
    inferred: bool = False
    reason: str = ""

    @property
    def is_single(self) -> bool:
        return self.scale in SCALES

    def to_dict(self) -> dict[str, object]:
        return {"scale": self.scale, "label": self.label, "audience": self.audience,
                "inferred": self.inferred, "reason": self.reason}


def normalize_scope(value: str | None) -> str | None:
    if value is None:
        return None
    raw = str(value).strip()
    return ALIASES.get(raw.lower()) or ALIASES.get(raw)


def infer_scope(query: str, *, school: str | None = None, major: str | None = None,
                has_personal_input: bool = False) -> ScopeSpec:
    """从 query/输入推断默认层级；推断不出来时默认中观（最常见的专业分析）。"""
    text = (query or "").lower()
    if has_personal_input:
        return ScopeSpec("micro", SCALE_LABEL["micro"], SCALE_AUDIENCE["micro"],
                         inferred=True, reason="检测到个人画像输入")
    for scale in ("micro", "meso", "macro"):
        hits = [kw for kw in KEYWORDS[scale] if kw.lower() in text]
        if hits:
            return ScopeSpec(scale, SCALE_LABEL[scale], SCALE_AUDIENCE[scale],
                             inferred=True, reason=f"query 命中关键词：{'、'.join(hits[:3])}")
    if school and major:
        return ScopeSpec("meso", SCALE_LABEL["meso"], SCALE_AUDIENCE["meso"],
                         inferred=True, reason="给定院校+专业，默认做专业级分析")
    return ScopeSpec("meso", SCALE_LABEL["meso"], SCALE_AUDIENCE["meso"],
                     inferred=True, reason="未命中关键词，默认中观（专业级）")


def resolve_scope(
    query: str,
    *,
    explicit: str | None = None,
    school: str | None = None,
    major: str | None = None,
    has_personal_input: bool = False,
) -> ScopeSpec:
    normalized = normalize_scope(explicit)
    if normalized:
        return ScopeSpec(normalized, SCALE_LABEL[normalized], SCALE_AUDIENCE[normalized],
                         inferred=False, reason="用户显式指定")
    return infer_scope(query, school=school, major=major,
                       has_personal_input=has_personal_input)


def question_text(default: ScopeSpec) -> str:
    """第一版生成前的层级选择话术（保留问询过程）。"""
    options = "1) 宏观（政府/区域）  2) 中观（专业/教师）  3) 微观（个人/学生）  4) 三视角完整版"
    return (f"请选择要生成的分析层级：{options}\n"
            f"（当前默认：{SCALE_LABEL[default.scale]}；直接回车即用默认）")


def followup_text() -> str:
    """第一版产出后的追问：是否需要完整三视角。"""
    return ("已生成你选择的层级报告。是否需要更完整的**三视角**分析报告与 HTML"
            "（宏观 + 中观 + 微观一次看全）？[y/N]")


def parse_choice(answer: str | None) -> str | None:
    value = (answer or "").strip().lower()
    if value in {"1", "宏观", "macro"}:
        return "macro"
    if value in {"2", "中观", "meso"}:
        return "meso"
    if value in {"3", "微观", "micro"}:
        return "micro"
    if value in {"4", "三视角", "三视图", "全部", "all"}:
        return "all"
    return normalize_scope(value)


def parse_yes(answer: str | None) -> bool:
    return (answer or "").strip().lower() in {"y", "yes", "是", "需要", "好的", "要"}

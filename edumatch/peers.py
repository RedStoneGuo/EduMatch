"""同类院校检索：给定目标院校（可带专业），从全国高校名单里选出可比院校。

数据来源（全部离线、可复现）：

* 教育部《全国普通高等学校名单》——随 edu-material-harvest 插件下发
  （``vendor/edu-material-harvest/.../references/data/univ_list_2026-06-17.json``）；
* 985 / 211 名单（同目录下 ``985.json`` / ``211.json``）；
* 本包已核实的官方域名台账 ``data/harvest/domains.json``（决定"现在能不能采"）；
* 本包已有材料的院校 ``data/source``（决定"能不能离线分析"）。

选校口径是**可解释的加权排序**，不是排行榜：层次匹配 > 同城/同省/同区域 > 同校型 >
可采集 > 可离线分析。每个候选都带 ``reasons`` 说明为什么被选中，便于报告披露与人工复核。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

PLUGIN_DATA = ("vendor", "edu-material-harvest", "skills", "edu-material-harvest",
               "references", "data")

#: 省 → 大区（同时接受简称与全称）
REGIONS: dict[str, str] = {
    "北京市": "华北", "北京": "华北", "天津市": "华北", "天津": "华北",
    "河北省": "华北", "河北": "华北", "山西省": "华北", "山西": "华北",
    "内蒙古自治区": "华北", "内蒙古": "华北",
    "辽宁省": "东北", "辽宁": "东北", "吉林省": "东北", "吉林": "东北",
    "黑龙江省": "东北", "黑龙江": "东北",
    "上海市": "华东", "上海": "华东", "江苏省": "华东", "江苏": "华东",
    "浙江省": "华东", "浙江": "华东", "安徽省": "华东", "安徽": "华东",
    "福建省": "华东", "福建": "华东", "江西省": "华东", "江西": "华东",
    "山东省": "华东", "山东": "华东",
    "河南省": "华中", "河南": "华中", "湖北省": "华中", "湖北": "华中",
    "湖南省": "华中", "湖南": "华中",
    "广东省": "华南", "广东": "华南", "广西壮族自治区": "华南", "广西": "华南",
    "海南省": "华南", "海南": "华南",
    "重庆市": "西南", "重庆": "西南", "四川省": "西南", "四川": "西南",
    "贵州省": "西南", "贵州": "西南", "云南省": "西南", "云南": "西南",
    "西藏自治区": "西南", "西藏": "西南",
    "陕西省": "西北", "陕西": "西北", "甘肃省": "西北", "甘肃": "西北",
    "青海省": "西北", "青海": "西北", "宁夏回族自治区": "西北", "宁夏": "西北",
    "新疆维吾尔自治区": "西北", "新疆": "西北",
}

#: 校型关键词（用于"同校型"加分）
CATEGORY_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("理工", ("工业", "理工", "科技", "工程", "电子", "邮电", "交通", "航空", "航天",
              "矿业", "石油", "地质", "化工", "建筑", "电力", "水利", "冶金", "机械")),
    ("师范", ("师范",)),
    ("财经", ("财经", "经济", "贸易", "商学", "工商")),
    ("医药", ("医科", "医药", "中医", "药科")),
    ("农林", ("农业", "林业", "农学", "农垦")),
    ("语言", ("外国语", "语言",)),
    ("政法", ("政法", "法")),
    ("民族", ("民族",)),
    ("艺术体育", ("艺术", "美术", "音乐", "戏剧", "体育", "舞蹈", "传媒")),
]


def school_category(name: str) -> str:
    for category, keywords in CATEGORY_KEYWORDS:
        if any(k in name for k in keywords):
            return category
    return "综合"


def region_of(province: str) -> str:
    return REGIONS.get(province, REGIONS.get(province.rstrip("省市自治区"), "其他"))


@dataclass(frozen=True)
class University:
    name: str
    province: str
    city: str
    level: str
    code: str
    tiers: tuple[str, ...] = ()

    @property
    def tier_rank(self) -> int:
        if "985" in self.tiers:
            return 3
        if "211" in self.tiers:
            return 2
        return 1

    @property
    def category(self) -> str:
        return school_category(self.name)

    @property
    def region(self) -> str:
        return region_of(self.province)

    def to_dict(self) -> dict[str, Any]:
        return {
            "school": self.name, "province": self.province, "city": self.city,
            "level": self.level, "tiers": list(self.tiers), "category": self.category,
            "region": self.region,
        }


@dataclass
class PeerCandidate:
    school: str
    province: str
    city: str
    level: str
    tiers: tuple[str, ...]
    category: str
    region: str
    domain: str = ""
    has_local_material: bool = False
    has_local_major: bool = False
    score: float = 0.0
    reasons: list[str] | None = None

    @property
    def harvestable(self) -> bool:
        return bool(self.domain)

    def to_dict(self) -> dict[str, Any]:
        return {
            "school": self.school, "province": self.province, "city": self.city,
            "tiers": list(self.tiers), "category": self.category, "region": self.region,
            "domain": self.domain, "harvestable": self.harvestable,
            "has_local_material": self.has_local_material,
            "has_local_major": self.has_local_major,
            "score": round(self.score, 1), "reasons": self.reasons or [],
        }


class UniversityCatalog:
    """全国高校名单 + 985/211 名单（离线）。"""

    def __init__(self, schools: list[University], source: str = "") -> None:
        self.schools = schools
        self.source = source
        self.by_name = {s.name: s for s in schools}

    @classmethod
    def load(cls, project_root: Path) -> "UniversityCatalog":
        base = Path(project_root).resolve().joinpath(*PLUGIN_DATA)
        listing = base / "univ_list_2026-06-17.json"
        schools: list[University] = []
        tiers: dict[str, list[str]] = {}
        if listing.exists():
            payload = json.loads(listing.read_text(encoding="utf-8"))
            for key, tag in (("985.json", "985"), ("211.json", "211")):
                path = base / key
                if path.exists():
                    for name in json.loads(path.read_text(encoding="utf-8")).get("names") or []:
                        tiers.setdefault(name, []).append(tag)
            for row in payload.get("schools") or []:
                name = str(row.get("n") or "").strip()
                if not name:
                    continue
                schools.append(University(
                    name=name, province=str(row.get("p") or ""), city=str(row.get("c") or ""),
                    level=str(row.get("l") or ""), code=str(row.get("k") or ""),
                    tiers=tuple(tiers.get(name, [])),
                ))
        return cls(schools, source=str(listing.relative_to(Path(project_root).resolve()).as_posix())
                   if listing.exists() else "")

    def get(self, name: str) -> University | None:
        if name in self.by_name:
            return self.by_name[name]
        matches = [s for s in self.schools if name and (name in s.name or s.name in name)]
        return matches[0] if len(matches) == 1 else None

    def search(self, *, keyword: str = "", province: str = "", city: str = "",
               level: str = "", tiers: Iterable[str] = ()) -> list[University]:
        wanted = set(tiers)
        return [
            s for s in self.schools
            if (not keyword or keyword in s.name)
            and (not province or province in s.province)
            and (not city or city in s.city)
            and (not level or s.level == level)
            and (not wanted or wanted & set(s.tiers))
        ]

    def provinces(self) -> list[str]:
        return sorted({s.province for s in self.schools if s.province})


def _verified_domains(project_root: Path) -> dict[str, str]:
    path = Path(project_root).resolve() / "data" / "harvest" / "domains.json"
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    out: dict[str, str] = {}
    for key, value in payload.items():
        if key.startswith("_") or key == "generated_at":
            continue
        if isinstance(value, str):
            out[key] = value
        elif isinstance(value, dict) and value.get("domain"):
            out[key] = str(value["domain"])
    return out


def _local_majors(project_root: Path) -> dict[str, set[str]]:
    """本包已有哪些院校的哪些专业培养方案（离线可分析的证据）。"""
    out: dict[str, set[str]] = {}
    base = Path(project_root).resolve() / "data" / "source" / "培养方案"
    if not base.exists():
        return out
    for school_dir in base.iterdir():
        if not school_dir.is_dir():
            continue
        majors: set[str] = set()
        for path in school_dir.glob("*.pdf"):
            stem = path.stem
            if "_" in stem:
                _, _, tail = stem.partition("_")
                majors.add(tail.strip())
        out[school_dir.name] = majors
    return out


class PeerSelector:
    """按"层次 + 地域 + 校型 + 可采集/可离线分析"给同类院校打分排序。"""

    def __init__(self, catalog: UniversityCatalog, *, domains: dict[str, str],
                 local_majors: dict[str, set[str]]) -> None:
        self.catalog = catalog
        self.domains = domains
        self.local_majors = local_majors

    @classmethod
    def from_project(cls, project_root: Path) -> "PeerSelector":
        root = Path(project_root).resolve()
        return cls(UniversityCatalog.load(root), domains=_verified_domains(root),
                   local_majors=_local_majors(root))

    def resolve(
        self, target_school: str, *, major: str | None = None, max_peers: int = 5,
        same_level_only: bool = True, require_domain: bool = False,
        exclude: Iterable[str] = (),
    ) -> tuple[list[PeerCandidate], dict[str, Any]]:
        """返回 (候选院校列表, 说明)。目标院校不在列表中。"""
        target = self.catalog.get(target_school)
        if target is None:
            return [], {"status": "target_not_found", "target": target_school,
                        "note": f"全国名单里找不到「{target_school}」，无法判定同类院校。"}
        excluded = {str(x) for x in exclude} | {target.name}
        majors = sorted({m for m in (self.local_majors.get(target.name) or set())
                         if not major or major in m})
        candidates: list[PeerCandidate] = []
        for school in self.catalog.schools:
            if school.name in excluded:
                continue
            if same_level_only and school.level != target.level:
                continue
            score, reasons = self._score(target, school, major)
            domain = self.domains.get(school.name, "")
            if require_domain and not domain:
                continue
            local = school.name in self.local_majors
            local_major = bool(major) and any(
                major in m for m in (self.local_majors.get(school.name) or set()))
            candidates.append(PeerCandidate(
                school=school.name, province=school.province, city=school.city,
                level=school.level, tiers=school.tiers, category=school.category,
                region=school.region, domain=domain,
                has_local_material=local, has_local_major=local_major,
                score=score, reasons=reasons,
            ))
        # 同分时优先：本校本专业已有材料 > 本校已有材料（可离线分析）> 名称
        candidates.sort(key=lambda c: (-c.score, -int(c.has_local_major),
                                      -int(c.has_local_material), c.school))
        note = {
            "status": "ok",
            "target": target.to_dict(),
            "target_local_majors": majors[:20],
            "n_candidates": len(candidates),
            "n_harvestable": sum(1 for c in candidates if c.harvestable),
            "note": ("同类院校口径为可解释加权排序（层次/地域/校型/可采集性），不是排行榜；"
                     "没有已核实官方域名的候选需先联网解析域名才能采集。"),
            "catalog_source": self.catalog.source,
        }
        return candidates[:max_peers], note

    @staticmethod
    def _score(target: University, peer: University, major: str | None) -> tuple[float, list[str]]:
        score = 0.0
        reasons: list[str] = []
        gap = abs(target.tier_rank - peer.tier_rank)
        if gap == 0:
            score += 40
            tag = "、".join(target.tiers) or "普通本科"
            reasons.append(f"层次一致（{tag}）+40")
        elif gap == 1:
            score += 18
            reasons.append(f"层次接近（{target.tier_rank}→{peer.tier_rank}）+18")
        if peer.city == target.city:
            score += 25
            reasons.append("同城 +25")
        elif peer.province == target.province:
            score += 15
            reasons.append("同省 +15")
        elif peer.region == target.region and peer.region != "其他":
            score += 8
            reasons.append(f"同区域（{peer.region}）+8")
        if peer.category == target.category and peer.category != "综合":
            score += 6
            reasons.append(f"同校型（{peer.category}）+6")
        return score, reasons


def find_peers(project_root: Path, target_school: str, *, major: str | None = None,
               max_peers: int = 5, require_domain: bool = False) -> dict[str, Any]:
    """便捷入口：返回可直接写进报告/工具的字典。"""
    selector = PeerSelector.from_project(project_root)
    peers, note = selector.resolve(target_school, major=major, max_peers=max_peers,
                                   require_domain=require_domain)
    return {**note, "peers": [c.to_dict() for c in peers],
            "missing_domain": [c.school for c in peers if not c.harvestable]}

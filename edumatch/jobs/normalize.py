"""Normalise company / position / salary / location fields for job postings.

Raw web rows are never trusted as unique demand. Normalisation produces stable
keys so that the same position reposted under several pages collapses into one
``deduplicated_count``.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass

COMPANY_SUFFIXES = [
    "有限责任公司", "股份有限公司", "有限公司", "股份公司", "集团有限公司",
    "科技集团", "网络科技", "信息技术", "技术有限公司", "（中国）", "(中国)",
    "北京分公司", "上海分公司", "分公司",
]

POSITION_NOISE = [
    "（急聘）", "(急聘)", "急聘", "【急聘】", "高薪", "双休", "五险一金",
    "2024届", "2025届", "校招", "社招", "实习", "实习生",
]

CITY_ALIASES = {
    "北京市": "北京", "北京·": "北京", "beijing": "北京",
    "上海市": "上海", "上海市市辖区": "上海", "广州": "广州", "深圳市": "深圳",
}

EDUCATION_ORDER = {
    "不限": 0, "学历不限": 0, "中专": 1, "高中": 2, "大专": 3, "专科": 3,
    "本科": 4, "学士": 4, "硕士": 5, "研究生": 5, "博士": 6,
}

EXPERIENCE_ORDER = {
    "经验不限": 0, "不限": 0, "应届": 1, "1年以下": 1, "1-3年": 2,
    "3-5年": 3, "5-10年": 4, "10年以上": 5,
}


def _nfkc(text: str) -> str:
    return unicodedata.normalize("NFKC", text or "").strip()


def norm_company(company: str) -> str:
    name = _nfkc(company)
    for suffix in COMPANY_SUFFIXES:
        if name.endswith(suffix):
            name = name[: -len(suffix)]
    return re.sub(r"[\s·・\-_（）()]+", "", name).lower()


def norm_position(position: str) -> str:
    name = _nfkc(position)
    for noise in POSITION_NOISE:
        name = name.replace(noise, "")
    name = re.sub(r"[（(].*?[)）]", "", name)
    return re.sub(r"[\s·・\-_/]+", "", name).lower()


def norm_city(city: str) -> str:
    raw = _nfkc(city)
    for alias, canonical in CITY_ALIASES.items():
        if alias in raw:
            return canonical
    return raw.split("-")[0].split("·")[0] or "未知"


_SALARY_NUM = re.compile(r"(\d+(?:\.\d+)?)\s*([kK千万wW]?)")


def parse_salary(raw: str) -> dict[str, float | str | None]:
    """Parse '15-25K·13薪' -> monthly range in CNY plus a coarse bucket."""
    text = _nfkc(raw).replace("元/月", "").replace("/月", "")
    text = re.sub(r"[·x×*]?\s*1[0-9]\s*薪", "", text)
    if not text or "面议" in text or "保密" in text:
        return {"min": None, "max": None, "bucket": "unknown", "is_daily": False}
    is_daily = "天" in text or "日" in text
    if is_daily:
        return {"min": None, "max": None, "bucket": "daily", "is_daily": True}
    tokens = _SALARY_NUM.findall(text)
    # A trailing unit applies to the whole range: "15-25K" means 15K-25K.
    units = [unit for _, unit in tokens if unit]
    fallback_unit = units[-1] if len(set(u.lower() for u in units)) == 1 else ""
    numbers = []
    for raw_number, raw_unit in tokens:
        unit = raw_unit or fallback_unit
        if unit.lower() == "k":
            factor = 1000
        elif unit in ("万", "w", "W"):
            factor = 10000
        else:
            factor = 1
        numbers.append(float(raw_number) * factor)
    numbers = [n for n in numbers if n > 0]
    if not numbers:
        return {"min": None, "max": None, "bucket": "unknown", "is_daily": False}
    low, high = min(numbers), max(numbers)
    if high <= 100:  # bare numbers such as "15-25" are thousands
        low, high = low * 1000, high * 1000
    midpoint = (low + high) / 2
    if midpoint < 8000:
        bucket = "lt8k"
    elif midpoint < 15000:
        bucket = "8k-15k"
    elif midpoint < 25000:
        bucket = "15k-25k"
    elif midpoint < 40000:
        bucket = "25k-40k"
    else:
        bucket = "gt40k"
    return {"min": low, "max": high, "bucket": bucket, "is_daily": False}


def education_rank(value: str) -> int | None:
    text = _nfkc(value)
    for label, rank in EDUCATION_ORDER.items():
        if label in text:
            return rank
    return None


def experience_rank(value: str) -> int | None:
    text = _nfkc(value)
    for label, rank in EXPERIENCE_ORDER.items():
        if label in text:
            return rank
    return None


@dataclass(frozen=True)
class NormalizedJob:
    company_norm: str
    position_norm: str
    city_norm: str
    salary: dict

    @property
    def fingerprint(self) -> str:
        raw = "|".join([self.company_norm, self.position_norm, self.city_norm, str(self.salary["bucket"])])
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]

    @property
    def content_key(self) -> str:
        """Fingerprint without company: catches cross-posting of the same role."""
        raw = "|".join([self.position_norm, self.city_norm, str(self.salary["bucket"])])
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def normalize_job(company: str, position: str, city: str, salary_raw: str) -> NormalizedJob:
    return NormalizedJob(
        company_norm=norm_company(company),
        position_norm=norm_position(position),
        city_norm=norm_city(city),
        salary=parse_salary(salary_raw),
    )

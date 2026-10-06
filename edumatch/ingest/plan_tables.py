"""把本科"指导性教学计划进程表"（培养方案 PDF）解析成课程记录。

北工大等高校的培养方案 PDF 是可抽取文本，课程行形如::

    0010726 机器学习 考试 3.5 56 44 12 3.5 信息学部
    ├ 课程编码 └ 课程名称 └ 考核 └学分 └总学时 └讲课 └实验/实践

解析规则（确定性、可复算；解析不到的字段保持 None，绝不猜）：

* 课程行以 7 位课程编码开头，名称以"考试/考查"结束；
* 学分 = 第一个数字；总学时 = 第二个数字；
* 实践学时优先按 ``总学时 − 讲课学时`` 计算；若该课被判定为实践环节课而
  差额为 0/负，则记为总学时（如"工作实习 4 120 120"）；
* 必修/选修取该行之前最近一次出现的章节标题（公共基础必修课/学科基础必修课/
  实践环节必修课 → 必修；学科基础选修课/专业选修课/校选专业课/自主课程 → 选修）；
* 是否实践环节：名称含 实验/实践/实习/实训/课程设计/课设/训练/毕业设计 等，
  或所在章节名含"实践环节"，或实践学时 ≥ 总学时的 50%。

这些启发式都被写入记录的 ``description``，便于人工复核与审计。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .courses import CourseRecord

NUMBER = r"\d+(?:\.\d+)?"
ROW = re.compile(
    rf"(?P<code>\d{{7}})\s*(?P<name>.{{2,60}}?)\s*(?P<exam>考试|考查)\s*"
    rf"(?P<nums>(?:{NUMBER}\s+){{1,6}})"
)
DEPT = re.compile(r"([\u4e00-\u9fff]{2,12}(?:学院|学部|部|系|中心|教学部))")

PRACTICE_HINTS = ("实验", "实践", "实习", "实训", "课程设计", "课设", "训练",
                  "毕业设计", "综合实验", "上机", "project")

#: 章节标题 → 是否必修。长标题在前，避免"选修课"盖过"专业选修课"这类前缀关系。
SECTIONS: list[tuple[str, bool]] = [
    ("公共基础必修课", True), ("学科基础必修课", True), ("实践环节必修课", True),
    ("专业必修课", True), ("通识教育必修", True), ("通识必修", True),
    ("学科基础选修课", False), ("专业选修课", False), ("实践环节选修课", False),
    ("校选专业课", False), ("自主课程", False), ("通识教育任意选修课", False),
    ("外语选修课", False), ("工科选修", False), ("选修课", False),
]


@dataclass
class PlanParseResult:
    courses: list[CourseRecord]
    n_rows: int
    sections: list[str]
    notes: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {"n_courses": len(self.courses), "n_rows": self.n_rows,
                "sections": self.sections, "notes": self.notes}


def normalize(text: str) -> str:
    """把分页/换行折叠成单空格，使跨行课程名可被同一行正则匹配。"""
    return re.sub(r"\s+", " ", (text or "").replace("\f", " "))


def sanitize_text(text: str) -> str:
    """去掉 PDF 抽取常见的孤立代理项（surrogate），否则写 JSON 会报 UnicodeEncodeError。"""
    return str(text).encode("utf-8", "ignore").decode("utf-8")


def _split_numbers(chunk: str) -> list[float]:
    return [float(x) for x in re.findall(NUMBER, chunk)]


def _required_from_section(text: str, position: int) -> tuple[bool | None, str, int | None]:
    """返回（必修?, 章节名, 章节标题距本行的字符距离）。

    距离用于判断"这个章节标题是不是真的紧邻本行"：培养方案表头行会把
    "公共基础必修课 学科基础必修课 实践环节必修课"并列写在一起，离得远的行
    其实属于别的课组。距离过远时调用方会把必修/选修记为 None（不猜）。
    """
    best: tuple[int, bool, str] | None = None
    for label, required in SECTIONS:
        start = text.rfind(label, 0, position)
        if start >= 0 and (best is None or start > best[0]):
            best = (start, required, label)
    if best is None:
        return None, "", None
    return best[1], best[2], position - best[0]


#: 章节标题离课程行超过该距离时，认为归属不可靠 → 必修/选修记 None。
SECTION_MAX_DISTANCE = 200

#: 一份完整的培养方案课程表通常有 30–100 行。低于该行数说明版式只被部分识别
#: （例如名先行版式只匹配到零星行），此时宁可返回 0，也不产出残缺课程表。
MIN_ROWS_FOR_ADAPTER = 20

#: 课程代码：各校格式差异很大——北工大 7 位数字、地大 GR081067、北大 04830041、
#: 清华 10421055、北理工 100960001、北交大 30L679Q / A109001B（**字母数字混排**）。
#: 统一放开成"5–14 位字母数字、且至少含 4 个数字"，避免再因为某一校的编码格式整表漏掉。
COURSE_CODE = re.compile(r"(?<![A-Za-z0-9])([A-Za-z0-9]{5,14})(?![A-Za-z0-9])")


def _looks_like_course_code(token: str) -> bool:
    """课程代码必须像"编号"：至少 4 个数字，且不是纯年份/纯单词。"""
    digits = sum(1 for ch in token if ch.isdigit())
    if digits < 4:
        return False
    if token.isdigit() and len(token) not in (5, 6, 7, 8, 9, 10, 11, 12):
        return False          # 4 位的多半是年份，5 位以上才当代码
    return True

#: 表头列名 → 内部字段。顺序即"数值列出现顺序"的候选。
NUMERIC_COLUMNS: list[tuple[str, tuple[str, ...]]] = [
    ("credits", ("学分", "Credits")),
    ("total", ("总学时", "学时", "Hours")),
    ("theory", ("讲课学时", "理论学时", "授课学时", "讲课", "理论")),
    ("practice", ("实践学时", "实践总学时", "实践")),
    ("semester", ("修读学期", "开课学期", "选课学期", "建议修读学期")),
]

#: 明显不是课程名的片段（用于质量闸门，避免把说明文字当成课程）
NAME_STOPWORDS = ("培养", "学分", "课程", "要求", "目标", "毕业", "说明", "备注", "序号",
                  "学期", "总计", "合计", "小计", "注：", "标准", "模块", "方向", "能力")
NAME_MAX_LEN = 24

#: 名称截断词：出现在课程名之后即代表进入其它列
NAME_CUT = ("考试", "考查", "Exam", "学分", "学时", "必修", "选修", "五级", "百分",
            "理论", "实践", "说明", "备注", "备注", "建议修读")
NAME_OK = re.compile(r"^[\u4e00-\u9fff][\u4e00-\u9fffA-Za-z0-9（）()·+\-]{1,19}$")

#: 课程名提示词（与策展文档抽取同一套规则）：不含任何提示词且少于 3 个汉字的片段
#: 视为表格错位产物（如"选修""必修""业B类"），直接丢弃。
NAME_HINTS = ("课", "学", "论", "导论", "基础", "技术", "设计", "实验", "实践", "实训",
              "工程", "原理", "方法", "分析", "建模", "编程", "系统", "算法", "应用",
              "开发", "案例", "研讨", "概论", "智能", "数据", "计算", "网络", "信息",
              "通信", "电子", "电路", "物理", "化学", "经济", "管理", "英语", "数学", "统计")

#: 以拉丁字母为主的技术类课程名（Python语言 / Java语言II / C语言程序设计 / SPSS / SQL …）。
#: 之前这类名字会被 NAME_OK（必须以汉字开头）与"汉字 < 3 且无提示词"两条规则整体丢弃，
#: 导致 Python/Java/C 等技能的供给被误记为 0——这是**通用解析缺陷**，不是某个专业的问题。
TECH_NAME_HINTS = ("python", "java", "javascript", "c语言", "c++", "c#", "r语言", "matlab",
                   "spss", "stata", "sas", "sql", "mysql", "oracle", "excel", "word",
                   "ppt", "office", "linux", "unix", "web", "html", "css", "php", "docker",
                   "git", "hadoop", "spark", "hive", "tableau", "powerbi", "power bi",
                   "vue", "react", "node", "数据库")


def _is_tech_name(name: str) -> bool:
    lowered = name.lower()
    for token in TECH_NAME_HINTS:
        if len(token) >= 4:
            if token in lowered:
                return True
        elif re.search(rf"(?<![a-z0-9]){re.escape(token)}(?![a-z0-9])", lowered):
            return True
    return False


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", text)


def _strip_parentheses(text: str) -> str:
    return re.sub(r"[（(][^）)]{0,14}[）)]", "", text)


def _row_numbers(text: str) -> list[float]:
    return [float(x) for x in re.findall(NUMBER, _strip_parentheses(text))]


def _clean_name(raw: str) -> str | None:
    raw = sanitize_text(raw)
    for cut in NAME_CUT:
        index = raw.find(cut)
        if index > 0:
            raw = raw[:index]
    name = re.sub(r"\s+", "", raw).strip("　 ，,。；;、:：·-")
    name = re.sub(r"^\d+[.、]", "", name)
    if not name or len(name) > NAME_MAX_LEN:
        return None
    if any(word in name for word in NAME_STOPWORDS):
        return None
    han = len(re.findall(r"[\u4e00-\u9fff]", name))
    latin = len(re.findall(r"[A-Za-z]", name))
    tech = _is_tech_name(name)
    if not tech and not NAME_OK.match(name):
        return None
    if tech:
        # 技术类课程名（Python语言 / Java语言II / C语言程序设计 …）放行；
        # 仍要求"有汉字或有 ≥3 个字母"，挡掉纯符号/表格错位碎片。
        if han < 1 and latin < 3:
            return None
    else:
        if han < 2 and latin < 3:
            return None
        if latin > han * 2 + 2:      # 英文残片（双语表格错位）一律拒绝
            return None
        if han < 3 and not any(hint in name for hint in NAME_HINTS):
            return None
    return name


def parse_rows_by_header(flat: str) -> list[dict[str, Any]]:
    """通用适配器：以课程代码为行首，字段按"表头列的数值语义"取值。

    覆盖已实测的四种版式：

    * 北工大 `0010726 机器学习 考试 3.5 56 44 12`（学分在前）
    * 地大   `GR081071 大学英语(1) College English(1) 64 4 64 考试 Exam 1`（总学时在前）
    * 民族   `1037010025 马克思主义基本原理概论 3 54 18 4`（学分/学时/实践学时/学期）
    * 北大   `04830041 计算概论 A 全校必修 3 68 34 大一/上`
    * 清华   `10421055 微积分A(1) 5学分`

    取值规则（确定性、可复核）：

    1. 学分 = 行内第一个 ≤ 15 的数字（括号内的序号不计，如 `大学英语(1)`）；
    2. 总学时 = 学分前紧邻的 ≥ 16 的数字，否则取学分后紧邻的 ≥ 16 的数字；
    3. 理论学时 = 总学时之后紧邻且不大于总学时的数字；实践学时 = 总学时 − 理论学时；
    4. 名称 = 代码之后、第一个数字之前的文本（去掉括号内容），并经过停用词与长度闸门。
    """
    matches = [m for m in COURSE_CODE.finditer(flat) if _looks_like_course_code(m.group(1))]
    rows: list[dict[str, Any]] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else min(len(flat), match.end() + 140)
        body = flat[match.end(): end][:160]
        numbers = _row_numbers(body)
        if not numbers:
            continue
        credit_pos = next((i for i, value in enumerate(numbers) if value <= 15), None)
        if credit_pos is None:
            continue
        credits = numbers[credit_pos]
        before = numbers[credit_pos - 1] if credit_pos > 0 else None
        after = numbers[credit_pos + 1:]
        if before is not None and before >= 16:
            total, rest = before, after
        elif after and after[0] >= 16:
            total, rest = after[0], after[1:]
        else:
            total, rest = None, after
        theory = rest[0] if (total and rest and 0 < rest[0] <= total) else None
        practice = (total - theory) if (total is not None and theory is not None) else None
        # 名称：优先取代码之后、首个"不在括号内"的数字之前的文本；
        # 只接受这一条路径：名先行版式（课程名在代码之前）会取到空名而被丢弃——
        # 宁可不解析该版式，也不产出"必修/五级制"这类错位名称。
        name = _clean_name(_strip_parentheses(body[:_first_number_pos(body)]))
        if name is None:
            continue
        dept_match = DEPT.search(body[:60])
        rows.append({
            "code": match.group(1), "name": name, "credits": credits, "total": total,
            "theory": theory, "practice": practice, "position": match.start(),
            "dept": dept_match.group(1) if dept_match else "",
        })
    return rows


def _first_number_pos(text: str) -> int:
    """返回首个"不在括号内"的数字位置；没有则返回文本长度。"""
    for match in re.finditer(NUMBER, text):
        prefix = text[:match.start()]
        if prefix.count("（") + prefix.count("(") > prefix.count("）") + prefix.count(")"):
            continue
        return match.start()
    return len(text)


def parse_rows_bjut(flat: str) -> list[dict[str, Any]]:
    """北工大专用兜底适配器（严格的 课程号+名称+考试/考查+数字 结构）。"""
    rows: list[dict[str, Any]] = []
    for match in ROW.finditer(flat):
        name = _clean_name(re.sub(r"\s+", "", match.group("name")))
        numbers = _split_numbers(match.group("nums"))
        if name is None or len(numbers) < 2:
            continue
        credits, total = numbers[0], numbers[1]
        theory = numbers[2] if len(numbers) > 2 and numbers[2] <= total else None
        rows.append({
            "code": match.group("code"), "name": name, "credits": credits, "total": total,
            "theory": theory,
            "practice": (total - theory) if theory is not None else None,
            "position": match.start(), "dept": "",
        })
    return rows


#: 「竖排展开表」版式：课程代码单独占一行，名称/英文名/数值各占后续若干行。
#: 典型是北京理工大学（9 位课程代码 + 名称换行 + 英文名 + 数值行 + 属性行）。
CODE_ONLY = re.compile(r"^([A-Za-z0-9]{5,14})\s*$")

#: 「名先行」版式：课程名在代码之前（北交大等）。
#: 例：``结构有限元分析 30L134Q 选 理 2 32 32   查 五级  6``
#: 历史文档把它列为"暂不支持"，于是北交大整校课程恒为 0，下游把"没教"当结论。
NAME_FIRST_ROW = re.compile(
    r"(?P<name>[\u4e00-\u9fff][\u4e00-\u9fffA-Za-z0-9（）()·+\-]{1,23}?)\s+"
    r"(?P<code>[A-Za-z0-9]{5,14})\s+"
    r"(?P<req>[必选])\s*(?P<mode>[理实])?\s+"
    rf"(?P<credits>{NUMBER})\s+(?P<hours>{NUMBER})"
)


def parse_rows_name_first(flat: str) -> list[dict[str, Any]]:
    """名先行版式：``课程名 课程号 必修/选修 理论/实践 学分 总学时 …``。"""
    rows: list[dict[str, Any]] = []
    for match in NAME_FIRST_ROW.finditer(flat):
        if not _looks_like_course_code(match.group("code")):
            continue
        name = _clean_name(match.group("name"))
        if name is None:
            continue
        credits = float(match.group("credits"))
        hours = float(match.group("hours"))
        if credits <= 0 or hours <= 0:
            continue
        rows.append({
            "code": match.group("code"), "name": name,
            "credits": credits, "total": hours if hours >= credits else None,
            "theory": None, "practice": None,
            "position": match.start(), "dept": "",
            "required_hint": match.group("req") == "必",
        })
    return rows

#: 竖排表里出现这些行就说明一条课程记录已结束（或整表结束）。
_EXPLODED_STOP = ("合计", "续表", "课程代码", "备注", "先修课说明", "小计", "总计")

#: 属性/时间类片段：出现在名称行里说明名称已经结束。
_EXPLODED_ATTR = ("必修", "选修", "不限", "考查", "考试", "实践周", "秋", "春", "夏", "冬",
                  "周", "学分", "学时")


def _cjk_ratio(line: str) -> float:
    if not line:
        return 0.0
    cjk = sum(1 for ch in line if "\u4e00" <= ch <= "\u9fff")
    return cjk / len(line)


def _is_number_only_line(line: str) -> bool:
    """整行只有数字/空白（数值行），不是课程名。"""
    stripped = re.sub(r"\s+", "", line)
    return bool(stripped) and not re.search(r"[\u4e00-\u9fffA-Za-z]", stripped)


def _is_code_line(line: str) -> bool:
    """整行只有课程代码，且确实像编号（≥4 位数字）。

    只写成"字母数字"会把 ``Business`` / ``Simulation`` 这类英文课程名也当成代码行，
    于是缓冲被截断、学分行读不到——课程数会从 47 掉到 13（实测踩过）。
    """
    match = CODE_ONLY.match(line.strip())
    return bool(match) and _looks_like_course_code(match.group(1))


def parse_rows_exploded(text: str) -> list[dict[str, Any]]:
    """解析「代码单独成行、字段逐格换行」的竖排课程表。

    背景（真实缺陷、共享路径）：北京理工大学 96 个专业的培养方案都是这种版式——
    ``100960001`` 一行、课程名若干行、英文名若干行、``1 2周 …… 秋季实践周 7 必修`` 一行。
    表头驱动适配器要求"代码+名称+数值同处一行"，于是整份表一行也匹配不到：
    实测《2023 会计学》有 125 行疑似课程行，引擎只解析出 3 门（还是别专业的名字），
    下游把"专业没教"当成结论。这里按"代码行 → 名称行 → 数值行"分段还原。
    """
    lines = text.split("\n")
    # 记录每行的字符偏移，保持与表头适配器一致的 position 语义（章节归属靠它）。
    offsets: list[int] = []
    cursor = 0
    for line in lines:
        offsets.append(cursor)
        cursor += len(line) + 1
    rows: list[dict[str, Any]] = []
    i, n = 0, len(lines)
    while i < n:
        if not _is_code_line(lines[i]):
            i += 1
            continue
        match = CODE_ONLY.match(lines[i].strip())
        code = match.group(1)
        start = i
        buffer: list[str] = []
        j = i + 1
        while j < n and len(buffer) < 12:
            line = lines[j].strip()
            if (not line) or _is_code_line(line) or any(s in line for s in _EXPLODED_STOP):
                break
            buffer.append(line)
            j += 1
        i = j if j > start else start + 1
        # 名称 = 开头连续的"中文为主"的行（英文名/数值行/属性行即停止）
        parts: list[str] = []
        k = 0
        while k < len(buffer):
            line = buffer[k]
            if (_cjk_ratio(line) >= 0.5 and not _is_number_only_line(line)
                    and not any(a in line for a in _EXPLODED_ATTR)):
                parts.append(line)
                k += 1
            else:
                break
        name = _clean_name(re.sub(r"\s+", "", "".join(parts))) if parts else None
        if not name:
            continue
        numbers: list[float] = []
        for line in buffer[k:]:
            numbers.extend(_split_numbers(line))
        joined = " ".join(buffer)
        rows.append({
            "code": code, "name": name,
            "credits": numbers[0] if numbers else None,
            # 竖排表里第二个数字常是"2周"这类实践周数，不能当总学时；学时未知就记 None。
            "total": None, "theory": None, "practice": None,
            "position": offsets[start], "dept": "",
            "required_hint": (True if "必修" in joined else
                              (False if "选修" in joined else None)),
        })
    return rows


def _is_practice(name: str, section: str, theory: float | None,
                 total: float | None, practice: float | None) -> bool:
    if any(hint in name.lower() for hint in PRACTICE_HINTS):
        return True
    # 注意：表头行会把"公共基础必修课/学科基础必修课/实践环节必修课"并列写在一起，
    # 用章节名判实践会把整个学科基础课块误标为实践课，因此这里只按课程名与实践学时占比判定。
    if total and practice is not None and practice >= total * 0.5:
        return True
    return False


def parse_plan_text(
    text: str, *, school: str, year: int | None, major: str, family: str | None,
    source_document: str, evidence_level: str = "A",
) -> PlanParseResult:
    """把一份培养方案正文解析成课程记录（同名课程保留学分更高的那条）。"""
    flat = normalize(text)
    courses: list[CourseRecord] = []
    sections: list[str] = []
    notes: list[str] = []
    by_name: dict[str, CourseRecord] = {}

    # 适配器**合并**而不是"先达标就用第一个"：表头驱动适配器字段更全（章节/开课单位），
    # 课程编码驱动的兜底适配器行更全（能补上表头识别不到的课程行）。历史上因为
    # "表头适配器先达标就 break"，Python语言/Java语言II 这类课被整行漏掉，技能供给记 0。
    rows_by_code: dict[str, dict[str, Any]] = {}
    adapter_counts: list[str] = []
    # 顺序＝优先级：竖排展开表（字段最全）→ 表头驱动 → 编码兜底。
    # 注意：竖排表靠**换行**分段，必须喂原始正文；另两个适配器喂折叠后的 flat。
    for adapter, source_text in ((parse_rows_exploded, text),
                                 (parse_rows_name_first, flat),
                                 (parse_rows_by_header, flat),
                                 (parse_rows_bjut, flat)):
        found = adapter(source_text)
        adapter_counts.append(f"{adapter.__name__}={len(found)}")
        for row in found:
            code = str(row.get("code") or f"n{row['position']}")
            rows_by_code.setdefault(code, row)     # 先到的（表头驱动）优先，保留其字段
    rows = list(rows_by_code.values())
    if rows:
        notes.append("适配器合并：" + "、".join(adapter_counts) + f" → {len(rows)} 行")
    for row in rows:
        name = row["name"]
        credits = row.get("credits")
        total = row.get("total")
        theory = row.get("theory")
        practice = row.get("practice")
        if practice is None and theory is not None and total is not None and total >= theory:
            practice = total - theory
        if row.get("experiment") is not None:
            practice = (practice or 0) + (row["experiment"] or 0)
        if not name or credits is None:
            continue
        required, section, distance = _required_from_section(flat, row["position"])
        if row.get("required_hint") is not None and (distance is None
                                                    or distance > SECTION_MAX_DISTANCE):
            # 竖排表的"必修/选修"就写在本条记录里，比远距离章节标题可靠。
            required = bool(row["required_hint"])
            distance = 0
        reliable_section = distance is not None and distance <= SECTION_MAX_DISTANCE
        is_required = required if reliable_section else None
        is_practice = _is_practice(name, section, theory, total, practice)
        if is_practice and (not practice or practice <= 0):
            practice = total
        if section and section not in sections:
            sections.append(section)
        code = row.get("code") or f"n{row['position']}"
        description = (
            f"{major}{year or ''}级培养方案 · 章节："
            f"{section if reliable_section else '未可靠标注'} · 学分 {credits}"
            + (f" · 总学时 {total:g}" if total else "")
            + (f" · 讲课 {theory:g}" if theory is not None else "")
            + (f" · 实践 {practice:g}" if practice else "")
            + (f" · 开课单位 {row['dept']}" if row.get("dept") else "")
            + ("" if is_required is None else
               (" · 必修" if is_required else " · 选修"))
        )
        record = CourseRecord(
            # 主键必须带专业：不同专业的培养方案会共用同一个课程号（如高等数学），
            # 只用 学校:年份:课程号 会让后解析的专业覆盖先解析的专业。
            course_id=f"plan:{school}:{major}:{year or 'n'}:{code}",
            school=school, year=year, major=major, name=name,
            category="实践" if is_practice else "理论",
            credits=credits, practice_hours=practice if is_practice else None,
            is_practice=is_practice, description=description,
            source_document=source_document, evidence_level=evidence_level, family=family,
            is_required=is_required,
        )
        previous = by_name.get(name)
        if previous is None or (record.credits or 0) > (previous.credits or 0):
            by_name[name] = record
    courses = list(by_name.values())
    if not rows:
        notes.append("未匹配到任何课程行：版式不在已支持范围内，或 PDF 为扫描件")
    return PlanParseResult(courses=courses, n_rows=len(rows),
                           sections=sections, notes=notes)

# -*- coding: utf-8 -*-
"""高校公开资料采集 · 全自动发现引擎

给定 {学校名, 域名}，自动摸清该校「培养方案 / 专业介绍 / 课程大纲 / 年度报告」挂在
哪些栏目页、附件直链是什么，产出可直接喂给 download.py 的 jobs.json，外加人眼确认表。

用法：
  python discover.py --school 湖南大学 --domain hnu.edu.cn
  python discover.py --school 湖南大学 --domain hnu.edu.cn --kinds 年度报告 --auto
  python discover.py --seeds schools_seed.json           # 批量
  python discover.py --school X --domain x.edu.cn --no-subdomains --max-pages 30

默认 --dry-run：只侦察、只出候选，不下载。
  --auto：确认后串起 download.py → report.py（先下载后台账）。

红线：**绝不猜域名**。--domain 必须由上层（Agent / 人）先解析出官方 *.edu.cn 再传入；
缺失即非零退出并给指引。宁可不跑，不编 URL。

算法六步（详见 references/08-自动发现逻辑.md）：
  Step0 规范化+校验域名 → apex
  Step1 主机扩展：探教务/招生/信息公开等子域，得 allowed_hosts
  Step2 导航图爬（BFS）：按关键词给链接打分，只跟进高分页（主力召回）
  Step3 附件枚举：命中栏目页抽附件；空则二级进详情页再抽
  Step4 可达性+魔数确认：每条候选实探 HTTP/ctype/头 8 字节，绝不凭猜
  Step5 产出：jobs.json / html_links.json / unverified.json / candidates.md / discover_report.json
  Step6 --auto：串 download.py → report.py
"""
import os
import re
import sys
import json
import time
import shutil
import argparse
import itertools
import subprocess
from collections import deque
from urllib.parse import urlparse, urljoin

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402
import enum_helpers as enum  # noqa: E402
import env  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))

# ----------------------------------------------------------------------------
# 关键词表：锚文本 / URL 命中即映射到材料类型
# ----------------------------------------------------------------------------
KW_TABLE = [
    ("培养方案", ["培养方案", "培养计划", "教学计划", "人才培养方案", "专业培养方案", "培养方案汇编"]),
    # 「专业介绍」只留专业本体词：删掉「招生简章/报考指南/招生专业」——那是招生宣传页
    # （招生网 /newsCenter/article/ 里满屏这类锚文本，会整片误命中）
    ("专业介绍", ["专业介绍", "专业设置", "专业目录", "学科专业", "本科专业"]),
    ("课程大纲", ["课程大纲", "教学大纲", "课程标准", "教学大纲汇编", "课程简介", "syllabus"]),
    # 「年度报告」只认质量报告实词：删掉宽泛的「信息公开」，否则「科研项目信息公开」页会误命中
    ("年度报告", ["就业质量", "教学质量", "本科教学质量", "毕业生就业", "年度报告", "质量报告",
                  "就业质量年度报告", "就业质量报告"]),
]
ALL_KINDS = [k for k, _ in KW_TABLE]

# 子域前缀（按优先级）：教务 / 招生 / 信息公开 / 研究生 / 评估
SUB_LABELS = [
    "jwc", "jw", "jiaowu", "jwgl", "dean", "undergrad", "rcpy", "jxjy",
    "zs", "zsb", "zsw", "zhaosheng", "bkzs",
    "xxgk", "gongkai", "info",
    "yjs", "yjsy", "gs",
    "pg", "pinggu", "zljk",
    "www",
]

# 导航排除：登录 / 验证码 / 英文站 / 邮件 / 脚本
NEG = re.compile(r"login|logon|验证码|captcha|/en/|/eng/|mailto:|javascript:|"
                 r"\.(jpg|jpeg|png|gif|css|js|ico|svg|woff2?|mp4|mp3|avi)(\?|$)", re.I)
# 附件后缀（导航爬取时跳过——它们是产物不是栏目）
ATT_EXT = (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".rar", ".zip", ".7z")
# 反爬/WAF 拦截页特征（命中即记 blocked，不再当正常栏目）
BLOCK_MARKS = ("系统提示", "抱歉", "暂时无法访问", "请稍后重试", "验证码", "安全检查",
               "Just a moment", "Attention Required", "Access Denied")

# 非材料栏目：新闻 / 通知公告 / 科研项目公开 / 党建思政 / 招生宣传。URL 路径命中即整页丢弃、不跟进。
NEG_SECTION = re.compile(
    r"/(?:xww|xwzh|xwdt|xwzx|xinwen|news|zhxw|tzgg|notice|gonggao|"
    r"newscenter|article|zhaosheng|zsxx|bkzn|"
    r"mkzxky|kyxm|dangjian|sizheng|llxx|dsxx)(?:/|\.|$)", re.I)
# 明显非目标材料的附件（报名表 / 申请表 / 指南 / 联系表等）：命中即不纳入候选
NEG_ATTACH = re.compile(
    r"报名表|申请表|汇总表|登记表|推荐表|承诺书|联系方式|咨询电话|招生咨询|"
    r"学校概况|考生须知|温馨提示|报考点|工作简报", re.I)


def is_blocked(text):
    return any(m in text for m in BLOCK_MARKS)


# ----------------------------------------------------------------------------
# Step0 域名规范化 + apex
# ----------------------------------------------------------------------------
def norm_host(s):
    """把任意写法归一为 hostname（去 scheme / 路径 / 端口 / 末尾点）。"""
    s = (s or "").strip().lower()
    s = re.sub(r"^https?://", "", s)
    s = s.split("/")[0].split("?")[0].split("@")[-1].split(":")[0].rstrip(".")
    return s


def apex_of(host):
    """取注册域。*.edu.cn 的 apex 取最后三段（如 jwc.hnu.edu.cn → hnu.edu.cn）。"""
    parts = host.split(".")
    if len(parts) >= 3 and parts[-2:] == ["edu", "cn"]:
        return ".".join(parts[-3:])
    if len(parts) >= 2:
        return ".".join(parts[-2:])
    return host


def same_apex(host, apex):
    return bool(host) and (host == apex or host.endswith("." + apex))


# ----------------------------------------------------------------------------
# 探测原语（HTTP/ctype/redirect/头字节 一把抓）
# ----------------------------------------------------------------------------
_PROBE_SEQ = itertools.count(1)


def probe(url, work, maxt=25, ref=None):
    """取一次响应元信息 + 头 8 字节。返回 dict。不抛异常（异常记 status=0）。

    每次用独立落盘文件（支持并发探测互不覆盖）；工作文件在结论期统一回收。
    """
    exe = env.require_curl()
    body = os.path.join(work, "_probe_%d.bin" % next(_PROBE_SEQ))
    fmt = "%{http_code}\t%{content_type}\t%{url_effective}\t%{num_redirects}"
    cmd = [exe, "-s", "-L", "-m", str(maxt), "-A", C.UA, "--compressed",
           "--speed-time", "15", "--speed-limit", "10240",
           "-r", "0-4095", "-o", body, "-w", fmt, url]
    if ref:
        cmd += ["-e", ref]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=maxt + 10)
        meta = r.stdout.decode("utf-8", "replace").strip().split("\t")
    except Exception:
        meta = []
    status, ctype, eff, redir = 0, "", url, 0
    if len(meta) >= 4:
        try:
            status = int(meta[0])
        except Exception:
            status = 0
        ctype, eff = meta[1], meta[2]
        try:
            redir = int(meta[3])
        except Exception:
            redir = 0
    head = b""
    try:
        with open(body, "rb") as f:
            head = f.read(64)          # 64 字节：够判文件头，也够认出 <!DOCTYPE（9 字符）
    except Exception:
        pass
    return {"url": url, "status": status, "ctype": ctype, "effective": eff,
            "redirects": redir, "head": head, "size": _size(body)}


def _size(p):
    try:
        return os.path.getsize(p)
    except Exception:
        return 0


def magic_kind(head, ext=""):
    """据头字节判文件真实类型。返回 pdf/zip/rar/ole/html/other/unknown。"""
    ext = ext.lower().lstrip(".")
    if head[:4] == b"%PDF":
        return "pdf"
    if head[:2] == b"PK":
        return "zip"
    if head[:3] == b"Rar":
        return "rar"
    if head[:4] == b"\xd0\xcf\x11\xe0":
        return "ole"
    low = head[:64].lower().lstrip()
    if low.startswith(b"<!doctype") or low.startswith(b"<html") or low.startswith(b"<?xml") \
            or b"<html" in low[:20]:
        return "html"
    if not head:
        return "unknown"
    return "other"


CONFIRMED_KINDS = {"pdf": "pdf", "zip": "zip", "rar": "rar", "ole": "doc"}


# ----------------------------------------------------------------------------
# Step2 导航评分
# ----------------------------------------------------------------------------
def classify(anchor, url):
    """据锚文本 + URL 判材料类型。返回 (kind 或 None, 命中数, 强信号?)。

    "强信号" = 锚文本（栏目名）里就含关键词；仅 URL 路径碰巧含词算弱信号。
    弱信号（如 URL 里带 /jxjh/ 而页面其实是新闻）不足以把整页判成材料。
    """
    a, u = (anchor or "").lower(), url.lower()
    best, hits, strong = None, 0, False
    for kind, kws in KW_TABLE:
        n = sum(1 for k in kws if k in a or k.lower() in u)
        if n > hits:
            best, hits = kind, n
            strong = any(k in a for k in kws)
    return best, hits, strong


def score_link(anchor, url, depth):
    """给一个导航链接打分。≥2 才跟进（精度优先于召回）。返回 (分, kind, 强信号?)。"""
    kind, hits, strong = classify(anchor, url)
    if not kind:
        return 0, None, False
    s = 3 * min(hits, 2)
    p = urlparse(url).path
    if p.count("/") <= 1:                       # 顶层栏目页更可能是入口
        s += 1
    if re.search(r"更多|more$|下一页|next", (anchor or "").strip(), re.I):
        s -= 2                                   # 分页/更多是路标，不是目标
    return s, kind, strong


def title_of(text):
    m = re.search(r"<title[^>]*>(.*?)</title>", text, re.I | re.S)
    return re.sub(r"\s+", " ", C.decode(m.group(1))).strip() if m else ""


def keep_as_hit(kind, depth, strong, url, kinds):
    """该页是否作为「材料栏目页」收下（决定其页内附件继承哪种材料类型）。

    三条必须同时成立，缺一即丢弃——防止把新闻/通知/科研公开页的正文措辞
    当成材料，进而让其页内全部附件被错误继承（假货之源）：
      · kind 属目标类型；depth>0（首页自身不当材料栏目）；
      · strong=强信号（锚文本或标题里含关键词，非仅 URL 路径碰巧含词）；
      · 不在 NEG_SECTION 黑名单栏目（新闻/通知/科研项目公开/党建）。
    """
    return bool(kind in kinds and depth > 0 and strong
                and not NEG_SECTION.search(url) and not _is_root_url(url))


def _is_root_url(u):
    """站点首页 / 栏目根（路径为空或仅 /）——本身不是材料，登记为材料页必是假货。"""
    return urlparse(u).path.strip("/") == ""


def _looks_nav(full, anchor):
    """像站内导航栏目页吗（顶层菜单全跟进，弥补栏目名不含关键词的漏召）。"""
    a = (anchor or "").strip()
    if not a or a.lower().startswith(("javascript:", "mailto:")):
        return False
    if urlparse(full).path.count("/") > 2:
        return False
    low = full.split("?")[0].lower()
    if low.endswith(ATT_EXT):
        return False
    return True


# ----------------------------------------------------------------------------
# Step1 主机扩展
# ----------------------------------------------------------------------------
def expand_hosts(apex, work, enabled=True, log=print, workers=10):
    """探子域，返回 (allowed_hosts, homes)。homes 用于启动 BFS。

    裸 apex 未必解析（如 hnu.edu.cn 不解析、www.hnu.edu.cn 才通），
    故 apex 与 www 都探，谁通谁进；子域再按优先级补。
    全部并发探测（顺序探 20 个子域会慢到分钟级）。
    """
    from concurrent.futures import ThreadPoolExecutor

    hosts = [apex, "www.%s" % apex]
    if enabled:
        hosts += ["%s.%s" % (lb, apex) for lb in SUB_LABELS if lb != "www"]

    def _one(host):
        url = "https://%s/" % host if not host.startswith("http") else host
        r = probe(url, work, maxt=10)
        eff = norm_host(urlparse(r["effective"]).hostname or "")
        ok = bool(r["status"]) and r["status"] < 400 and same_apex(eff or host, apex) \
            and (eff == host or not eff)
        return host, url, ok, r["status"]

    with ThreadPoolExecutor(max_workers=workers) as ex:
        results = list(ex.map(_one, hosts))

    allowed, homes = [], []
    for host, url, ok, status in results:
        if ok:
            if host not in allowed:
                allowed.append(host)
                homes.append(url)
            log("    + %s  (%d)" % (host, status))
    return allowed, homes


# ----------------------------------------------------------------------------
# Step2+3 导航爬 + 附件枚举
# ----------------------------------------------------------------------------
def _fetch_many(urls, maxt=30, workers=8):
    """并发抓页面正文（bytes）。保持顺序返回。"""
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=workers) as ex:
        return list(ex.map(lambda u: C.curl(u, maxt=maxt), urls))


def crawl(apex, allowed, homes, kinds, work, max_pages=60, depth_max=2, log=print, workers=8):
    """BFS（分批并发抓取）。返回 (hits, pages, blocked)。

    双队列：**关键词命中的链接优先**（pri），泛导航链接次之（gen）。
    否则首页几十条导航会把页数预算吃光，够不到 xxgk/jwc 里真正有料的栏目。
    每批 workers 个并发抓，兼顾速度与站点压力。
    """
    pri, gen = deque(), deque()
    for h in homes:
        gen.append((h, 0, None, False))
    seen, hits, pages, blocked = set(), [], [], []
    while (pri or gen) and len(pages) < max_pages:
        batch = []
        while (pri or gen) and len(batch) < workers and len(pages) + len(batch) < max_pages:
            url, depth, kind, strong = pri.popleft() if pri else gen.popleft()
            u = url.split("#")[0]
            if u in seen:
                continue
            seen.add(u)
            batch.append((u, depth, kind, strong))
        if not batch:
            break
        texts = _fetch_many([b[0] for b in batch], workers=workers)
        for (u, depth, kind, strong), raw in zip(batch, texts):
            text = C.decode(raw)
            if not text:
                continue
            if is_blocked(text):                 # 反爬拦截：记 blocked，不当正常栏目
                blocked.append(u)
                continue
            pages.append(u)
            # 判类：链接锚文本 →（缺省时）页面 <title>（栏目名常写在标题里）
            k_page, strong_page = kind, strong
            kt, ht, st = classify(title_of(text), u)
            if st or ht >= 2:                    # 标题强命中 / 标题+URL 双命中 → 以标题判定为准
                k_page, strong_page = kt, True
            elif not k_page and kt:
                k_page = kt
            # 非材料栏目（新闻/通知/科研项目公开/党建）即便标题命中关键词也不收：
            # 这类页里挂的"培养方案/年度报告"是正文措辞，不是可下载材料。
            # 且须为强信号：仅 URL 路径碰巧含词的弱命中页（实为新闻/其他栏目）不收，
            # 否则其页内所有附件会被错误继承成该类型 → 假货之源。
            if keep_as_hit(k_page, depth, strong_page, u, kinds):
                hits.append((u, k_page, text))
            if depth >= depth_max:
                continue
            for href, anchor in enum.all_links(text, u):
                full = href.split("#")[0]
                if NEG.search(full) or NEG.search(anchor):
                    continue
                if NEG_SECTION.search(full):       # 非材料栏目页：整页丢弃、不跟进
                    continue
                host = norm_host(urlparse(full).hostname)
                if not same_apex(host, apex):
                    continue
                low = full.split("?")[0].lower()
                if low.endswith(ATT_EXT) or full in seen:
                    continue
                s, k, strong = score_link(anchor, full, depth)
                if k in kinds and s >= 2:
                    pri.append((full, depth + 1, k, strong))    # 关键词命中：优先
                elif depth == 0 and _looks_nav(full, anchor):
                    gen.append((full, depth + 1, None, False))  # 顶层泛导航：次之
    return hits, pages, blocked


_RES_RE = re.compile(r'(?:href|src)\s*=\s*["\']([^"\']*(?:__local|/docs/|/upload|/resources/)[^"\']+)["\']', re.I)


def _detail_links(text, page_url, max_detail):
    """从栏目页找详情页链接（htm/html 或 /info/ 式）。"""
    out = []
    for href, anchor in enum.all_links(text, page_url):
        u = href.split("#")[0]
        if NEG.search(u) or NEG.search(anchor):
            continue
        low = u.split("?")[0].lower()
        if low.endswith(ATT_EXT) or low.endswith((".jpg", ".png", ".css", ".js")):
            continue
        if re.search(r"/(info|content|article|detail|show|tzgg|notice)[/_]", low) or \
           low.endswith((".htm", ".html", ".shtml")):
            if u not in out:
                out.append(u)
        if len(out) >= max_detail:
            break
    return out


def _is_article(u):
    """URL 像文章详情页（/info/1014/1654.htm 式）——本身即材料，别再往里二级解析。"""
    return bool(re.search(r"/(info|content|article|detail|show|tzgg)[/_]\d", u.lower()))


def enum_attachments(page_url, text, max_detail=30, workers=8):
    """命中页抽附件直链；无附件则二级进详情页。

    返回 (atts, htmls, ndetail)：
      atts   = [(直链, 锚文本)]  可下载附件
      htmls  = [(详情页URL, 标题)] 无附件的详情页本身即材料（只登记，不下载）
    """
    got = [(u, t) for u, t in enum.links_from_html(text, page_url) if C.ascii_path_url(u)]
    if got:
        return got, [], 0
    if _is_article(page_url):
        # 本身就是文章页：抽不到附件即登记本页，不再往里钻（否则每页再抓 30 条侧栏链接，爆炸）
        return [], [(page_url, title_of(text), len(text.encode("utf-8")))], 0
    # 栏目页无附件：本页本身可能就是 HTML 材料（如"本科专业"列表页）
    htmls = [(page_url, title_of(text), len(text.encode("utf-8")))]
    details = _detail_links(text, page_url, max_detail)
    if not details:
        return [], htmls, 0
    raws = _fetch_many(details, maxt=25, workers=workers)   # 并发抓详情页
    atts = []
    for d, raw in zip(details, raws):
        dt = C.decode(raw)
        if not dt or is_blocked(dt):
            continue
        items = [(u, t) for u, t in enum.links_from_html(dt, d) if C.ascii_path_url(u)]
        if not items:
            for m in _RES_RE.finditer(dt):
                full = urljoin(d, m.group(1))
                if re.search(r"\.(pdf|docx?|xlsx?|rar|zip|7z)(\?|$)", full.split("#")[0], re.I):
                    items.append((full, ""))
        if items:
            atts += items
        elif _is_article(d) or classify(title_of(dt), d)[0]:
            # 只留文章页或标题与材料类型相关的详情页，滤掉页脚导航（学生/教职工/校友…）
            htmls.append((d, title_of(dt), len(dt.encode("utf-8"))))
    return atts, htmls, len(details)


# ----------------------------------------------------------------------------
# Step4 确认
# ----------------------------------------------------------------------------
def confirm(school, kind, url, page, anchor, work, title="", log=print):
    """实探一条候选。返回 (bucket, record)。bucket ∈ confirmed/html/unverified。

    title = 承载页标题，作锚文本为泛词（"PDF文件"）时的说明兜底。
    """
    ext = ""
    m = re.search(r"\.([a-z0-9]{2,4})(?:\?|#|$)", url.split("/")[-1], re.I)
    if m:
        ext = m.group(1).lower()
    r = probe(url, work, maxt=25, ref=page if page != url else None)
    mk = magic_kind(r["head"], ext)
    year = _year_of(anchor, title)
    desc = _desc_of(anchor, title, url)
    base = dict(school=school, kind=kind, desc=desc, year=year, url=url, page=page,
                http=r["status"], ctype=r["ctype"], bytes=r["size"])
    if r["status"] in (200, 206) and mk in CONFIRMED_KINDS:
        if mk in ("rar", "zip"):
            base["pack"] = True
        # 优先用 URL 里的后缀（doc/xls 比魔数更细），否则据魔数推
        base["ext"] = ext if ext in ("pdf", "doc", "docx", "xls", "xlsx", "rar", "zip") \
            else CONFIRMED_KINDS[mk]
        return "confirmed", base
    if mk == "html" or "html" in (r["ctype"] or "").lower():
        return "html", base
    return "unverified", base


GENERIC_ANCHOR = re.compile(
    r"^(pdf|pdf\s*文件|附件|附件下载|下载|文件|docx?|xlsx?|rar|zip|查看|点击下载|详情|"
    r"more|图标|image|icon|无标题文档|20\d{2}年?)\s*$", re.I)


def _year_of(anchor, title=""):
    """从锚文本/标题里取年份。限 2000~本年+1，避免把 URL 哈希里的数字当年份。"""
    hi = time.localtime().tm_year + 1
    for src in (anchor or "", title or ""):
        for m in re.finditer(r"(?<!\d)(20\d{2})(?!\d)", src):
            y = int(m.group(1))
            if 2000 <= y <= hi:
                return str(y)
    return ""


def _desc_of(anchor, title="", url=""):
    """说明优先级：具体锚文本 → 承载页标题 → URL 文件名。泛词锚文本（"PDF文件"）跳过。"""
    a = re.sub(r"\s+", " ", (anchor or "")).strip()
    if a and not GENERIC_ANCHOR.match(a) and len(a) > 1:
        return C.safe_name(a, 70)
    t = re.sub(r"\s+", " ", (title or "")).strip()
    # 去站点后缀：只切「空格-空格 / 竖线 / 破折号」，别切词内连字符（否则 "2024-2025年度…" 会被切成 "2024"）
    t = re.split(r"\s+[-–—]\s+|\s*[|｜]\s*", t)[0].strip()
    if t and not GENERIC_ANCHOR.match(t):
        return C.safe_name(t, 70)
    name = url.split("?")[0].rstrip("/").split("/")[-1]
    return C.safe_name(name or "未命名", 70)


# ----------------------------------------------------------------------------
# Step5 产出
# ----------------------------------------------------------------------------
def write_outputs(out, ctx, confirmed, html, unverified, log=print):
    os.makedirs(out, exist_ok=True)
    jobs = []
    for c in confirmed:
        j = {k: c[k] for k in ("school", "kind", "desc", "year", "url", "page", "ext") if k in c}
        if c.get("pack"):
            j["pack"] = True
        jobs.append(j)
    C.save_json(jobs, os.path.join(out, "jobs.json"))
    # html_links.json 用 report.py 期望的 schema：{school,type,form,link,desc}
    C.save_json([dict(school=h.get("school", ""), type=h.get("kind", ""),
                      form="HTML正文页", link=h.get("url", ""), desc=h.get("desc", ""))
                 for h in html], os.path.join(out, "html_links.json"))
    C.save_json(unverified, os.path.join(out, "unverified.json"))

    # candidates.md 人眼确认表
    lines = ["# 采集候选确认表 · %s" % ctx["school"], "",
             "- 域名：%s（apex=%s）" % (ctx["domain"], ctx["apex"]),
             "- 可达主机：%s" % ", ".join(ctx["allowed_hosts"]),
             "- 扫描页数：%d；命中栏目：%d；反爬拦截：%d；候选：%d（确认 %d / HTML %d / 未定 %d）"
             % (ctx["pages"], len(ctx["hits"]), len(ctx.get("blocked", [])),
                len(confirmed) + len(html) + len(unverified),
                len(confirmed), len(html), len(unverified)),
             "", "## 已确认（可下载）", "",
             "| 材料类型 | 说明 | 年份 | HTTP | ctype | 字节 | 直链 | 承载页 |",
             "|---|---|---|---|---|---|---|---|"]
    for c in confirmed:
        lines.append("| %s | %s | %s | %s | %s | %s | %s | %s |" % (
            c["kind"], c["desc"], c.get("year", ""), c["http"], c["ctype"], c["bytes"],
            c["url"], c["page"]))
    lines += ["", "## 仅 HTML（只登记，不下载）", "",
              "| 材料类型 | 说明 | HTTP | ctype | 链接 | 承载页 |", "|---|---|---|---|---|---|"]
    for h in html:
        lines.append("| %s | %s | %s | %s | %s | %s |" % (
            h["kind"], h["desc"], h["http"], h["ctype"], h["url"], h["page"]))
    lines += ["", "## 未定（未通过魔数/可达性，未自动下载）", "",
              "| 材料类型 | 说明 | HTTP | ctype | 字节 | 直链 |", "|---|---|---|---|---|---|"]
    for u in unverified:
        lines.append("| %s | %s | %s | %s | %s | %s |" % (
            u["kind"], u["desc"], u["http"], u["ctype"], u.get("bytes", ""), u["url"]))
    with open(os.path.join(out, "candidates.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    C.save_json(ctx, os.path.join(out, "discover_report.json"))
    return jobs


# ----------------------------------------------------------------------------
# 主流程
# ----------------------------------------------------------------------------
def discover_one(school, domain, out, kinds, no_subdomains=False, max_pages=60,
                 dry_run=True, work=None, log=print, workers=8):
    t0 = time.time()
    apex = apex_of(norm_host(domain))
    if not apex.endswith(".edu.cn"):
        raise ValueError("域名 %r 不是 *.edu.cn 官方域名（本工具只采官方源）。" % domain)
    work = work or os.path.join(out, "_discover_tmp")
    os.makedirs(work, exist_ok=True)

    log("=" * 60)
    log("学校：%s  域名：%s  apex：%s" % (school, norm_host(domain), apex))
    # Step0 可达性校验（裸 apex 未必解析，只作参考；真正兜底看 expand_hosts 结果）
    r0 = probe("https://%s/" % apex, work, maxt=20)
    log("Step0 校验 apex：HTTP %s  ctype=%s" % (r0["status"], r0["ctype"]))
    if not r0["status"]:
        log("    （裸 apex 不解析属常见；继续探 www/子域）")

    log("Step1 主机扩展……")
    allowed, homes = expand_hosts(apex, work, enabled=not no_subdomains, log=log, workers=workers)
    log("    可达主机 %d 个：%s" % (len(allowed), ", ".join(allowed)))
    if not allowed:
        raise RuntimeError("apex、www 及已知子域均不可达。请核对域名是否官方 *.edu.cn，勿凭猜。")

    log("Step2 导航图爬（≤%d 页，深≤2）……" % max_pages)
    hits, pages, blocked = crawl(apex, allowed, homes, kinds, work, max_pages=max_pages,
                                 log=log, workers=workers)
    log("    命中栏目页 %d；反爬拦截 %d" % (len(hits), len(blocked)))
    for b in blocked[:5]:
        log("    ! 拦截：%s" % b)

    return _finalize(school, norm_host(domain), apex, out, kinds, hits, pages, blocked,
                     allowed, work, dry_run, log, workers, t0)


def _finalize(school, domain, apex, out, kinds, hits, pages, blocked, allowed, work,
              dry_run, log, workers, t0):
    """Step3-6：由「命中栏目页」枚举附件 → 实探确认 → 落盘 →（可选）自动下载。

    discover_one（全站爬）与 discover_pages（指定承载页）共用此段，
    保证两条入口产出同一套台账口径。
    """
    log("Step3 附件枚举……")
    cand = []          # (kind, url, page, anchor, ptitle)  可下载附件
    htmlc = []         # (kind, url, page, desc)            只登记的 HTML 材料页
    for page_url, kind, text in hits:
        ptitle = title_of(text)
        if re.fullmatch(r"[\d\s\-—.]+", ptitle or ""):       # 标题仅年份/数字 → 补类型名
            ptitle = "%s%s" % (kind, ptitle)
        atts, htmls, ndetail = enum_attachments(page_url, text)
        log("    %s → 附件 %d，HTML 页 %d（%d 详情页）" % (page_url, len(atts), len(htmls), ndetail))
        for u, t in atts:
            if NEG_ATTACH.search("%s %s" % (t or "", u)):    # 报名表/申请表/指南等非材料，跳过
                continue
            cand.append((kind, u, page_url, t, ptitle))
        for u, t, sz in htmls:
            if NEG_ATTACH.search("%s %s" % (t or "", u)):
                continue
            if _is_root_url(u):          # 站点首页/栏目根：不是材料，登记即假货
                continue
            # 不整列继承承载页类型：按该页自身标题/锚文本重判，判不出就不登记
            # （否则"年度报告"栏目里的"研究生招生简章"也会被登记成年度报告）
            kt, ht, _st = classify("%s %s" % (t or "", ptitle), u)
            if kt not in kinds:
                continue
            htmlc.append((kt, u, page_url, t or ptitle, sz))
    # 去重（忽略 http/https 差异：同一 URL 两协议会各出现一次）
    seen, uniq = set(), []
    for c in cand:
        key = re.sub(r"^https?://", "", c[1])
        if key not in seen:
            seen.add(key)
            uniq.append(c)
    seenh, uniqh = set(), []
    for c in htmlc:
        key = re.sub(r"^https?://", "", c[1])
        if key not in seenh:
            seenh.add(key)
            uniqh.append(c)
    log("    去重后：附件候选 %d，HTML 材料页 %d" % (len(uniq), len(uniqh)))

    log("Step4 逐条实探确认（HTTP/ctype/魔数）……")
    from concurrent.futures import ThreadPoolExecutor
    confirmed, html, unverified = [], [], []

    def _safe(c):
        try:
            return confirm(school, c[0], c[1], c[2], c[3], work, title=c[4])
        except Exception as e:                       # 单条异常不拖垮整轮
            return "unverified", dict(school=school, kind=c[0], desc=c[3], url=c[1],
                                      page=c[2], http=0, ctype="", bytes=0, error=str(e))

    with ThreadPoolExecutor(max_workers=workers) as ex:
        results = list(ex.map(_safe, uniq))
    for bucket, rec in results:
        {"confirmed": confirmed, "html": html, "unverified": unverified}[bucket].append(rec)
    # 无附件的详情页：本身即 HTML 材料，只登记（正文已在枚举阶段抓过，直接带证据）
    for kind, url, page, desc, size in uniqh:
        html.append(dict(school=school, kind=kind, desc=_desc_of("", desc or "", url),
                         url=url, page=page, http=200, ctype="text/html", bytes=size))
    log("    确认 %d / HTML %d / 未定 %d" % (len(confirmed), len(html), len(unverified)))

    ctx = dict(school=school, domain=domain, apex=apex,
               allowed_hosts=allowed, pages=len(pages), hits=[h[0] for h in hits],
               blocked=blocked, kinds=kinds, confirmed=len(confirmed), html=len(html),
               unverified=len(unverified), elapsed=round(time.time() - t0, 1))
    os.makedirs(out, exist_ok=True)
    jobs = write_outputs(out, ctx, confirmed, html, unverified, log=log)
    log("Step5 产出 → %s" % out)
    log("     jobs.json(%d) / html_links.json(%d) / unverified.json(%d) / candidates.md / discover_report.json"
        % (len(jobs), len(html), len(unverified)))

    # 工作目录回收（自己的暂存，非用户数据）
    C.recycle(work)

    if not dry_run:
        step6_auto(school, out, jobs, log=log)
    return ctx


def discover_pages(school, domain, out, kinds, pages_spec, no_subdomains=False,
                   dry_run=True, work=None, log=print, workers=8):
    """指定承载页直采：由上层（Agent+WebSearch）定位承载页 URL，本函数只枚举其附件。

    pages_spec: [(url, kind 或 None), ...]。kind=None 时按页面标题/URL 自动判类。
    这是「全站爬不动时」的精准入口，等价手工 21_enum.py 的做法——把"找承载页"
    交给会搜索的 Agent，把"枚举+实探+落盘"交给本函数，避免纯站内爬的假货。
    """
    t0 = time.time()
    apex = apex_of(norm_host(domain))
    if not apex.endswith(".edu.cn"):
        raise ValueError("域名 %r 不是 *.edu.cn 官方域名（本工具只采官方源）。" % domain)
    work = work or os.path.join(out, "_discover_tmp")
    os.makedirs(work, exist_ok=True)

    log("=" * 60)
    log("学校：%s  域名：%s  apex：%s  【指定承载页模式】" % (school, norm_host(domain), apex))
    log("指定承载页 %d 个，逐页抓取……" % len(pages_spec))

    hits, pages, blocked = [], [], []
    for url, kind in pages_spec:
        full = url.split("#")[0]
        host = norm_host(urlparse(full).hostname)
        if not same_apex(host, apex):                    # 红线：只采官方 apex 内
            log("    x 跨域，丢弃：%s" % full)
            continue
        raw = C.curl(full, maxt=30)
        text = C.decode(raw)
        if not text:
            log("    x 抓取失败（不可达/空）：%s" % full)
            continue
        if is_blocked(text):
            log("    ! 反爬拦截：%s" % full)
            blocked.append(full)
            continue
        k = kind
        if not k or k == "auto":
            kt, ht, _st = classify(title_of(text), full)
            k = kt if kt in kinds else None
        if k not in kinds:
            log("    x 判类失败（用 --kind 显式指定）：%s" % full)
            continue
        pages.append(full)
        hits.append((full, k, text))
        log("    + [%s] %s" % (k, full))

    if not hits:
        raise RuntimeError("指定承载页均不可用（不可达/跨域/判类失败）。请核对 URL 与 --kind。")

    return _finalize(school, norm_host(domain), apex, out, kinds, hits, pages, blocked,
                     [], work, dry_run, log, workers, t0)


def step6_auto(school, out, jobs, log=print):
    """Step6：串 download.py → report.py。"""
    if not jobs:
        log("Step6 --auto：无确认候选，跳过下载。")
        return
    dest = os.path.join(out, "新增数据")
    records = os.path.join(out, "records.json")

    def _run(args):
        # 子进程写 UTF-8；text=True 会按 GBK 解码而炸掉 reader 线程 → 强制 utf-8
        return subprocess.run([sys.executable] + args, capture_output=True,
                              encoding="utf-8", errors="replace")

    log("Step6 --auto：下载 → %s" % dest)
    dl = _run([os.path.join(HERE, "download.py"), os.path.join(out, "jobs.json"),
               "--dest", dest, "--records", records])
    sys.stdout.write(dl.stdout or "")
    if dl.returncode != 0:
        sys.stderr.write(dl.stderr or "")
        log("download.py 非零退出（%d），已中止台账。" % dl.returncode)
        return
    log("Step6 --auto：出台账 → %s" % out)
    rp = _run([os.path.join(HERE, "report.py"), records, "--out", out,
               "--html-links", os.path.join(out, "html_links.json")])
    sys.stdout.write(rp.stdout or "")
    if rp.returncode != 0:
        sys.stderr.write(rp.stderr or "")


# ----------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="高校公开资料采集·全自动发现（默认只侦察）")
    ap.add_argument("--school", help="学校名")
    ap.add_argument("--domain", help="官方域名（*.edu.cn）。必须由上层先解析，本工具不猜。")
    ap.add_argument("--seeds", help="批量种子 json：[{school,domain,kinds?}]")
    ap.add_argument("--kinds", default=",".join(ALL_KINDS),
                    help="材料类型，逗号分隔（默认全部）")
    ap.add_argument("--page", action="append", default=[],
                    help="指定承载页 URL 直采（可重复）。用于全站爬不动时：先由 Agent+WebSearch "
                         "定位承载页，再交给本工具枚举附件。与 --seeds 互斥。")
    ap.add_argument("--kind", default="auto",
                    help="配合 --page：指定这些承载页的材料类型（默认 auto=按标题/URL 自判）")
    ap.add_argument("--out", default="discover_out", help="产出目录")
    ap.add_argument("--max-pages", type=int, default=60, help="导航爬取页数上限")
    ap.add_argument("--no-subdomains", action="store_true", help="跳过子域探测")
    ap.add_argument("--workers", type=int, default=8, help="并发抓取数（默认 8）")
    ap.add_argument("--auto", action="store_true", help="确认后自动下载+出台账")
    ap.add_argument("--dry-run", action="store_true", help="只侦察（默认行为）")
    a = ap.parse_args()

    kinds = [k.strip() for k in a.kinds.split(",") if k.strip()]

    # 组装任务列表
    tasks = []
    if a.page:
        if a.seeds or not (a.school and a.domain):
            sys.stderr.write("--page 需与 --school、--domain 同时给出（且不与 --seeds 同用）。\n")
            sys.exit(2)
        if a.kind != "auto" and a.kind not in ALL_KINDS:
            sys.stderr.write("--kind 须为 %s 之一（或 auto）。\n" % "/".join(ALL_KINDS))
            sys.exit(2)
        pages_spec = [(u, a.kind) for u in a.page]
        out = a.out
        try:
            discover_pages(a.school, a.domain, out, kinds, pages_spec,
                           no_subdomains=a.no_subdomains, dry_run=not a.auto,
                           workers=a.workers)
        except Exception as e:
            sys.stderr.write("指定承载页直采失败：%s\n" % e)
            sys.exit(1)
        return
    if a.seeds:
        seeds = C.load_json(a.seeds, [])
        if isinstance(seeds, dict):          # 允许 {"schools":[...], "_说明":...} 形态
            seeds = seeds.get("schools", [])
        for s in seeds:
            if not isinstance(s, dict) or "_说明" in s or not s.get("domain"):
                continue
            tasks.append((s["school"], s["domain"], s.get("kinds", kinds)))
    elif a.school and a.domain:
        tasks.append((a.school, a.domain, kinds))
    else:
        sys.stderr.write(
            "缺少 --school/--domain（或 --seeds）。\n"
            "本工具不猜域名：请先用 WebSearch 解析该校官方 *.edu.cn 域名，再传入。\n"
            "示例：python discover.py --school 湖南大学 --domain hnu.edu.cn\n")
        sys.exit(2)

    dry = not a.auto
    for school, domain, kd in tasks:
        out = os.path.join(a.out, C.safe_name(school, 40)) if len(tasks) > 1 else a.out
        try:
            discover_one(school, domain, out, kd, no_subdomains=a.no_subdomains,
                         max_pages=a.max_pages, dry_run=dry, workers=a.workers)
        except Exception as e:
            sys.stderr.write("发现失败：%s\n" % e)


if __name__ == "__main__":
    main()

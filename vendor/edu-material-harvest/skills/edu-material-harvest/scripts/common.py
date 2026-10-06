# -*- coding: utf-8 -*-
"""高校公开资料采集 · 通用函数库

从实战脚本抽取的可复用件：下载 / 回收站 / 去重 / 魔数 / 命名 / 编码 / RAR 解压 / PDF 首页取词。
所有函数独立、无副作用（除显式落盘/删除外）。

可移植约定：
  - 外部工具（curl / 解压器 / PowerShell）一律经 env.py 解析，本文件不写死任何绝对路径
  - 缺依赖**吵不要哑**：需要即 require_*（抛 DepError）；可选能力缺失一律 WARN
  - 删除走回收站；无 PowerShell 时**隔离到 <临时目录>/_edu_recycle/**（文件不丢，只移位）
"""
import os
import re
import sys
import json
import hashlib
import base64
import tempfile
import subprocess
from urllib.parse import urlparse, quote

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import env  # noqa: E402
# 供上层沿用 C.find_7z() 等写法（真身在 env）
from env import find_7z, find_curl, find_powershell, DepError, have  # noqa: E402,F401

# 控制台中文（Windows GBK 终端）——导入即生效。
# 用 reconfigure 而非新建 TextIOWrapper：避免重复包裹导致底层缓冲被 GC 关闭。
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", write_through=True)
    sys.stderr.reconfigure(encoding="utf-8", errors="replace", write_through=True)
except Exception:
    pass

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

_HAS_FITZ = env.have("fitz")
_WARNED = set()


def _warn_once(key, msg):
    """同一类警告只打一次，避免刷屏，但绝不静默。"""
    if key not in _WARNED:
        _WARNED.add(key)
        print("WARN:", msg, file=sys.stderr)


# ----------------------------------------------------------------------------
# 网络
# ----------------------------------------------------------------------------
def curl(url, out=None, ref=None, maxt=300, timeout=None):
    """下载或取页面。

    out=None  -> 返回响应体 bytes
    out=path  -> 落盘，返回 bool

    必带反卡死参数 --speed-time 30 --speed-limit 20480：
    高校附件服务器会中途停传，<20KB/s 持续 30 秒即中止，避免干等到 max-time。
    缺 curl 时抛 DepError（不再返回空 bytes 被误判为「下载失败」）。
    """
    exe = env.require_curl()
    cmd = [exe, "-s", "-m", str(maxt), "-A", UA, "-L", "--compressed",
           "--speed-time", "30", "--speed-limit", "20480"]
    if ref:
        cmd += ["-e", ref]
    if timeout:
        cmd += ["--connect-timeout", str(timeout)]
    if out:
        cmd += ["-o", out]
    cmd += [url]
    r = subprocess.run(cmd, capture_output=True)
    if out:
        return r.returncode == 0 and os.path.exists(out) and os.path.getsize(out) > 0
    return r.stdout


def decode(b):
    """多编码解码：utf-8 → gbk → gb18030 → ignore。"""
    if isinstance(b, str):
        return b
    for enc in ("utf-8", "gbk", "gb18030"):
        try:
            return b.decode(enc)
        except Exception:
            pass
    return b.decode("utf-8", "ignore")


def url_quote(u):
    """只对路径段做百分号编码（保留 scheme/host/query）。用于中文路径直链。"""
    p = urlparse(u)
    path = quote(p.path, safe="/%")
    from urllib.parse import urlunparse
    return urlunparse((p.scheme, p.netloc, path, p.params, p.query, p.fragment))


def ascii_path_url(u):
    """路径含非 ASCII 的 URL 视为无效直链（多为页面 JS 数组里的原始文件名），返回 False。"""
    return all(ord(c) < 128 for c in urlparse(u).path)


# ----------------------------------------------------------------------------
# 文件 / 去重
# ----------------------------------------------------------------------------
def sha1(path, chunk=1 << 20):
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for c in iter(lambda: f.read(chunk), b""):
            h.update(c)
    return h.hexdigest()


def magic_ok(path, ext):
    """按魔数校验文件头。ext 为小写扩展名。"""
    try:
        with open(path, "rb") as f:
            head = f.read(8)
    except Exception:
        return False
    ext = ext.lower().lstrip(".")
    if ext == "pdf":
        return head[:4] == b"%PDF"
    if ext in ("docx", "xlsx", "pptx", "zip"):
        return head[:2] == b"PK"
    if ext in ("doc", "xls", "ppt"):
        return head[:4] == b"\xd0\xcf\x11\xe0"
    if ext == "rar":
        return head[:3] == b"Rar"
    return True


def valid(path, ext=None):
    """文件是否存在、非空、且魔数正确。⚠️ 只查文件头：半截文件会被误判为完整。

    参数 ext=None 时按扩展名推断。
    """
    if not os.path.exists(path) or os.path.getsize(path) < 800:
        return False
    if ext is None:
        ext = os.path.splitext(path)[1]
    return magic_ok(path, ext)


def safe_name(s, maxlen=80):
    """文件名清洗：去 Windows 非法字符，限长，空值兜底。"""
    s = re.sub(r'[\\/:*?"<>|]', "_", str(s)).strip()
    s = re.sub(r"\s+", " ", s)
    return s[:maxlen].strip(" .") or "unnamed"


# ----------------------------------------------------------------------------
# 删除（回收站；无 PowerShell 则隔离，绝不静默 no-op）
# ----------------------------------------------------------------------------
def _default_quarantine():
    return os.path.join(tempfile.gettempdir(), "_edu_recycle")


def _ps_recycle(ps, paths):
    """调 PowerShell 走回收站。返回是否成功（据执行后文件是否仍存在判定）。"""
    body = ["Add-Type -AssemblyName Microsoft.VisualBasic"]
    for p in paths:
        esc = os.path.abspath(p).replace("'", "''")
        fn = "DeleteDirectory" if os.path.isdir(p) else "DeleteFile"
        body.append("[Microsoft.VisualBasic.FileIO.FileSystem]::%s('%s','OnlyErrorDialogs',"
                    "'SendToRecycleBin')" % (fn, esc))
    enc = base64.b64encode(("\r\n".join(body)).encode("utf-16-le")).decode("ascii")
    try:
        subprocess.run([ps, "-NoProfile", "-EncodedCommand", enc],
                       capture_output=True, text=True, timeout=120)
    except Exception:
        return False
    return not any(os.path.exists(p) for p in paths)


def _quarantine(paths, tmp=None):
    """兜底：把文件移入隔离目录（不永久删除，文件不丢）。返回隔离目录。"""
    q = os.path.join(tmp or _default_quarantine())
    os.makedirs(q, exist_ok=True)
    import shutil as _sh
    for p in paths:
        if not os.path.exists(p):
            continue
        base = os.path.basename(p.rstrip("\\/")) or "item"
        dst = os.path.join(q, base)
        k = 1
        while os.path.exists(dst):
            k += 1
            dst = os.path.join(q, "%s_%d" % (base, k))
        _sh.move(p, dst)
    return q


def recycle(paths, on_missing="quarantine", tmp=None):
    """删除文件/目录，优先走回收站。

    paths: 路径列表或单个路径。
    on_missing: PowerShell 不可用时的行为——"quarantine"（默认，移入隔离目录+WARN）
                或 "raise"（抛 DepError）。

    任何情况下都不会永久删除：回收站失败即降级为隔离。
    """
    if not paths:
        return
    if isinstance(paths, str):
        paths = [paths]
    paths = [os.path.abspath(p) for p in paths if os.path.exists(p)]
    if not paths:
        return

    ps = env.find_powershell()
    if ps and _ps_recycle(ps, paths):
        return

    remaining = [p for p in paths if os.path.exists(p)]
    if not remaining:
        return
    if not ps and on_missing == "raise":
        raise env.DepError(
            "PowerShell（回收站删除）",
            "本机无 PowerShell。改用 recycle(on_missing='quarantine') 隔离，"
            "或在有 PowerShell 的环境运行。")
    q = _quarantine(remaining, tmp)
    _warn_once("recycle_quarantine",
               "回收站不可用，已将 %d 项移入隔离目录（文件未丢失）：%s" % (len(remaining), q))


def recycle_dir(path):
    recycle(path)


# ----------------------------------------------------------------------------
# RAR / ZIP 解压（解压器经 env 探测：7z / 7za / bz / unrar，或 EDU_7Z 覆盖）
# ----------------------------------------------------------------------------
def extract_rar(archive, outdir):
    """解压 RAR/ZIP 到 outdir，返回 True/False。缺解压器抛 DepError。"""
    tool = env.require_7z()
    os.makedirs(outdir, exist_ok=True)
    r = subprocess.run(env.extract_cmd(archive, outdir, tool), capture_output=True)
    return r.returncode == 0


# ----------------------------------------------------------------------------
# PDF 取词（PyMuPDF）
# ----------------------------------------------------------------------------
def pdf_text_available():
    """PyMuPDF 是否可用。不可用时所有 PDF 取词退化为空串。"""
    return _HAS_FITZ


def first_page_text(pdf, maxlen=2000, required=False):
    """取 PDF 首页文本；无文字层返回空串。

    required=True 且无 PyMuPDF → 抛 DepError；否则返回 "" 并（首次）WARN。
    """
    if not _HAS_FITZ:
        if required:
            raise env.DepError("PyMuPDF (fitz)", "pip install pymupdf")
        _warn_once("fitz_missing",
                   "未安装 PyMuPDF，PDF 取词不可用（文件名将退化为通用名）。pip install pymupdf")
        return ""
    try:
        import fitz
        with fitz.open(pdf) as d:
            if d.page_count == 0:
                return ""
            return d[0].get_text()[:maxlen]
    except Exception:
        return ""


def strip_school_prefix(line, school=None):
    """去掉行首校名。school 给定时，若行以校名（或其去后缀形）开头则剥掉。"""
    s = line.strip()
    if not school:
        return s
    for name in (school, school.replace("大学", ""), school.replace("学院", "")):
        if name and s.startswith(name):
            return s[len(name):].strip()
    return s


def course_name(pdf):
    """从 PDF 首页首行提取课程名（教学大纲命名用）。

    规则：取首个非纯数字、非空白行；剥《》书名号；去「课程名称：」「教学大纲」等前后缀。
    """
    txt = first_page_text(pdf)
    if not txt:
        _warn_once("pdf_no_text_syllabus", "PDF 无文字层（或未装 PyMuPDF），课程名退化，用通用名。")
        return ""
    for line in txt.splitlines():
        s = line.strip()
        if not s or re.fullmatch(r"[\d\s.．、,，:：\-—_/()（）]+", s):
            continue
        s = re.sub(r"^课程名称[：:\s]+", "", s)
        s = re.sub(r"教学大纲.*$", "", s)
        s = s.strip("《》").strip()
        s = re.sub(r"[（(].*?[）)]$", "", s).strip()  # 去尾部括号补充
        if s:
            return safe_name(s, 60)
    return ""


def pdf_title_line(pdf, school=None):
    """取培养方案类专业名：以「培养方案」结尾、去掉校名前缀后的最短行。

    school 给定时剥去行首校名（不写死任何校名，可移植）。
    """
    txt = first_page_text(pdf, maxlen=4000)
    if not txt:
        _warn_once("pdf_no_text_plan", "PDF 无文字层（或未装 PyMuPDF），专业名退化，用通用名。")
        return ""
    cands = []
    for line in txt.splitlines():
        s = strip_school_prefix(line, school)
        if not s.endswith("培养方案") or len(s) > 40:
            continue
        name = re.sub(r"培养方案$", "", s).strip("《》").strip()
        if name:
            cands.append(name)
    if not cands:
        return ""
    return safe_name(min(cands, key=len), 60)


# ----------------------------------------------------------------------------
# 记录 IO
# ----------------------------------------------------------------------------
def load_json(path, default=None):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return default if default is not None else []


def save_json(obj, path):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)

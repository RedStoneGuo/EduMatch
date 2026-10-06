# -*- coding: utf-8 -*-
"""高校公开资料采集 · 外部环境解析（唯一入口）

设计目标：**换台机器也能跑，缺东西要吵不要哑。**

外部工具（解压器 / curl / PowerShell）与可选 Python 库（fitz / openpyxl / docx）
的探测全部收在这里，别处一律不写死路径。探测顺序：

    1) 环境变量覆盖   EDU_7Z / EDU_CURL / EDU_POWERSHELL
    2) PATH 查找       shutil.which(<常见命令名>)
    3) 常见安装位置    各平台默认目录（不写机器专属路径）

`find_*()` 缺失返回 None；`require_*()` 缺失抛 `DepError`（附安装提示）。
调用方要么用 require_* 让缺失显性失败，要么自行处理 None 并 WARN —— 但**绝不静默降级**。
"""
import os
import sys
import shutil
import importlib.util

# ----------------------------------------------------------------------------
# 依赖缺失异常
# ----------------------------------------------------------------------------
class DepError(RuntimeError):
    """外部依赖缺失。message 已含「缺什么 + 怎么补」两段提示，直接打印即可。"""

    def __init__(self, tool, hint):
        self.tool = tool
        self.hint = hint
        super().__init__("缺少依赖：%s\n  解决：%s" % (tool, hint))


# ----------------------------------------------------------------------------
# 通用探测原语
# ----------------------------------------------------------------------------
def _env_override(var):
    """读环境变量覆盖项；为空或路径不存在则返回 None。"""
    p = (os.environ.get(var) or "").strip()
    if p and os.path.exists(p):
        return p
    return None


def _which_any(names):
    """按序 which 第一批存在的命令名，返回绝对路径或 None。"""
    for n in names:
        p = shutil.which(n)
        if p:
            return p
    return None


def _first_existing(paths):
    """返回第一个存在的绝对路径（支持 %ProgramFiles% 等环境变量展开）。"""
    for p in paths:
        q = os.path.expandvars(p)
        if os.path.exists(q):
            return q
    return None


def have(mod):
    """Python 库是否可用（不导入，只查 spec）。"""
    try:
        return importlib.util.find_spec(mod) is not None
    except Exception:
        return False


# ----------------------------------------------------------------------------
# 解压器（7z 家族 / Bandizip / unrar）
# ----------------------------------------------------------------------------
_SEVENZ_PATHS = [
    r"%ProgramFiles%\7-Zip\7z.exe",
    r"%ProgramFiles(x86)%\7-Zip\7z.exe",
    r"%ProgramW6432%\7-Zip\7z.exe",
    "/usr/bin/7z", "/usr/bin/7za", "/usr/local/bin/7z",
    "/opt/homebrew/bin/7z",
]
_BANDIZIP_PATHS = [
    r"%ProgramFiles%\Bandizip\bz.exe",
    r"%ProgramFiles(x86)%\Bandizip\bz.exe",
    r"%ProgramW6432%\Bandizip\bz.exe",
]


def find_7z():
    """返回 (可执行路径, 调用风格) 或 None。风格 ∈ {"7z","bandizip"}。

    两者命令行不同：7z 用 `-o<dir>`（无冒号），Bandizip 用 `-o:<dir>`（带冒号）。
    见 extract_cmd()。
    """
    p = _env_override("EDU_7Z")
    if p:
        flavor = "bandizip" if os.path.basename(p).lower().startswith("bz") else "7z"
        return p, flavor
    p = _which_any(["7z", "7za", "7zr"])
    if p:
        return p, "7z"
    p = _which_any(["bz"])                       # Bandizip console
    if p:
        return p, "bandizip"
    p = _first_existing(_SEVENZ_PATHS)
    if p:
        return p, "7z"
    p = _first_existing(_BANDIZIP_PATHS)
    if p:
        return p, "bandizip"
    return None


def require_7z():
    """解压器，缺失抛 DepError。返回 (path, flavor)。"""
    got = find_7z()
    if not got:
        raise DepError(
            "解压器（7-Zip / Bandizip / unrar）",
            "安装 7-Zip（https://7-zip.org）或 Bandizip；"
            "或用环境变量 EDU_7Z 指向可执行文件。")
    return got


def extract_cmd(archive, outdir, tool=None):
    """据解压器风格拼解压命令。tool 为 require_7z() 的返回值；缺省时自行解析。

    7z:        <7z> x -y -o<outdir> <archive>
    bandizip:  <bz> x -y -aoa -o:<outdir> <archive>

    路径一律转绝对路径：Bandizip 不认相对路径（尤其正斜杠形式）。
    """
    path, flavor = tool or require_7z()
    archive, outdir = os.path.abspath(archive), os.path.abspath(outdir)
    if flavor == "bandizip":
        return [path, "x", "-y", "-aoa", "-o:%s" % outdir, archive]
    return [path, "x", "-y", "-o%s" % outdir, archive]


# ----------------------------------------------------------------------------
# curl
# ----------------------------------------------------------------------------
def find_curl():
    """返回 curl 绝对路径或 None。"""
    p = _env_override("EDU_CURL")
    if p:
        return p
    p = _which_any(["curl"])
    if p:
        return p
    return _first_existing([r"%SystemRoot%\System32\curl.exe", "/usr/bin/curl"])


def require_curl():
    """curl，缺失抛 DepError。"""
    p = find_curl()
    if not p:
        raise DepError(
            "curl",
            "Windows 10 1803+ 自带 curl；或安装 curl 并加入 PATH；"
            "或用环境变量 EDU_CURL 指向可执行文件。")
    return p


# ----------------------------------------------------------------------------
# PowerShell（回收站删除用；非 Windows 无解，走隔离目录兜底）
# ----------------------------------------------------------------------------
def find_powershell():
    """返回 powershell/pwsh 绝对路径或 None。"""
    p = _env_override("EDU_POWERSHELL")
    if p:
        return p
    p = _which_any(["powershell", "pwsh"])
    if p:
        return p
    return _first_existing([
        r"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe",
        "/usr/bin/pwsh", "/usr/local/bin/pwsh",
    ])


def require_powershell():
    """PowerShell，缺失抛 DepError。"""
    p = find_powershell()
    if not p:
        raise DepError(
            "PowerShell",
            "本机无 PowerShell，无法走回收站删除。非 Windows 下请接受"
            "「隔离到 _recycle/ 目录」的兜底行为（文件不丢，只移位）。")
    return p


# ----------------------------------------------------------------------------
# 诊断：python -m env  或  python env.py
# ----------------------------------------------------------------------------
def _report():
    rows = [
        ("7z 解压器", find_7z()),
        ("curl", find_curl()),
        ("powershell", find_powershell()),
        ("[py] fitz (PyMuPDF)", have("fitz")),
        ("[py] openpyxl", have("openpyxl")),
        ("[py] docx (python-docx)", have("docx")),
    ]
    print("== 环境探测 ==")
    for name, v in rows:
        if isinstance(v, tuple):
            print("  %-22s OK  %s  (%s)" % (name, v[0], v[1]))
        elif v:
            print("  %-22s OK  %s" % (name, v))
        else:
            print("  %-22s --  未找到（相关功能会报错或降级）" % name)
    print("提示：EDU_7Z / EDU_CURL / EDU_POWERSHELL 可覆盖自动探测。")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", write_through=True)
    except Exception:
        pass
    _report()

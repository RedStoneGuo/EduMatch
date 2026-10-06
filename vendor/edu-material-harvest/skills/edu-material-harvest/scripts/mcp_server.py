# -*- coding: utf-8 -*-
"""高校公开资料采集 · MCP 服务端（零依赖 stdio）

把本 skill 的采集内核（discover / download / report）以 **MCP（Model Context
Protocol）** 暴露出去，让任何支持 MCP 的客户端（Claude Code / Codex / WorkBuddy /
千问办公 …）都能用同一套采集能力——**内核不改，只做透传**。

设计要点（技术/逻辑见 references/09-Agent接入与MCP.md）：

1. 零依赖：只用 Python 标准库实现协议子集，**不必 pip install mcp**。
2. stdio + NDJSON：每行一条 JSON-RPC 2.0 消息，无 Content-Length 头。
3. **stdout 屏蔽（承重设计）**：本仓库的 common.py / env.py 在 import 时就
   reconfigure 了 sys.stdout，且各长任务默认 log=print —— 这些都写 stdout，
   会毁掉 JSON-RPC 流。故在**任何 repo import 之前**先把 fd1 改指 stderr，
   协议出口改用 dup 出来的真 stdout。见下方 _shield_stdout()。
4. 粗粒度工具 + 后台任务：弱模型只需「调一个工具 → job_wait → read_artifacts」，
   长任务立即返回 job_id，避免客户端超时。
5. 失败自解释：缺依赖不静默，工具返回 isError 并内嵌安装提示。

用法：
  python mcp_server.py                 # 以 stdio 服务端启动（客户端调用）
  python mcp_server.py --print-config  # 打印可粘贴的客户端 MCP 配置
  python mcp_server.py --install claude   # 一键写 Claude Code 配置
  python mcp_server.py --install codex    # 一键写 Codex 配置
"""
import os
import sys

# ----------------------------------------------------------------------------
# 0) stdout 屏蔽 —— 必须在任何 repo import 之前执行（承重设计）
#
#    · real_out  = dup 原始 fd1（真 stdout 管道），协议只往它写
#    · fd1 改指 /dev/null：此后任何 print / 子进程继承 fd1 的杂散输出**直接丢弃**，
#      既不污染协议流，也**不会写满任何管道**（→ 对不排空 stderr/stdout 的客户端
#      也不会死锁）。可选 EDU_MCP_LOG=1 时改指 stderr，便于本地排障。
#    · sys.stdout 重绑到 fd1：repo 里的 reconfigure/print 无害
# ----------------------------------------------------------------------------
_REAL_OUT = os.dup(1)
_VERBOSE = os.environ.get("EDU_MCP_LOG", "").strip() not in ("", "0", "false", "off")
try:
    if _VERBOSE:
        os.dup2(2, 1)                          # 排障：杂散输出转 stderr
    else:
        _devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(_devnull, 1)                   # 默认：杂散输出丢弃，杜绝管道写满
        os.close(_devnull)
    try:
        sys.stdout.flush()
    except Exception:
        pass
except Exception:
    pass
try:
    sys.stdout = os.fdopen(os.dup(1), "w", encoding="utf-8", errors="replace",
                           buffering=1)
except Exception:
    pass

# ----------------------------------------------------------------------------
# 依赖与常量（stdlib）
# ----------------------------------------------------------------------------
import io          # noqa: E402
import json        # noqa: E402
import time        # noqa: E402
import shutil      # noqa: E402
import threading   # noqa: E402
import subprocess  # noqa: E402
import traceback   # noqa: E402
from collections import deque  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(HERE)
REFS = os.path.join(SKILL_DIR, "references")

sys.path.insert(0, HERE)

NAME = "edu-material-harvest"
VERSION = "2.0.0"
SUPPORTED_PROTOCOLS = ("2025-06-18", "2024-11-05")
DEFAULT_PROTOCOL = "2025-06-18"

# initialize 时回给客户端的用法提示（弱模型可直接照做）
INSTRUCTIONS = (
    "高校公开资料采集：给定{学校名, 官方 *.edu.cn 域名}，从官方免登录公开源采"
    "培养方案/专业介绍/课程大纲/年度报告，逐份落盘并登记可溯源台账。\n"
    "· 先调 env_check（确认 curl/openpyxl 等依赖）。\n"
    "· 一键：harvest_school(school, domain) 立即返回 job_id → job_wait(job_id)"
    " 等它跑完 → read_artifacts(out, \"candidates\") 看确认表。\n"
    "· 若全站爬被子域 WAF 挡、或爬出假货：自己联网搜到「挂着材料的那一页」URL，"
    "改用 harvest_pages(school, domain, pages)。\n"
    "· 多校批量：harvest_many(schools=[{school,domain}, ...])。\n"
    "· 按地区批量：region_seeds(province=\"湖南\", preset=\"985\") 生成 seeds.json（纯本地、"
    "出口径边界与待补域名清单）→ 你联网补域名 → harvest_many。\n"
    "· prompt \"edu:harvest-school\" 提供了照念即用的完整配方。\n"
    "红线：绝不猜域名；绝不编 URL；只采官方免登录公开源。"
)

# 协议出口：真 stdout（dup 出来的），二进制、逐条 flush
_proto = os.fdopen(_REAL_OUT, "wb", buffering=0)

# 仓库内核：屏蔽完成后才能 import（它们 import 即改 sys.stdout）
import common as C        # noqa: E402
import env as ENV         # noqa: E402
import discover as D      # noqa: E402
import download as DL     # noqa: E402
import report as R        # noqa: E402
import region_seeds as RS # noqa: E402  （地区名单生成：①层，纯函数，不联网）


# ============================================================================
# 协议基础
# ============================================================================
def _send(obj):
    """写一条 NDJSON 到真 stdout。"""
    try:
        data = (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")
        _proto.write(data)
        _proto.flush()
    except Exception:
        # 协议出口都写不了，只能放弃（不要往 stderr 倒垃圾再触发递归）
        pass


def _result(mid, result):
    _send({"jsonrpc": "2.0", "id": mid, "result": result})


def _error(mid, code, message, data=None):
    err = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    _send({"jsonrpc": "2.0", "id": mid, "error": err})


def _text(s):
    return {"type": "text", "text": s}


def _tool_ok(text, structured=None):
    out = {"content": [_text(text)], "isError": False}
    if structured is not None:
        out["structuredContent"] = structured
    return out


def _tool_err(text):
    return {"content": [_text(text)], "isError": True}


# ============================================================================
# 任务模型（后台线程 + 轮询/等待）
# ============================================================================
_JOBS = {}
_JOBS_LOCK = threading.Lock()
_OUT_LOCKS = {}
_OUT_LOCKS_GUARD = threading.Lock()
_JOB_SEQ = [0]


def _out_lock(out):
    """同一 out 目录串行（避免 _discover_tmp / jobs.json / records.json 竞争）。"""
    key = os.path.abspath(out)
    with _OUT_LOCKS_GUARD:
        lk = _OUT_LOCKS.get(key)
        if lk is None:
            lk = threading.Lock()
            _OUT_LOCKS[key] = lk
        return lk


_JOBS_KEEP = 200                     # 保留的「已完成」任务数上限（运行中的不淘汰）


def _prune_jobs_locked():
    """淘汰最老的已完成任务 + 其独占的 out 锁，防长命服务端无限增长。

    仅淘汰 done/error 的任务；queued/running 一律保留。锁只在没有任何存活任务
    引用其 out 时才丢弃（此时不可能有线程还在等它）。"""
    if len(_JOBS) > _JOBS_KEEP:
        finished = sorted((j for j in _JOBS.values()
                           if j["state"] in ("done", "error")),
                          key=lambda j: j["started"])
        for j in finished[:len(_JOBS) - _JOBS_KEEP]:
            _JOBS.pop(j["id"], None)
    live = set()
    for j in _JOBS.values():
        o = j.get("out")
        live.add(os.path.abspath(o) if o else os.path.abspath("_global"))
    with _OUT_LOCKS_GUARD:
        for k in list(_OUT_LOCKS):
            if k not in live:
                _OUT_LOCKS.pop(k, None)


def _new_job(tool, out):
    with _JOBS_LOCK:
        _JOB_SEQ[0] += 1
        jid = "%s-%d-%s" % (tool, _JOB_SEQ[0], os.urandom(2).hex())
        job = {"id": jid, "tool": tool, "state": "queued", "log": deque(maxlen=800),
               "result": None, "error": None, "out": out,
               "started": time.time(), "finished": None}
        _JOBS[jid] = job
        _prune_jobs_locked()
        return job


def _job_logger(job):
    """任务日志：默认只进环形缓冲（供 job_status/job_wait 回看）。

    仅在 EDU_MCP_LOG=1 时才同步到 stderr —— 默认不写 stderr 是刻意的：若客户端
    把 stderr 开成 PIPE 却不排空，持续写会写满管道、把任务线程阻塞死。真实 MCP
    客户端都会排空 stderr，但为对所有客户端都安全，默认静默。
    """
    def log(*parts):
        line = " ".join(str(p) for p in parts)
        job["log"].append(line)
        if _VERBOSE:
            try:
                sys.stderr.write("[%s] %s\n" % (job["id"], line))
                sys.stderr.flush()
            except Exception:
                pass
    return log


def _start_job(tool, out, fn):
    """起一个后台任务。fn(job, log) -> result。立即返回 job。"""
    job = _new_job(tool, out)

    def runner():
        lock = _out_lock(out) if out else _out_lock("_global")
        job["state"] = "running"
        log = _job_logger(job)
        try:
            with lock:
                res = fn(job, log)
            job["result"] = res
            job["state"] = "done"
        except Exception as e:                      # 业务失败不抛协议错，记进任务
            job["error"] = "%s: %s" % (type(e).__name__, e)
            job["state"] = "error"
            log("失败：%s" % job["error"])
            log(traceback.format_exc()[-1500:])     # 栈进环形缓冲，job_status 可见
        finally:
            job["finished"] = time.time()

    threading.Thread(target=runner, name="edu-job-%s" % job["id"], daemon=True).start()
    return job


def _job_brief(job):
    return {"job_id": job["id"], "state": job["state"], "tool": job["tool"],
            "out": job["out"]}


def _job_text(job):
    """给弱模型的下一步指引（照念即可）。"""
    if job["state"] in ("queued", "running"):
        return ("任务已启动：job_id=%s（%s，out=%s）。\n"
                "下一步：调用 job_wait 工具，参数 {\"job_id\": \"%s\", \"timeout_s\": 600}，"
                "等它跑完并取回摘要。" % (job["id"], job["tool"], job["out"], job["id"]))
    if job["state"] == "done":
        return "任务 %s 已完成。\n%s" % (job["id"], _summ_text(job.get("result")))
    return "任务 %s 结束于 %s：%s" % (job["id"], job["state"], job.get("error") or "")


def _summ_text(s):
    if isinstance(s, str):
        return s
    if isinstance(s, dict):
        return json.dumps(s, ensure_ascii=False, indent=1)
    return str(s)


def _job_wait(job, timeout_s):
    deadline = time.monotonic() + max(0, float(timeout_s or 0))
    while job["state"] in ("queued", "running"):
        if time.monotonic() >= deadline:
            break
        time.sleep(0.4)
    return job


# ============================================================================
# 参数小工具
# ============================================================================
def _norm_kinds(v):
    """把 kinds 归一成合法子集。

    · v is None（未指定）→ 全部类型
    · 显式给定 → 只保留合法项；**全非法时返回 []**（由调用方报错，不静默退回全部）
    """
    if v is None:
        return list(D.ALL_KINDS)
    if isinstance(v, str):
        v = [k.strip() for k in v.replace("，", ",").split(",") if k.strip()]
    return [k for k in v if k in D.ALL_KINDS]


def _default_out(out, school=None):
    """缺省产出目录 = <当前目录>/discover_out（绝对化，便于 read_artifacts 定位）。"""
    return os.path.abspath(out or os.path.join(os.getcwd(), "discover_out"))


def _ctx_summary(ctx, out, auto):
    s = ("学校：%s  域名：%s（apex=%s）\n"
         "可达主机：%s\n"
         "扫描页数 %s；命中栏目 %s；反爬拦截 %s\n"
         "确认可下载 %s；仅 HTML %s；未定 %s；耗时 %ss\n"
         "产出目录：%s\n"
         "（看人眼确认表：read_artifacts(which=\"candidates\")）"
         % (ctx.get("school"), ctx.get("domain"), ctx.get("apex"),
            ", ".join(ctx.get("allowed_hosts", []) or ["?"]),
            ctx.get("pages"), len(ctx.get("hits", [])), len(ctx.get("blocked", []) or []),
            ctx.get("confirmed"), ctx.get("html"), ctx.get("unverified"),
            ctx.get("elapsed"), out))
    if auto:
        s += "\n已自动下载并出台账（自动=是）。"
    else:
        s += "\n只侦察（未下载）。确认候选无误后，再调 harvest_school 跑 auto=true。"
    return s


# ============================================================================
# 下载 + 台账（不走 discover.step6_auto —— 那条会 sys.stdout.write 子进程输出）
# ============================================================================
def _download_and_ledger(out, log, exclude_school=None, resume=True, csv_only=False,
                         dest_sub="新增数据", existing_sha=None):
    jobs_path = os.path.join(out, "jobs.json")
    jobs = C.load_json(jobs_path, [])
    dest = os.path.join(out, dest_sub)
    records_path = os.path.join(out, "records.json")

    existing = DL.load_existing_sha(existing_sha) if existing_sha else None
    records = DL.run(jobs, dest, existing_sha=existing, records_path=records_path,
                     exclude_school=exclude_school, resume=resume, log=log)

    html_links = C.load_json(os.path.join(out, "html_links.json"), [])
    date = time.strftime("%Y-%m-%d")
    ledger = R.build_ledger(records, html_links, date)
    fail = [r for r in records if not r.get("file")]

    if not ENV.have("openpyxl") and not csv_only:
        raise ENV.DepError("openpyxl", "pip install openpyxl（或传 csv_only=true 只出 CSV）")

    p1, p2 = R.write_csvs(records, ledger, out, date, fail)
    xp = None
    try:
        xp = R.write_xlsx(records, ledger, out, date, csv_only=csv_only)
    except SystemExit as e:                 # write_xlsx 缺库时会 sys.exit(3)：兜住别杀服务
        log("write_xlsx 中断（SystemExit=%s）" % e)
    except Exception as e:
        log("write_xlsx 异常：%s" % e)

    ok = [r for r in records if r.get("file")]
    return {
        "out": out,
        "dest": dest,
        "jobs": len(jobs),
        "新增": sum(1 for r in ok if r.get("status") == "新增"),
        "已入库": len(ok),
        "未成功": len(fail),
        "链接台账": len(ledger),
        "csv": [p1, p2],
        "xlsx": xp,
        "台账": (xp or p1),
    }


# ============================================================================
# 工具实现
# ============================================================================
def _tool_env_check(_a):
    rows = [
        ("7z 解压器", ENV.find_7z()),
        ("curl", ENV.find_curl()),
        ("powershell", ENV.find_powershell()),
        ("[py] fitz (PyMuPDF)", ENV.have("fitz")),
        ("[py] openpyxl", ENV.have("openpyxl")),
        ("[py] docx (python-docx)", ENV.have("docx")),
    ]
    lines = ["== 环境探测（缺依赖会显性报错，不会静默降级）=="]
    miss = []
    for name, v in rows:
        if isinstance(v, tuple):
            lines.append("  %-22s OK  %s  (%s)" % (name, v[0], v[1]))
        elif v:
            lines.append("  %-22s OK  %s" % (name, v))
        else:
            lines.append("  %-22s --  未找到" % name)
            miss.append(name)
    if miss:
        lines.append("")
        lines.append("缺：%s" % ", ".join(miss))
        if any("curl" in m for m in miss):
            lines.append("  curl 缺失 → 无法下载/探测（Windows 10 1803+ 自带）。")
        if any("openpyxl" in m for m in miss):
            lines.append("  openpyxl 缺失 → 无法出 Excel 台账；可 pip install openpyxl，"
                         "或 build_ledger 传 csv_only=true。")
        if any("7z" in m for m in miss):
            lines.append("  解压器缺失 → 打包件（rar/zip）跳过，其余照常。")
    else:
        lines.append("环境完备。")
    lines.append("提示：EDU_7Z / EDU_CURL / EDU_POWERSHELL 可覆盖自动探测。")
    return _tool_ok("\n".join(lines))


def _as_list(v):
    """把标量/数组归一到字符串列表（弱模型可能只传一个字符串）。"""
    if v is None:
        return []
    if isinstance(v, str):
        return [v] if v.strip() else []
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    return []


def _inline_domains(obj):
    """把内联域名映射（dict 或 list）转成 {校名: (domain, source)}，与 region_seeds.load_domains 同形。"""
    out = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(k, str) and isinstance(v, str) and v.strip():
                out[k.strip()] = (RS.norm_domain(v), "user")
    elif isinstance(obj, list):
        for it in obj:
            if isinstance(it, dict) and it.get("school") and it.get("domain"):
                out[str(it["school"]).strip()] = (
                    RS.norm_domain(str(it["domain"])), it.get("source") or "user")
    return out


def _tool_region_seeds(a):
    """地区名单生成（①层）：省/城市/层次/预设 → seeds.json。纯本地、不联网、不猜域名。

    注意：**不直接调 RS.load_data / RS.load_domains** —— 那两支失败时会 sys.exit(2)，
    在常驻服务端里等于杀进程；改为自己用 C.load_json 读并校验，只复用纯函数 build/norm_domain。
    """
    provinces = _as_list(a.get("province"))
    cities = _as_list(a.get("city"))
    levels = _as_list(a.get("level"))
    preset = a.get("preset")
    names_file = a.get("names_file")
    data_path = a.get("data") or RS.DEFAULT_DATA
    out = a.get("out") or os.path.join(os.getcwd(), "region_seeds.json")

    if not (provinces or cities or preset or names_file):
        return _tool_err("至少要给筛选条件之一：province / city / preset(985|211) / names_file。"
                         "（不给条件＝全表 2952 校，通常不是本意。）")

    doc = C.load_json(data_path, None)
    if not doc or not isinstance(doc.get("schools"), list):
        return _tool_err("名单数据不可用：%s（可用 data 参数指向其它名单 JSON）。" % data_path)

    try:
        preset_names, preset_label = RS.load_preset(preset, names_file)
    except Exception as e:
        return _tool_err("读取预设/自定义名单失败：%s" % e)
    if (preset or names_file) and not preset_names:
        return _tool_err("预设/自定义名单为空或不可读：preset=%r names_file=%r" % (preset, names_file))

    dom_arg = a.get("domains")
    if isinstance(dom_arg, str) and dom_arg.strip():
        raw = C.load_json(dom_arg, None)
        if raw is None:
            return _tool_err("域名文件不可读（需 JSON）：%s" % dom_arg)
        domains = _inline_domains(raw)
    elif isinstance(dom_arg, (dict, list)):
        domains = _inline_domains(dom_arg)
    else:
        domains = {}

    try:
        result, unmatched = RS.build(doc, provinces, levels, preset_names,
                                     preset_label, cities, domains)
        C.save_json(result, out)
        if a.get("csv"):
            RS.write_csv(result["schools"], os.path.splitext(out)[0] + ".csv")
    except Exception as e:
        return _tool_err("生成名单失败：%s" % e)

    m = result["_meta"]
    rows = result["schools"]
    pending = [r["school"] for r in rows if not r["domain"]]

    filt = "、".join(x for x in [
        ("省=" + "/".join(m["filter"]["province"])) if m["filter"]["province"] else "",
        ("市=" + "/".join(m["filter"]["city"])) if m["filter"]["city"] else "",
        ("层次=" + "/".join(m["filter"]["level"])) if m["filter"]["level"] else "",
        ("预设=" + m["filter"]["preset"]) if m["filter"]["preset"] else "",
    ] if x)

    L = ["地区名单已生成 → %s" % out,
         "命中 %d 校%s；含域名 %d 校，待补域名 %d 校。"
         % (m["count"], ("（%s）" % filt) if filt else "", m["with_domain"], len(pending)),
         "",
         "⚠️ 名单口径（务必知悉）：",
         "  · 本名单＝教育部《全国普通高等学校名单》，仅普通高校（本科+专科）。",
         "  · 不含成人高校（教育部并列发布的另一份名单）——默认不采；确需可经 data / names_file 补入。",
         "  · 不含军队院校（国防科技大学等）——按 985/211 筛时在下方「未匹配」列出，不静默丢。",
         "  边界详见 resource edu://ref/10（references/10-地区批量.md §3.1）。"]
    if unmatched:
        L += ["", "未匹配（多为军校）：%s" % "、".join(unmatched)]
    L.append("")
    if pending:
        show = pending[:12]
        more = "" if len(pending) <= 12 else " 等 %d 校" % len(pending)
        L += ["下一步：",
              "  1) 对「待补域名」的学校，用联网搜索逐校解析官方 *.edu.cn（绝不猜），"
              "证据页 URL 写入 domain_source=\"agent:<URL>\"；",
              "  2) 调 harvest_many(schools=[{school,domain,…}], out=…) 逐校采集。",
              "待补域名（%d 校，前 12）：%s%s" % (len(pending), "、".join(show), more)]
    else:
        L.append("下一步：全部学校已带域名 → 直接 harvest_many(schools=…, out=…) 逐校采集。")

    return _tool_ok("\n".join(L), structured={
        "out": out, "count": m["count"], "with_domain": m["with_domain"],
        "pending": len(pending), "unmatched": unmatched})


def _tool_harvest_school(a, dry=False, tool="harvest_school"):
    school = a.get("school")
    domain = a.get("domain")
    if not school or not domain:
        return _tool_err("缺参数：school 与 domain 必填（domain 须为官方 *.edu.cn）。")
    kinds = _norm_kinds(a.get("kinds"))
    if not kinds:
        return _tool_err("kinds 需为 %s 的子集（收到 %r）。"
                         % ("/".join(D.ALL_KINDS), a.get("kinds")))
    out = _default_out(a.get("out"), school)
    auto = False if dry else bool(a.get("auto", True))
    no_sub = bool(a.get("no_subdomains", False))
    max_pages = int(a.get("max_pages") or 60)
    workers = int(a.get("workers") or 8)

    def fn(job, log):
        ctx = D.discover_one(school, domain, out, kinds, no_subdomains=no_sub,
                             max_pages=max_pages, dry_run=True, log=log, workers=workers)
        if auto and ctx.get("confirmed"):
            log("开始下载 + 出台账……")
            summ = _download_and_ledger(out, log)
            ctx["ledger"] = summ
        elif auto:
            log("无确认候选，跳过下载。")
        return _ctx_summary(ctx, out, auto)

    job = _start_job(tool, out, fn)
    return _tool_ok(_job_text(job))


def _tool_discover_school(a):
    return _tool_harvest_school(a, dry=True, tool="discover_school")


def _tool_harvest_many(a):
    """批量多校：逐校 discover（各自子目录）→ auto 时下载 + 台账。"""
    schools = a.get("schools")
    if not isinstance(schools, list) or not schools:
        return _tool_err("缺参数：schools 必填，形如 "
                         "[{\"school\":\"湖南大学\",\"domain\":\"hnu.edu.cn\"}, …]。")
    tasks = []
    for s in schools:
        if isinstance(s, dict) and s.get("school") and s.get("domain"):
            tasks.append((s["school"], s["domain"], s.get("kinds")))
    if not tasks:
        return _tool_err("schools 里没有可用项（每项需含 school 与 domain）。")
    default_kinds = a.get("kinds")
    auto = bool(a.get("auto", True))
    no_sub = bool(a.get("no_subdomains", False))
    max_pages = int(a.get("max_pages") or 60)
    workers = int(a.get("workers") or 8)
    root = _default_out(a.get("out"))

    def fn(job, log):
        lines = ["批量采集 %d 所学校 → %s" % (len(tasks), root)]
        for i, (school, domain, kd) in enumerate(tasks, 1):
            kinds = _norm_kinds(kd if kd else default_kinds) or list(D.ALL_KINDS)
            sub = os.path.join(root, C.safe_name(school, 40))
            log("[%d/%d] %s（%s）" % (i, len(tasks), school, domain))
            try:
                ctx = D.discover_one(school, domain, sub, kinds, no_subdomains=no_sub,
                                     max_pages=max_pages, dry_run=True, log=log,
                                     workers=workers)
                n = ctx.get("confirmed", 0)
                if auto and n:
                    summ = _download_and_ledger(sub, log)
                    lines.append("· %s：确认 %s 份，入库 %s 份 → %s"
                                 % (school, n, summ.get("已入库"), sub))
                else:
                    lines.append("· %s：确认 %s 份（未下载）→ %s" % (school, n, sub))
            except Exception as e:
                log("  %s 失败：%s" % (school, e))
                lines.append("· %s：失败 %s" % (school, e))
        lines.append("完成。各校产出在其子目录，台账见 <子目录>/采集台账.xlsx。")
        return "\n".join(lines)

    job = _start_job("harvest_many", root, fn)
    return _tool_ok(_job_text(job))


def _tool_harvest_pages(a, dry=False, tool="harvest_pages"):
    school = a.get("school")
    domain = a.get("domain")
    pages = a.get("pages") or []
    if not school or not domain:
        return _tool_err("缺参数：school 与 domain 必填。")
    if not isinstance(pages, list) or not pages:
        return _tool_err("缺参数：pages 必填，形如 [{\"url\":\"https://...\",\"kind\":\"培养方案\"}]"
                         "（kind 可省，用 auto 按页面标题自判）。")
    spec = []
    for p in pages:
        if isinstance(p, str):
            spec.append((p, None))
        elif isinstance(p, dict) and p.get("url"):
            spec.append((p["url"], p.get("kind") or None))
    if not spec:
        return _tool_err("pages 里没有可用 url。")
    kd = _norm_kinds(a.get("kinds")) if a.get("kinds") else None
    if a.get("kinds") and not kd:
        return _tool_err("kinds 需为 %s 的子集（收到 %r）。"
                         % ("/".join(D.ALL_KINDS), a.get("kinds")))
    # pages 每项可带 kind；kinds 作为允许集合（缺省=全部）
    kinds = kd or list(D.ALL_KINDS)
    out = _default_out(a.get("out"), school)
    auto = False if dry else bool(a.get("auto", True))
    workers = int(a.get("workers") or 8)

    def fn(job, log):
        ctx = D.discover_pages(school, domain, out, kinds, spec, dry_run=True,
                               log=log, workers=workers)
        if auto and ctx.get("confirmed"):
            log("开始下载 + 出台账……")
            ctx["ledger"] = _download_and_ledger(out, log)
        return _ctx_summary(ctx, out, auto)

    job = _start_job(tool, out, fn)
    return _tool_ok(_job_text(job))


def _tool_discover_pages_dry(a):
    return _tool_harvest_pages(a, dry=True, tool="discover_pages_dry")


def _tool_download_materials(a):
    out = a.get("out")
    if not out:
        return _tool_err("缺参数：out 必填（discover 产出目录，内含 jobs.json）。")
    out = os.path.abspath(out)
    if not os.path.exists(os.path.join(out, "jobs.json")):
        return _tool_err("在 %s 未找到 jobs.json。请先跑 harvest_school/discover_school。" % out)
    excl = a.get("exclude_school")
    resume = bool(a.get("resume", True))
    csv_only = bool(a.get("csv_only", False))
    existing = a.get("existing_sha") or None

    def fn(job, log):
        return _download_and_ledger(out, log, exclude_school=excl, resume=resume,
                                    csv_only=csv_only, existing_sha=existing)

    job = _start_job("download_materials", out, fn)
    return _tool_ok(_job_text(job))


def _tool_build_ledger(a):
    out = a.get("out")
    if not out:
        return _tool_err("缺参数：out 必填。")
    out = os.path.abspath(out)
    csv_only = bool(a.get("csv_only", False))
    if not ENV.have("openpyxl") and not csv_only:
        return _tool_err(
            "缺少依赖：openpyxl（Excel 台账是本工具核心产物）。\n"
            "  解决：pip install openpyxl；或传 csv_only=true 只出 CSV。")
    try:
        records = C.load_json(os.path.join(out, "records.json"), [])
        html_links = C.load_json(os.path.join(out, "html_links.json"), [])
        date = (a.get("date") or "").strip() or time.strftime("%Y-%m-%d")
        ledger = R.build_ledger(records, html_links, date)
        fail = [r for r in records if not r.get("file")]
        p1, p2 = R.write_csvs(records, ledger, out, date, fail)
        xp = None
        try:
            xp = R.write_xlsx(records, ledger, out, date, csv_only=csv_only)
        except SystemExit:
            xp = None
        ok = len([r for r in records if r.get("file")])
        return _tool_ok("台账已生成：入库 %d 份，链接台账 %d 行。\n文件：%s%s"
                        % (ok, len(ledger), (xp or p1),
                           ("\n      " + p2) if p2 else ""))
    except Exception as e:
        return _tool_err("出台账失败：%s" % e)


_ARTIFACTS = {
    "candidates": "candidates.md",
    "jobs": "jobs.json",
    "unverified": "unverified.json",
    "report": "discover_report.json",
    "html_links": "html_links.json",
    "records": "records.json",
    "ledger": "采集台账.xlsx",
}


def _tool_read_artifacts(a):
    out = a.get("out")
    which = (a.get("which") or "").strip()
    if not out:
        return _tool_err("缺参数：out 必填。")
    if which not in _ARTIFACTS:
        return _tool_err("which 须为 %s 之一。" % "/".join(_ARTIFACTS))
    path = os.path.join(os.path.abspath(out), _ARTIFACTS[which])
    if not os.path.exists(path):
        return _tool_err("未找到 %s（%s）。先跑发现/下载。" % (_ARTIFACTS[which], path))
    if which == "ledger":
        return _tool_ok("台账为二进制 xlsx，已生成：%s（请用 Excel 打开）。" % path)
    limit = 200000
    try:
        with open(path, "r", encoding="utf-8") as f:
            txt = f.read(limit + 1)          # 有界读取：别把超大文件整个读进内存
    except Exception as e:
        return _tool_err("读取失败：%s" % e)
    if len(txt) > limit:
        txt = txt[:limit] + "\n…（已截断，完整见 %s）" % path
    return _tool_ok(txt)


def _tool_job_status(a):
    jid = a.get("job_id")
    job = _JOBS.get(jid)
    if not job:
        return _tool_err("未知 job_id：%s" % jid)
    tail = list(job["log"])[-25:]
    lines = ["job_id=%s  工具=%s  状态=%s" % (job["id"], job["tool"], job["state"])]
    if job["state"] == "done":
        lines.append(_summ_text(job.get("result")))
    elif job["state"] == "error":
        lines.append("错误：%s" % job.get("error"))
    lines.append("— 最近日志 —")
    lines.extend(tail or ["（暂无）"])
    return _tool_ok("\n".join(lines))


def _tool_job_wait(a):
    jid = a.get("job_id")
    job = _JOBS.get(jid)
    if not job:
        return _tool_err("未知 job_id：%s" % jid)
    _job_wait(job, a.get("timeout_s") or 600)
    tail = list(job["log"])[-30:]
    lines = ["job_id=%s  状态=%s" % (job["id"], job["state"])]
    if job["state"] == "done":
        lines.append(_summ_text(job.get("result")))
    elif job["state"] in ("queued", "running"):
        lines.append("仍在运行（未在超时内完成）。可再次调用 job_wait 或 job_status 轮询。")
    else:
        lines.append("错误：%s" % (job.get("error") or ""))
    if tail:
        lines.append("— 最近日志 —")
        lines.extend(tail)
    return _tool_ok("\n".join(lines))


# ============================================================================
# 工具表
# ============================================================================
def _obj(props, req=None):
    return {"type": "object", "properties": props, "required": req or []}


_SCHOOL = {"type": "string", "description": "学校名，如「湖南大学」"}
_DOMAIN = {"type": "string", "description": "官方 *.edu.cn 域名，如 hnu.edu.cn。"
                                            "必须先用联网搜索确认，本工具绝不猜。"}
_KINDS = {"type": "array", "items": {"type": "string"},
          "description": "材料类型子集：培养方案 / 专业介绍 / 课程大纲 / 年度报告。缺省=全部。"}
_OUT = {"type": "string", "description": "产出目录（绝对路径更稳）。缺省=<当前目录>/discover_out。"}

TOOLS = [
    {"name": "env_check",
     "description": "检查本机依赖（curl / 解压器 / PowerShell / openpyxl 等）。"
                    "**第一个该调的工具**；缺依赖当场说清，避免后面「跑完啥也没有」。",
     "inputSchema": _obj({})},

    {"name": "region_seeds",
     "description": "【地区批量·第一步】按 省/城市/层次/预设(985·211) 或自定义名单生成高校 seeds.json"
                    "（纯本地、不联网、不猜域名、可复现）。至少给一个筛选条件。输出会列「待补域名」"
                    "的学校——需你联网搜官方 *.edu.cn 补上，再交 harvest_many 采集。"
                    "名单口径：仅普通高校（不含成人高校与军队院校），详见 resource edu://ref/10。",
     "inputSchema": _obj({
         "province": {"type": "array", "items": {"type": "string"},
                      "description": "省级，可多个：[\"湖南\"] 或 [\"湖北\",\"湖南\"]（简写即可）。也接受单个字符串。"},
         "city": {"type": "array", "items": {"type": "string"},
                  "description": "所在地城市，精确匹配，可多个。可选。"},
         "level": {"type": "array", "items": {"type": "string", "enum": ["本科", "专科"]},
                   "description": "办学层次，可多个。可选。"},
         "preset": {"type": "string", "enum": ["985", "211"], "description": "预设名单。可选。"},
         "names_file": {"type": "string",
                        "description": "自定义名单文件路径（每行一校名，或 JSON {\"names\":[…]}）。可选。"},
         "domains": {"description": "用户提供的域名映射：文件路径（字符串），或内联 "
                     "{\"湖南大学\":\"hnu.edu.cn\"} / [{\"school\":\"湖南大学\",\"domain\":\"hnu.edu.cn\",\"source\":\"…\"}]。可选。"},
         "data": {"type": "string",
                  "description": "覆盖内置名单 JSON 路径（缺省=教育部《全国普通高等学校名单》）。"},
         "csv": {"type": "boolean", "description": "同时输出同名 .csv。默认 false。"},
         "out": {"type": "string",
                 "description": "输出 seeds.json 路径（缺省=<当前目录>/region_seeds.json）。"}})},
    {"name": "harvest_school",
     "description": "【一键·推荐】给定学校名 + 官方域名，自动完成：全站发现 → 下载 → "
                    "去重 → 出台账。适合导航规整的站。返回 job_id，"
                    "随后用 job_wait 等待并取摘要。",
     "inputSchema": _obj({
         "school": _SCHOOL, "domain": _DOMAIN, "kinds": _KINDS,
         "auto": {"type": "boolean", "description": "true=发现后直接下载出台账；false=只侦察。默认 true。"},
         "no_subdomains": {"type": "boolean", "description": "跳过子域探测。默认 false。"},
         "max_pages": {"type": "integer", "description": "导航爬取页数上限，默认 60。"},
         "workers": {"type": "integer", "description": "并发抓取数，默认 8。"},
         "out": _OUT}, ["school", "domain"])},

    {"name": "harvest_many",
     "description": "【批量·一键】给多所学校（各带官方域名）批量跑：发现 → 下载 → 台账。"
                    "每校产出到 <out>/<校名>/ 子目录。返回 job_id，用 job_wait 等完成。",
     "inputSchema": _obj({
         "schools": {"type": "array", "description":
                     "[{\"school\":\"湖南大学\",\"domain\":\"hnu.edu.cn\",\"kinds\":[…]}, …]",
                     "items": {"type": "object", "properties": {
                         "school": {"type": "string"}, "domain": {"type": "string"},
                         "kinds": {"type": "array", "items": {"type": "string"}}}}},
         "kinds": _KINDS,
         "auto": {"type": "boolean", "description": "true=发现后直接下载出台账。默认 true。"},
         "no_subdomains": {"type": "boolean"},
         "max_pages": {"type": "integer"},
         "workers": {"type": "integer"},
         "out": _OUT}, ["schools"])},

    {"name": "harvest_pages",
     "description": "【精准·大站推荐】指定承载页直采：先由你会联网搜索定位到「挂着材料的"
                    "那一页」，把 URL 交给本工具枚举附件 → 下载 → 出台账。"
                    "用于全站爬不动（子域被 WAF 挡）或爬出一堆假货（新闻/招生页误命中）时。",
     "inputSchema": _obj({
         "school": _SCHOOL, "domain": _DOMAIN,
         "pages": {"type": "array", "description": "承载页列表：[{\"url\": \"https://...\", "
                   "\"kind\": \"培养方案\"}]。kind 可省略（按页面标题自判）。",
                   "items": {"type": "object", "properties": {
                       "url": {"type": "string"}, "kind": {"type": "string"}}}},
         "kinds": _KINDS,
         "auto": {"type": "boolean", "description": "true=直接下载出台账。默认 true。"},
         "workers": {"type": "integer"},
         "out": _OUT}, ["school", "domain", "pages"])},

    {"name": "discover_school",
     "description": "只侦察（不下载）：全站发现，产出候选确认表。确认无误后再 harvest_school。",
     "inputSchema": _obj({
         "school": _SCHOOL, "domain": _DOMAIN, "kinds": _KINDS,
         "no_subdomains": {"type": "boolean"}, "max_pages": {"type": "integer"},
         "out": _OUT}, ["school", "domain"])},

    {"name": "discover_pages_dry",
     "description": "只侦察（不下载）：指定承载页枚举，产出候选确认表。",
     "inputSchema": _obj({
         "school": _SCHOOL, "domain": _DOMAIN,
         "pages": {"type": "array", "items": {"type": "object", "properties": {
             "url": {"type": "string"}, "kind": {"type": "string"}}}},
         "out": _OUT}, ["school", "domain", "pages"])},

    {"name": "download_materials",
     "description": "对已侦察的 out 目录（含 jobs.json）执行下载 + 去重 + 出台账。",
     "inputSchema": _obj({
         "out": _OUT,
         "exclude_school": {"type": "string", "description": "补漏时剔除该校已有记录，防自比。"},
         "existing_sha": {"type": "string", "description":
                          "存量 sha1 的 json 路径（如 03_content_probe.json），用于跨批去重。"},
         "csv_only": {"type": "boolean", "description": "缺 openpyxl 时的降级：只出 CSV。"},
         "resume": {"type": "boolean", "description": "断点续跑（默认 true）。"}},
         ["out"])},

    {"name": "build_ledger",
     "description": "对已有 records.json 重新出台账（xlsx 5 表 + 2 CSV）。",
     "inputSchema": _obj({"out": _OUT,
         "csv_only": {"type": "boolean"},
         "date": {"type": "string", "description": "台账日期 YYYY-MM-DD（缺省=今天）。"}},
         ["out"])},

    {"name": "read_artifacts",
     "description": "读取 out 目录里的产物，让 Agent「看见」结果而不必开 shell。",
     "inputSchema": _obj({
         "out": _OUT,
         "which": {"type": "string",
                   "enum": ["candidates", "jobs", "unverified", "report",
                            "html_links", "records", "ledger"]}},
         ["out", "which"])},

    {"name": "job_status",
     "description": "查后台任务状态 + 最近日志（非阻塞）。",
     "inputSchema": _obj({"job_id": {"type": "string"}}, ["job_id"])},

    {"name": "job_wait",
     "description": "等待后台任务完成（阻塞至多 timeout_s 秒），返回终态摘要。"
                    "不会循环轮询的弱模型用这个。",
     "inputSchema": _obj({
         "job_id": {"type": "string"},
         "timeout_s": {"type": "integer", "description": "最长等待秒数，默认 600。"}},
         ["job_id"])},
]

TOOL_FUNCS = {
    "env_check": _tool_env_check,
    "region_seeds": _tool_region_seeds,
    "harvest_school": _tool_harvest_school,
    "harvest_many": _tool_harvest_many,
    "harvest_pages": _tool_harvest_pages,
    "discover_school": _tool_discover_school,
    "discover_pages_dry": _tool_discover_pages_dry,
    "download_materials": _tool_download_materials,
    "build_ledger": _tool_build_ledger,
    "read_artifacts": _tool_read_artifacts,
    "job_status": _tool_job_status,
    "job_wait": _tool_job_wait,
}


# ============================================================================
# Resources（让客户端可自动加载上下文）
# ============================================================================
_RESOURCES = [
    ("edu://manual", "SKILL.md", "采集 skill 总纲：原则 / 流程 / 陷阱 / 教训", "text/markdown"),
    ("edu://ref/00", "00-通用纪律.md", "只采官方源·免登录·回收站·编码·原始数据只读", "text/markdown"),
    ("edu://ref/01", "01-培养方案.md", "培养方案：来源形态与枚举手法", "text/markdown"),
    ("edu://ref/02", "02-专业介绍.md", "专业介绍：来源形态与枚举手法", "text/markdown"),
    ("edu://ref/03", "03-课程大纲.md", "课程大纲：来源形态与枚举手法", "text/markdown"),
    ("edu://ref/04", "04-年度报告.md", "年度报告：来源形态与枚举手法", "text/markdown"),
    ("edu://ref/05", "05-检索与反爬.md", "检索与反爬：边界与对策", "text/markdown"),
    ("edu://ref/07", "07-来源清单与模板.md", "来源清单：示例表 + 模板 + 新增一校四步", "text/markdown"),
    ("edu://ref/08", "08-自动发现逻辑.md", "自动发现引擎：判据 / 三重防线 / 边界（技术逻辑）", "text/markdown"),
    ("edu://ref/09", "09-Agent接入与MCP.md", "跨 Agent 接入与 MCP：架构 / 协议 / 工具 / 排障", "text/markdown"),
    ("edu://ref/10", "10-地区批量.md", "地区批量：省/985·211 → 逐校；名单口径三分（普通高校 / 成人高校 / 军校）", "text/markdown"),
]


def _res_index():
    return [{"uri": u, "name": fn, "description": d, "mimeType": m}
            for (u, fn, d, m) in _RESOURCES]


def _res_read(uri):
    for (u, fn, _d, m) in _RESOURCES:
        if u == uri:
            path = os.path.join(SKILL_DIR if fn == "SKILL.md" else REFS, fn)
            if not os.path.exists(path):
                return None
            with open(path, "r", encoding="utf-8") as f:
                return {"uri": uri, "mimeType": m, "text": f.read()}
    return None


# ============================================================================
# Prompts（把「有序调用配方」直接喂给弱模型）
# ============================================================================
_PROMPTS = [{
    "name": "edu:harvest-school",
    "description": "采集某校四类公开材料的「照念即用」流程配方。",
    "arguments": [
        {"name": "school", "required": True, "description": "学校名"},
        {"name": "domain", "required": True, "description": "官方 *.edu.cn 域名"},
        {"name": "kinds", "required": False, "description": "材料类型，逗号分隔"},
    ],
}]


def _prompt_get(name, args):
    if name != "edu:harvest-school":
        return None
    school = (args or {}).get("school", "<学校名>")
    domain = (args or {}).get("domain", "<域名>")
    kinds = (args or {}).get("kinds", "")
    text = (
        "目标：采集 %s（域名 %s）的培养方案 / 专业介绍 / 课程大纲 / 年度报告，"
        "逐份落盘并登记可溯源台账。%s\n\n"
        "严格按此顺序调用工具（不要跳步）：\n"
        "1) env_check —— 先确认本机有 curl / openpyxl，缺什么当场告诉用户。\n"
        "2) 首选 harvest_school {\"school\":\"%s\",\"domain\":\"%s\"%s}；"
        "若该站子域被 WAF 挡、或爬出的候选明显不是材料（新闻/招生页），"
        "改用 harvest_pages（你自己联网搜到「挂着材料的那一页」的 URL 再传）。\n"
        "3) 工具会立即返回 job_id。调用 job_wait {\"job_id\":\"...\",\"timeout_s\":600} 等它跑完。\n"
        "   （多校批量改调 harvest_many {\"schools\":[{\"school\":\"...\",\"domain\":\"...\"}, …]}，逐校产出到子目录。）\n"
        "4) 调 read_artifacts {\"out\":\"<上一步返回的 out>\",\"which\":\"candidates\"} "
        "看人眼确认表，向用户汇报确认了几份、类型分布。\n"
        "5) 完成后告诉用户台账文件位置（<out>/采集台账.xlsx）与来源直链可溯源。\n\n"
        "红线：绝不猜域名（domain 必须联网确认）；绝不编 URL（引擎逐条实测）；"
        "只采官方免登录公开源。"
        % (school, domain, ("类型限定：%s。" % kinds) if kinds else "", school, domain,
           (",\"kinds\":[\"%s\"]" % kinds) if kinds else "")
    )
    return {"description": "采集 %s 的公开材料" % school,
            "messages": [{"role": "user", "content": _text(text)}]}


# ============================================================================
# 协议分发
# ============================================================================
def _dispatch(msg):
    mid = msg.get("id")
    method = msg.get("method")
    params = msg.get("params") or {}

    # 通知（无 id）一律不回
    if method == "notifications/initialized" or (mid is None and method and
                                                 method.startswith("notifications/")):
        return
    if method in ("notifications/cancelled",):
        return

    if method == "initialize":
        pv = params.get("protocolVersion")
        ver = pv if pv in SUPPORTED_PROTOCOLS else DEFAULT_PROTOCOL
        _result(mid, {
            "protocolVersion": ver,
            "capabilities": {"tools": {"listChanged": False},
                             "resources": {"listChanged": False},
                             "prompts": {"listChanged": False}},
            "serverInfo": {"name": NAME, "version": VERSION},
            "instructions": INSTRUCTIONS,
        })
        return

    if method == "ping":
        _result(mid, {})
        return

    if method in ("logging/setLevel", "resources/subscribe", "resources/unsubscribe"):
        _result(mid, {})
        return

    if method == "tools/list":
        _result(mid, {"tools": TOOLS})
        return

    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        fn = TOOL_FUNCS.get(name)
        if not fn:
            _result(mid, _tool_err("未知工具：%s" % name))
            return
        try:
            _result(mid, fn(args))
        except ENV.DepError as e:
            _result(mid, _tool_err(str(e)))
        except Exception as e:
            _result(mid, _tool_err("工具执行失败：%s\n%s"
                                   % (e, traceback.format_exc()[-1500:])))
        return

    if method == "resources/list":
        _result(mid, {"resources": _res_index()})
        return

    if method == "resources/read":
        uri = params.get("uri")
        got = _res_read(uri)
        if got is None:
            _error(mid, -32602, "未知资源：%s" % uri)
            return
        _result(mid, {"contents": [got]})
        return

    if method == "prompts/list":
        _result(mid, {"prompts": _PROMPTS})
        return

    if method == "prompts/get":
        got = _prompt_get(params.get("name"), params.get("arguments"))
        if got is None:
            _error(mid, -32602, "未知 prompt：%s" % params.get("name"))
            return
        _result(mid, got)
        return

    if mid is None:
        return
    _error(mid, -32601, "未知方法：%s" % method)


def serve():
    _in = getattr(sys.stdin, "buffer", None)
    if _in is None:
        try:
            _in = os.fdopen(os.dup(0), "rb")
        except Exception:
            return
    while True:
        try:
            raw = _in.readline()
        except Exception:
            break
        if not raw:
            break                                   # EOF：客户端关闭
        line = raw.strip()
        if not line:
            continue
        try:
            msg = json.loads(line.decode("utf-8"))
        except Exception:
            _error(None, -32700, "JSON 解析失败")
            continue
        try:
            _dispatch(msg)
        except Exception as e:
            _error(msg.get("id"), -32603, "内部错误：%s" % e)


# ============================================================================
# 客户端自助接入：--print-config / --install
# ============================================================================
def _restore_stdout():
    """CLI 模式（--print-config / --install / --version）下把 fd1 还原到真 stdout。

    serve() 不需要：协议出口 _proto 独立于 fd1，fd1 指哪儿都不影响协议流。
    但 CLI 模式的输出是「给人看的」，必须落回真 stdout，否则 `--print-config > f`
    会得到空文件（输出被屏蔽到 stderr 了）。
    """
    try:
        os.dup2(_REAL_OUT, 1)          # fd1 → 真 stdout（_REAL_OUT 仍归 _proto 持有）
    except Exception:
        return
    try:
        sys.stdout = os.fdopen(os.dup(1), "w", encoding="utf-8",
                               errors="replace", buffering=1)
    except Exception:
        pass


def _config_block():
    py = sys.executable or "python"
    script = os.path.abspath(__file__)
    return py, script, {"mcpServers": {NAME: {"command": py, "args": [script]}}}


def print_config():
    py, script, block = _config_block()
    print("=" * 68)
    print("高校公开资料采集 · MCP 通用连接信息")
    print("=" * 68)
    print("command（解释器）: %s" % py)
    print("args   （服务脚本）: %s" % script)
    print()
    print("通用 MCP 配置（粘到客户端的 mcpServers / 连接器配置里）：")
    print(json.dumps(block, ensure_ascii=False, indent=2))
    print()
    print("客户端专用：")
    print("  Claude Code: python mcp_server.py --install claude")
    print("  Codex      : python mcp_server.py --install codex")
    print("  WorkBuddy  : 在「连接器（MCP）」里新建，命令与参数填上面的 command/args")
    print("  千问办公    : 在其自定义工具/MCP 入口填上面的 command/args")
    print()
    print("⚠️ 若客户端找不到 python（PATH 里没有），请把 command 换成上面的绝对路径。")


def install(client):
    py, script, _ = _config_block()
    client = (client or "").lower()
    if client in ("claude", "claude-code", "claudecode"):
        cmd = ["claude", "mcp", "add", NAME, "-s", "user", "--", py, script]
    elif client in ("codex",):
        cmd = ["codex", "mcp", "add", NAME, "--", py, script]
    else:
        print("暂不支持的客户端：%s（可选 claude / codex）" % client)
        print("其它客户端请用 --print-config 输出的通用配置手动添加。")
        return 1
    exe = shutil.which(cmd[0])
    if exe is None:
        print("未找到可执行文件：%s。请确认已安装并加入 PATH。" % cmd[0])
        print("将执行：%s" % " ".join(cmd))
        return 1
    # Windows 上 codex/claude 可能是 .cmd/.bat 垫片，CreateProcess 跑不了 → 经 cmd.exe
    run_cmd = [exe] + cmd[1:]
    if os.name == "nt" and exe.lower().endswith((".cmd", ".bat")):
        run_cmd = ["cmd", "/c", exe] + cmd[1:]
    print("将执行：%s" % " ".join(cmd))
    try:
        r = subprocess.run(run_cmd, capture_output=True, text=True, timeout=120,
                          encoding="utf-8", errors="replace")
    except Exception as e:
        print("执行失败：%s" % e)
        return 1
    print("返回码：%d" % r.returncode)
    if r.stdout:
        print(r.stdout.strip())
    if r.stderr:
        print(r.stderr.strip())
    if r.returncode == 0:
        print("\n完成。验证：")
        if client.startswith("claude"):
            print("  claude mcp list   # 看到 %s 即成功" % NAME)
        else:
            print("  codex mcp get %s" % NAME)
    return r.returncode


def main():
    argv = sys.argv[1:]
    if "--print-config" in argv or "--install" in argv or "--version" in argv:
        _restore_stdout()
    if "--print-config" in argv:
        print_config()
        return 0
    if "--install" in argv:
        i = argv.index("--install")
        client = argv[i + 1] if i + 1 < len(argv) else ""
        return install(client)
    if "--version" in argv:
        print("%s %s" % (NAME, VERSION))
        return 0
    serve()
    return 0


if __name__ == "__main__":
    sys.exit(main())

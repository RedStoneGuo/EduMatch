# -*- coding: utf-8 -*-
"""高校公开资料采集 · 自检

改动脚本后跑一遍，全 PASS（SKIP 不算失败）才算无回退。

    python scripts/selftest.py            # 全部（含可移植 grep 断言）
    python scripts/selftest.py --no-net   # 离线模式（跳过任何联网断言）

三类结果：
    PASS  通过
    SKIP  本机缺依赖（不算失败；如没装解压器只是跳过 find_7z 的存在性检查）
    FAIL  真失败（要修）

设计原则：**缺依赖要 SKIP，不要 FAIL**——别人机器上没 7z 不该判 skill 坏。
"""
import os
import re
import sys
import argparse
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C   # noqa: E402  （导入即完成 stdout utf-8 重配置）
import env           # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(HERE)

PASS, SKIP, FAIL = [], [], []


def t(name, cond):
    (PASS if cond else FAIL).append(name)


def skip(name, why):
    SKIP.append("%s（%s）" % (name, why))


def _raises_dep(fn):
    try:
        fn()
    except env.DepError:
        return True
    except Exception:
        return False
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-net", action="store_true", help="离线：跳过联网断言")
    a = ap.parse_args()

    # ---------------- 编码 ----------------
    t("decode_gbk", C.decode("培养方案（2025版）".encode("gbk")) == "培养方案（2025版）")
    t("decode_utf8", C.decode("培养方案".encode("utf-8")) == "培养方案")

    # ---------------- 魔数 ----------------
    d = tempfile.mkdtemp()
    samples = {"pdf": b"%PDF-1.7", "docx": b"PK\x03\x04", "rar": b"Rar!\x1a\x07\x00",
               "doc": b"\xd0\xcf\x11\xe0\xa1\xb1", "zip": b"PK\x03\x04"}
    for ext, head in samples.items():
        p = os.path.join(d, "s." + ext)
        open(p, "wb").write(head + b"\x00" * 100)
        t("magic_" + ext, C.magic_ok(p, ext))
    p = os.path.join(d, "fake.pdf")
    open(p, "wb").write(b"<!DOCTYPE html>" + b"\x00" * 100)
    t("magic_reject_html", C.magic_ok(p, "pdf") is False)
    p = os.path.join(d, "small.pdf")
    open(p, "wb").write(b"%PDF-1.7")
    t("valid_small_false", C.valid(p, "pdf") is False)

    # ---------------- 命名 ----------------
    r = C.safe_name('a/b\\c:d*e?f"g<h>i|j')
    t("safe_name_clean", all(ch not in r for ch in '/\\:*?"<>|'))
    t("safe_name_illegal_to_underscore", C.safe_name("***") == "___")
    t("safe_name_empty", C.safe_name("") == "unnamed")
    t("ascii_url_ok", C.ascii_path_url("https://x.edu.cn/a/b.pdf"))
    t("ascii_url_bad", C.ascii_path_url("https://x.edu.cn/a/专业.pdf") is False)
    t("url_quote", "%E4%B8%93%E4%B8%9A" in C.url_quote("https://x.edu.cn/a/专业.pdf"))
    t("url_quote_keep_slash", "/a/" in C.url_quote("https://x.edu.cn/a/专业.pdf"))

    # ---------------- env 契约（缺失=SKIP，不当 FAIL）----------------
    z = env.find_7z()
    if z is None:
        skip("find_7z_exists", "本机无解压器")
        t("require_7z_raises", _raises_dep(env.require_7z))
    else:
        t("find_7z_exists", os.path.exists(z[0]))
        t("find_7z_flavor", z[1] in ("7z", "bandizip"))

    cu = env.find_curl()
    if cu is None:
        skip("find_curl_exists", "本机无 curl")
        t("require_curl_raises", _raises_dep(env.require_curl))
    else:
        t("find_curl_exists", os.path.exists(cu))

    ps = env.find_powershell()
    t("find_powershell_none_or_exists", ps is None or os.path.exists(ps))

    # ---------------- 回收站契约（缺 PowerShell 时隔离，不静默丢）----------------
    import shutil as _sh
    _real = env.find_powershell
    try:
        env.find_powershell = lambda: None      # 假装无 PowerShell
        qdir = os.path.join(d, "recycle_q")
        victim = os.path.join(d, "victim.txt")
        open(victim, "w").write("x")
        C.recycle(victim, tmp=qdir)
        moved = (not os.path.exists(victim)) and os.path.exists(os.path.join(qdir, "victim.txt"))
        t("recycle_quarantine_when_no_ps", moved)   # 文件移位，不是永久删
    finally:
        env.find_powershell = _real

    # ---------------- 防假货：分类强度 / 栏目黑名单 / 附件黑名单 ----------------
    import discover as D

    # classify：锚文本命中=强信号；仅 URL 碰巧含词=弱信号
    k, n, strong = D.classify("培养方案", "https://jwb.bit.edu.cn/x/pyfa.htm")
    t("classify_anchor_strong", k == "培养方案" and strong)
    k, n, strong = D.classify("新闻中心", "https://www.bit.edu.cn/xwzx/人才培养方案.htm")
    t("classify_url_only_weak", k == "培养方案" and strong is False)

    # 栏目黑名单：新闻/通知/科研公开/党建 命中；正规材料栏目不命中
    for bad in ["https://www.bit.edu.cn/xwzx/1.htm", "https://www.bit.edu.cn/tzgg/a.htm",
                "https://www.bit.edu.cn/mkzxky/b.htm", "https://www.bit.edu.cn/dangjian/"]:
        t("neg_section_%s" % bad.rsplit("/", 2)[-2], bool(D.NEG_SECTION.search(bad)))
    for good in ["https://jwb.bit.edu.cn/old/dlpy/zysz/a456.htm",
                 "https://xxgk.bit.edu.cn/bkjxzlbg/", "https://jwc.bit.edu.cn/pyfa.htm"]:
        t("neg_section_safe_%s" % good.split("/")[3], not D.NEG_SECTION.search(good))

    # 附件黑名单：报名表/申请表等剔除；真材料放过
    for bad in ["报名表.docx", "2024年申请表.pdf", "x/汇总表.xls"]:
        t("neg_attach_%s" % re.sub(r"\W", "", bad), bool(D.NEG_ATTACH.search(bad)))
    for good in ["培养方案.pdf", "2024-2025学年本科教学质量报告.pdf", "教学大纲.pdf"]:
        t("neg_attach_safe_%s" % re.sub(r"\W", "", good), not D.NEG_ATTACH.search(good))

    # 词表收紧：宽泛词「信息公开」已剔除，「科研项目信息公开」不再判成年度报告
    t("kw_no_gongkai", all("信息公开" not in kws for _k, kws in D.KW_TABLE))
    t("classify_gongkai_none", D.classify("科研项目信息公开", "https://x.edu.cn/mkzxky/")[0] is None)
    # 招生宣传词已从「专业介绍」剔除；招生网 CMS 路径进黑名单
    t("kw_no_zhaosheng", all("招生简章" not in kws and "招生专业" not in kws for _k, kws in D.KW_TABLE))
    t("neg_section_newscenter", bool(D.NEG_SECTION.search("https://x.edu.cn/f/newsCenter/article/ab")))
    t("neg_section_article", bool(D.NEG_SECTION.search("https://admission.x.edu.cn/f/article/1.htm")))
    t("is_root_url_true", D._is_root_url("https://job.bit.edu.cn/"))
    t("is_root_url_false", D._is_root_url("https://x.edu.cn/pyfa/list.htm") is False)

    # keep_as_hit：弱信号 / 首页 / 黑名单栏目 → 不收；正规强信号栏目 → 收
    t("hit_strong_ok", D.keep_as_hit("培养方案", 1, True, "https://jwb.bit.edu.cn/pyfa.htm", D.ALL_KINDS))
    t("hit_weak_drop", D.keep_as_hit("培养方案", 1, False, "https://www.bit.edu.cn/xwzx/1.htm", D.ALL_KINDS) is False)
    t("hit_homepage_drop", D.keep_as_hit("培养方案", 0, True, "https://www.bit.edu.cn/", D.ALL_KINDS) is False)
    t("hit_negsec_drop", D.keep_as_hit("年度报告", 1, True, "https://www.bit.edu.cn/tzgg/a.htm", D.ALL_KINDS) is False)
    t("hit_root_drop", D.keep_as_hit("年度报告", 1, True, "https://job.bit.edu.cn/", D.ALL_KINDS) is False)

    # ---------------- 指定承载页直采（离线：桩掉网络，跑通全流程）----------------
    t("discover_has_pages_fn", callable(getattr(D, "discover_pages", None)))
    page_html = (
        "<html><head><title>本科培养方案</title></head><body>"
        '<a href="https://jwb.bit.edu.cn/a/1.pdf">培养方案（2025）</a>'
        '<a href="https://jwb.bit.edu.cn/a/2.pdf">培养方案（2024）</a>'
        '<a href="https://jwb.bit.edu.cn/a/%E6%8A%A5%E5%90%8D%E8%A1%A8.pdf">报名表</a>'
        "</body></html>")

    def _fake_probe(url, work, maxt=25, ref=None):
        ext = url.rsplit(".", 1)[-1].lower()
        head = b"%PDF-1.7" + b"\x00" * 64 if ext == "pdf" else b""
        return {"url": url, "status": 206, "ctype": "application/pdf", "effective": url,
                "redirects": 0, "head": head, "size": 12345}

    _rc, _rp = C.curl, D.probe
    try:
        C.curl = lambda url, **kw: page_html.encode("utf-8")
        D.probe = _fake_probe
        out2 = os.path.join(d, "pages_out")
        ctx = D.discover_pages("北京理工大学", "bit.edu.cn", out2, list(D.ALL_KINDS),
                              [("https://jwb.bit.edu.cn/old/dlpy/zysz/a456.htm", "培养方案")],
                              dry_run=True, log=lambda *a, **k: None, workers=2)
        t("pages_confirmed_2_of_3", ctx["confirmed"] == 2)              # 报名表被 NEG_ATTACH 剔除
        t("pages_jobs_written", os.path.exists(os.path.join(out2, "jobs.json")))
        cross = False
        try:
            D.discover_pages("北京理工大学", "bit.edu.cn", os.path.join(d, "x_out"),
                             list(D.ALL_KINDS),
                             [("https://evil.edu.cn/x.htm", "培养方案")],
                             dry_run=True, log=lambda *a, **k: None, workers=1)
        except RuntimeError:
            cross = True
        t("pages_crossdomain_reject", cross)                            # 跨 apex 全丢 → 报错
    finally:
        C.curl, D.probe = _rc, _rp

    # ---------------- MCP 服务端（离线握手：屏蔽生效 + 行级纯净 + 工具契约）----------------
    import json as _json
    import subprocess as _sp

    def _mcp_roundtrip(msgs, timeout=40):
        """起 server → 喂 NDJSON → 收 stdout。返回 (可用行列表, 原始stdout, stderr)。"""
        srv = os.path.join(HERE, "mcp_server.py")
        p = _sp.Popen([sys.executable, srv], stdin=_sp.PIPE, stdout=_sp.PIPE, stderr=_sp.PIPE)
        inp = ("\n".join(_json.dumps(m, ensure_ascii=False) for m in msgs) + "\n").encode("utf-8")
        out, err = p.communicate(inp, timeout=timeout)
        raw = out.decode("utf-8", "replace")
        return [l for l in raw.split("\n") if l.strip()], raw, err

    if not os.path.exists(os.path.join(HERE, "mcp_server.py")):
        skip("mcp_*", "无 mcp_server.py")
    else:
        _msgs = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                        "clientInfo": {"name": "selftest", "version": "1"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
             "params": {"name": "env_check", "arguments": {}}},
            {"jsonrpc": "2.0", "id": 4, "method": "resources/list"},
            {"jsonrpc": "2.0", "id": 5, "method": "tools/call",
             "params": {"name": "read_artifacts",
                        "arguments": {"out": os.path.join(d, "__none__"), "which": "candidates"}}},
            {"jsonrpc": "2.0", "id": 6, "method": "nope/method"},
            {"jsonrpc": "2.0", "id": 7, "method": "tools/call",
             "params": {"name": "region_seeds",
                        "arguments": {"province": ["湖北"], "preset": "985",
                                      "out": os.path.join(d, "_rs_selftest.json")}}},
        ]
        try:
            _lines, _raw, _err = _mcp_roundtrip(_msgs)
        except Exception as e:
            _lines, _raw, _err = [], "", str(e)

        _parsed, _bad = [], []
        for l in _lines:                       # 行级纯净：每行都必须是合法 JSON
            try:
                _parsed.append(_json.loads(l))
            except Exception:
                _bad.append(l[:80])
        t("mcp_all_lines_json", len(_lines) == 7 and not _bad)   # 7 条响应（通知不回）
        # 首行必须是 initialize 结果：证明 stdout 屏蔽生效（没有先前的 print 污染）
        t("mcp_first_line_is_initialize",
          bool(_parsed) and _parsed[0].get("id") == 1 and "serverInfo" in _parsed[0].get("result", {}))
        _by_id = {m.get("id"): m for m in _parsed if "id" in m}
        # initialize 回协商后的协议版本
        t("mcp_protocol_echo",
          _by_id.get(1, {}).get("result", {}).get("protocolVersion") in (("2025-06-18"), ("2024-11-05")))
        # tools/list：粗粒度工具齐（含一键 harvest_school 与 job_wait）
        _tools = {x["name"] for x in _by_id.get(2, {}).get("result", {}).get("tools", [])}
        t("mcp_tools_present",
          {"env_check", "region_seeds", "harvest_school", "harvest_many", "harvest_pages",
           "job_wait", "read_artifacts"} <= _tools)
        # initialize 回 instructions（弱客户端可据此照做）
        t("mcp_instructions_present",
          bool(_by_id.get(1, {}).get("result", {}).get("instructions")))
        # tools/call env_check：结构合法、isError=False、含探测文本
        _e = _by_id.get(3, {}).get("result", {})
        t("mcp_env_check_ok",
          _e.get("isError") is False and _e.get("content", [{}])[0].get("type") == "text"
          and "环境探测" in _e.get("content", [{}])[0].get("text", ""))
        # resources/list：手动/reference 可直接喂给客户端当上下文
        _res = {x["uri"] for x in _by_id.get(4, {}).get("result", {}).get("resources", [])}
        t("mcp_resources_present", {"edu://manual", "edu://ref/08"} <= _res)
        # 业务失败不抛协议错：isError=True 且带可读文本（缺文件）
        _r5 = _by_id.get(5, {}).get("result", {})
        t("mcp_iserror_plumbed",
          _r5.get("isError") is True and "未找到" in _r5.get("content", [{}])[0].get("text", ""))
        # 未知方法 → JSON-RPC error -32601，而非静默
        t("mcp_unknown_method_error", _by_id.get(6, {}).get("error", {}).get("code") == -32601)
        # tools/call region_seeds：同步返回，输出内嵌「名单口径边界」与未匹配（军校）
        _t7 = _by_id.get(7, {}).get("result", {})
        _rs_txt = (_t7.get("content") or [{}])[0].get("text", "")
        t("mcp_region_seeds_ok",
          _t7.get("isError") is False and "名单口径" in _rs_txt
          and "命中 2 校" in _rs_txt and "国防科技大学" in _rs_txt)
        # CLI 模式：--print-config 必须落真 stdout（曾因屏蔽把它吃到 stderr，`> f` 得空文件）
        try:
            _cp = _sp.run([sys.executable, os.path.join(HERE, "mcp_server.py"), "--print-config"],
                          capture_output=True, timeout=40)
            _cout = _cp.stdout.decode("utf-8", "replace")
        except Exception:
            _cout = ""
        t("mcp_cli_stdout_config", '"command"' in _cout and "mcp_server.py" in _cout)

    # ---------------- 可移植断言：全库无本机专属/写死日期 ----------------
    FORBID_ALL = ["D:\\Software", "D:/Software", "trae-data", "01_Python", "2026-10-03"]
    # scripts/*.py 里还不许写死校名（示例表在 references/ 里才允许出现）
    FORBID_CODE = FORBID_ALL + ["清华大学", "北京大学", "北京工业大学"]
    scanned = 0
    SKIP_DIRS = ("__pycache__", "discover_out", "_discover_tmp", "新增数据")
    for root, dirs, files in os.walk(SKILL_DIR):
        dirs[:] = [x for x in dirs if x not in SKIP_DIRS]      # 运行产物目录不扫（否则本机跑一次就多几十条断言）
        if any(s in root for s in SKIP_DIRS):
            continue
        for fn in files:
            if not fn.endswith((".py", ".md", ".json", ".txt")):
                continue
            if fn in ("records.json", "jobs.json", "html_links.json",
                      "unverified.json", "discover_report.json"):
                continue                                       # 运行产物，非源文件

            if fn == "selftest.py":      # 本文件带着上面这些反面词字面量，跳过自扫描
                continue
            fp = os.path.join(root, fn)
            try:
                s = open(fp, encoding="utf-8", errors="replace").read()
            except Exception:
                continue
            scanned += 1
            is_own_code = (fn.endswith(".py") and os.path.dirname(fp) == HERE)
            rules = FORBID_CODE if is_own_code else FORBID_ALL
            for bad in rules:
                t("portable_no_%s_in_%s" % (bad.strip(":/\\"), fn),
                  bad not in s)
    t("portable_scanned_some", scanned > 8)

    # ---------------- 结果 ----------------
    print("PASS", len(PASS))
    if SKIP:
        print("SKIP", len(SKIP))
        for s in SKIP:
            print("   -", s)
    print("FAIL", len(FAIL))
    for f in FAIL:
        print("   x", f)
    print("RESULT:", "OK" if not FAIL else "HAS FAILURES")
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(main())

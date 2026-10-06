#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""高校公开资料采集 · 地区名单生成器（地区批量 ① 层）

从内置《教育部全国普通高等学校名单》出发，按 **省 / 层次 / 预设名单(985·211·自定义)** 生成
`region_seeds.json`，直接交给 `discover.py --seeds` 或 MCP `harvest_many` 逐校采集。

设计定位（详见 references/10-地区批量.md）：
  - 本脚本只做**确定性**的事：名单筛选 + 合并用户提供的域名 + 溯源落盘。**不联网、不用测**。
  - **域名解析不在本脚本**：`domain` 为空的行留给上层 Agent 用 WebSearch 逐校补（红线：绝不猜域名）。
  - **零依赖**：只读内置 JSON，纯 stdlib（不引入 xlrd/pandas）。

用法示例：
  python region_seeds.py --province 湖南
  python region_seeds.py --province 湖南 --level 本科
  python region_seeds.py --preset 985 --province 湖北
  python region_seeds.py --preset 211 --province 湖北 --domains my_domains.json --out seeds.json
"""
import os
import re
import sys
import json
import argparse
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402  （复用 load_json/save_json + 控制台 UTF-8）

HERE = os.path.dirname(os.path.abspath(__file__))
REFDIR = os.path.abspath(os.path.join(HERE, "..", "references"))
DEFAULT_DATA = os.path.join(REFDIR, "data", "univ_list_2026-06-17.json")
PRESET_FILES = {
    "985": os.path.join(REFDIR, "data", "985.json"),
    "211": os.path.join(REFDIR, "data", "211.json"),
}

# 省级行政区后缀（用于把「湖南省 / 北京市 / 内蒙古自治区」归一到「湖南 / 北京 / 内蒙古」）
_PROV_SUFFIX = ("维吾尔自治区", "壮族自治区", "回族自治区", "特别行政区", "自治区", "省", "市")
_LEVELS = ("本科", "专科")


def norm_prov(s):
    """把省级名称归一：去掉「省/市/自治区」等后缀，便于「湖南」匹配「湖南省」。"""
    s = (s or "").strip()
    for suf in _PROV_SUFFIX:
        if s.endswith(suf):
            return s[: -len(suf)]
    return s


def norm_domain(d):
    """域名归一：去空白、去协议头、去路径/端口，转小写，去掉开头的 www.。

    只做「形状」归一，不判断真伪——是否为官方 *.edu.cn 由上层核实（红线：绝不猜域名）。
    """
    d = (d or "").strip().strip("/")
    d = re.sub(r"^[a-zA-Z][\w+.-]*://", "", d)  # 去 https:// 之类协议头
    d = d.split("/")[0].split("?")[0].strip()   # 去路径与查询
    d = d.lower()
    if d.startswith("www."):
        d = d[4:]
    return d


def load_data(path):
    doc = C.load_json(path, None)
    if not doc or not isinstance(doc.get("schools"), list):
        sys.stderr.write("名单数据不可用：%s\n" % path)
        sys.exit(2)
    return doc


def load_preset(name, names_file):
    """加载预设/自定义名单，返回 (names列表, 标签)。"""
    if names_file:
        raw = C.load_json(names_file, None)
        if raw is None:  # 允许「每行一个校名」的纯文本
            with open(names_file, encoding="utf-8") as f:
                names = [ln.strip() for ln in f if ln.strip() and not ln.startswith("#")]
        elif isinstance(raw, dict):
            names = raw.get("names", [])
        else:
            names = raw
        return [n for n in names if isinstance(n, str) and n.strip()], os.path.basename(names_file)
    if name in PRESET_FILES:
        doc = C.load_json(PRESET_FILES[name], {})
        return [n for n in doc.get("names", []) if isinstance(n, str)], name
    return None, None


def load_domains(path):
    """加载用户提供的域名映射。支持两种形态：
       {"湖南大学":"hnu.edu.cn"}  或  [{"school":"湖南大学","domain":"hnu.edu.cn","source":"…"}]
    返回 {校名: (domain, source)}，source 默认 "user"。
    """
    if not path:
        return {}
    raw = C.load_json(path, None)
    if raw is None:
        sys.stderr.write("域名文件不可读：%s\n" % path)
        sys.exit(2)
    out = {}
    if isinstance(raw, dict):
        for k, v in raw.items():
            if isinstance(k, str) and isinstance(v, str) and v.strip():
                out[k.strip()] = (norm_domain(v), "user")
    elif isinstance(raw, list):
        for it in raw:
            if isinstance(it, dict) and it.get("school") and it.get("domain"):
                out[str(it["school"]).strip()] = (norm_domain(str(it["domain"])), it.get("source") or "user")
    return out


def build(doc, provinces, levels, preset_names, preset_label, city, domains):
    all_names = {x["n"] for x in doc["schools"]}
    prov_keys = {norm_prov(p) for p in provinces} if provinces else None
    city_keys = {c.strip() for c in city} if city else None
    preset_set = set(preset_names) if preset_names else None

    rows, with_domain = [], 0
    for x in doc["schools"]:
        if prov_keys is not None and norm_prov(x.get("p", "")) not in prov_keys:
            continue
        if levels and x.get("l") not in levels:
            continue
        if city_keys is not None and (x.get("c", "") not in city_keys):
            continue
        if preset_set is not None and x["n"] not in preset_set:
            continue
        dom, src = domains.get(x["n"], (None, None))
        if dom:
            with_domain += 1
        rows.append({
            "school": x["n"], "province": x.get("p", ""), "city": x.get("c", ""),
            "level": x.get("l", ""), "code": x.get("k", ""),
            "domain": dom, "domain_source": src,
        })

    # 预设名单里在本表中找不到的校名（如军校不在教育部名单内）——显式报告，不静默
    unmatched = sorted(n for n in (preset_names or []) if n not in all_names)
    meta = {
        "generated_by": "region_seeds.py",
        "generated_at": date.today().isoformat(),
        "source_list": "%s (%s)" % (os.path.basename(DEFAULT_DATA), doc.get("_meta", {}).get("source", "")),
        "filter": {"province": list(provinces or []), "city": list(city or []),
                   "level": list(levels or []), "preset": preset_label},
        "count": len(rows), "with_domain": with_domain,
        "unmatched_preset_names": unmatched,
        "note": ("domain 为空的行需上层 Agent 用 WebSearch 逐校补官方域名（绝不猜）；"
                 "domain_source 记录来源（user=用户提供 / agent:<证据页URL>=Agent 检索）以便溯源。"),
    }
    return {"_meta": meta, "schools": rows}, unmatched


def write_csv(rows, path):
    import csv
    cols = ["school", "province", "city", "level", "code", "domain", "domain_source"]
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["学校", "省级归属", "所在地", "层次", "学校标识码", "域名", "域名来源"])
        for r in rows:
            w.writerow([r.get(c, "") for c in cols])


def main():
    ap = argparse.ArgumentParser(description="地区名单生成器（地区批量①层，确定性；域名需上层 Agent 补）")
    ap.add_argument("--province", action="append", default=[], help="省级（可重复；简写即可，如 湖南 / 湖北省）")
    ap.add_argument("--city", action="append", default=[], help="所在地城市（可重复，精确匹配，如 长沙市）")
    ap.add_argument("--level", action="append", default=[], choices=_LEVELS, help="办学层次（可重复，默认全部）")
    ap.add_argument("--preset", choices=sorted(PRESET_FILES), help="预设名单：985 / 211")
    ap.add_argument("--names-file", help="自定义名单文件（每行一校名，或 JSON {\"names\":[...]}）")
    ap.add_argument("--domains", help="用户提供的域名映射 JSON（见文档），合并进结果并标 domain_source=user")
    ap.add_argument("--data", default=DEFAULT_DATA, help="覆盖内置名单 JSON 路径")
    ap.add_argument("--out", default="region_seeds.json", help="输出文件名（默认 region_seeds.json）")
    ap.add_argument("--csv", action="store_true", help="同时输出同名 .csv")
    a = ap.parse_args()

    doc = load_data(a.data)
    preset_names, preset_label = load_preset(a.preset, a.names_file)
    if (a.preset or a.names_file) and not preset_names:
        sys.stderr.write("预设/自定义名单为空或不可读。\n")
        sys.exit(2)
    domains = load_domains(a.domains)

    result, unmatched = build(doc, a.province, a.level, preset_names, preset_label, a.city, domains)
    C.save_json(result, a.out)
    if a.csv:
        write_csv(result["schools"], os.path.splitext(a.out)[0] + ".csv")

    m = result["_meta"]
    print("已写出 %s：命中 %d 校（含域名 %d，待 Agent 补 %d）"
          % (a.out, m["count"], m["with_domain"], m["count"] - m["with_domain"]))
    if unmatched:
        print("⚠️ 预设名单有 %d 个校名在整份教育部名单中都未找到（多为军队院校，不受地区筛选影响）：%s"
              % (len(unmatched), "、".join(unmatched)))
    print("→ 下一步：补域名后 python discover.py --seeds %s --auto（或 MCP harvest_many）" % a.out)


if __name__ == "__main__":
    main()

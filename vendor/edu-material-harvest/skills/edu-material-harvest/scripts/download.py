# -*- coding: utf-8 -*-
"""高校公开资料采集 · 下载器（幂等、断点续跑）

用法：
  python download.py jobs.json --dest <新增数据目录> \\
      [--existing 存量sha.json] [--records records.json] \\
      [--tmp <工作目录>/_tmp] [--exclude-school 某校] [--resume]

jobs.json 每项：
  {school, kind, desc, url, page, ext, pack, year}
    school  学校名（落盘子目录）
    kind    材料类型（培养方案 / 专业介绍 / 课程大纲 / 年度报告…）
    desc    专业/说明（成文件名主体）
    url     下载直链
    page    承载页 URL
    ext     扩展名（pdf/rar/zip/docx…），默认按 url 推断
    pack    true 表示 url 是 RAR/ZIP 打包件，需解压后逐份登记
    year    年份（可选，作文件名前缀）

行为：
  下载 → 魔数校验 → sha1 与【存量 + 本批】去重（重复者回收）→
  RAR/ZIP 解压 → 按 <dest>/<school>/<kind>/ 落盘 → 追加 records.json

幂等：目标已存在且魔数正确则跳过下载（断点续跑）。
"""
import os
import re
import sys
import json
import shutil
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402

KIND_DIR = {
    "培养方案": "培养方案",
    "专业介绍": "专业介绍",
    "课程大纲": "课程大纲",
    "年度报告": "年度报告",
}


def ext_of(url, given=None):
    if given:
        return given.lower().lstrip(".")
    p = url.lower().split("?")[0]
    for e in ("pdf", "docx", "doc", "xlsx", "xls", "rar", "zip"):
        if p.endswith("." + e):
            return e
    return "pdf"


def target_fname(desc, year, ext):
    """落盘文件名：<年>_<说明>；说明本身已带同后缀时不再重复追加（避免 a.doc → a.doc.doc）。"""
    ext = (ext or "").lower().lstrip(".")
    base = C.safe_name(desc)
    fn = "%s_%s" % (year, base) if year else base
    if ext and not fn.lower().endswith("." + ext):
        fn += "." + ext
    return fn


def college_of(desc):
    """从 RAR 描述里剥出学院/包名（去 PDF、尾部括号）。"""
    s = re.sub(r"\.rar$|\.zip$", "", desc, flags=re.I)
    s = re.sub(r"[（(].*?[)）]", "", s).replace("PDF", "").replace("pdf", "").strip()
    return C.safe_name(s, 60) or "包"


def load_existing_sha(path):
    """读存量 sha1 集合。支持两种格式：list[{sha1}] 或 {sha1:..}。"""
    if not path or not os.path.exists(path):
        return set()
    data = C.load_json(path, [])
    out = set()
    if isinstance(data, list):
        for r in data:
            if isinstance(r, dict) and r.get("sha1"):
                out.add(r["sha1"])
    elif isinstance(data, dict):
        out.update(data.keys())
    return out


def run(jobs, dest, existing_sha=None, records_path=None, tmp=None,
        exclude_school=None, resume=True, log=print):
    """执行下载。返回 records 列表（本批全部条目，含失败/重复）。"""
    existing_sha = existing_sha or set()
    tmp = tmp or os.path.join(os.path.dirname(os.path.abspath(records_path or "records.json")), "_tmp")
    os.makedirs(tmp, exist_ok=True)

    # 断点续跑：载入已有 records 作为已落盘集合
    records = C.load_json(records_path, []) if (records_path and resume) else []
    # ⚠️ 防"自比"：补漏时把本校上轮记录先剔除，再据其余记录建去重集
    if exclude_school:
        records = [r for r in records if r.get("school") != exclude_school]
    got_sha = {}
    for r in records:
        if r.get("sha1"):
            got_sha[r["sha1"]] = os.path.join(dest, r.get("file", ""))

    to_recycle = []
    added = 0

    def place(school, kind, desc, srcpath, page, url, year="", inner=""):
        nonlocal added
        d = os.path.join(dest, C.safe_name(school), KIND_DIR.get(kind, kind))
        os.makedirs(d, exist_ok=True)
        fn = target_fname(desc, year, os.path.splitext(srcpath)[1])
        dst = os.path.join(d, fn)
        k = 1
        while os.path.exists(dst):
            k += 1
            stem, ext = os.path.splitext(fn)
            dst = os.path.join(d, "%s_%d%s" % (stem, k, ext))
        shutil.copyfile(srcpath, dst)
        s = C.sha1(dst)
        records.append(dict(
            school=school, kind=kind, desc=desc, year=year,
            file=os.path.relpath(dst, dest).replace("\\", "/"),
            size_mb=round(os.path.getsize(dst) / 1048576, 3),
            sha1=s, status="新增", url=url, page=page, inner=inner))
        got_sha[s] = dst
        added += 1

    for i, j in enumerate(jobs, 1):
        school = j["school"]
        kind = j.get("kind", "")
        desc = j.get("desc", "")
        url = j["url"]
        page = j.get("page", "")
        year = j.get("year", "")
        ext = ext_of(url, j.get("ext"))
        log("[%d/%d] %s | %s | %s" % (i, len(jobs), school, desc[:34], ext))

        if j.get("pack") or ext in ("rar", "zip"):
            arc = os.path.join(tmp, "p_%d.%s" % (i, ext))
            if not C.curl(url, out=arc, ref=page):
                log("   下载失败"); records.append(_fail(school, kind, desc, year, url, page, "下载失败")); continue
            if not C.magic_ok(arc, ext):
                log("   非 %s（可能 HTML）" % ext); C.recycle(arc)
                records.append(_fail(school, kind, desc, year, url, page, "非目标格式")); continue
            outdir = os.path.join(tmp, "x_%d" % i)
            if os.path.exists(outdir):
                C.recycle(outdir)          # 走回收站，不永久删除
            try:
                C.extract_rar(arc, outdir)
            except C.DepError as e:
                log("   缺解压器，跳过本项：%s" % e.tool)
                C.recycle(arc)
                records.append(_fail(school, kind, desc, year, url, page, "缺解压器"))
                continue
            folder = college_of(desc)
            cnt = 0
            for root, _dirs, files in os.walk(outdir):
                for fn in files:
                    if not fn.lower().endswith(".pdf"):
                        continue
                    place(school, kind, os.path.splitext(fn)[0], os.path.join(root, fn),
                          page, url, year, inner=folder)
                    cnt += 1
            log("   解压落盘 %d 份" % cnt)
            C.recycle(arc)
        else:
            outp = os.path.join(tmp, "d_%d.%s" % (i, ext))
            # 断点续跑：目标已存在且有效则跳过
            d0 = os.path.join(dest, C.safe_name(school), KIND_DIR.get(kind, kind))
            guess = os.path.join(d0, target_fname(desc, year, ext))
            if resume and C.valid(guess, ext):
                log("   已存在，跳过")
                continue
            if not C.curl(url, out=outp, ref=page):
                log("   下载失败"); records.append(_fail(school, kind, desc, year, url, page, "下载失败")); continue
            if not C.magic_ok(outp, ext):
                log("   非 %s（可能 HTML 挑战）" % ext); C.recycle(outp)
                records.append(_fail(school, kind, desc, year, url, page, "非目标格式")); continue
            s = C.sha1(outp)
            if s in existing_sha:
                log("   重复→已有存量"); C.recycle(outp)
                records.append(_fail(school, kind, desc, year, url, page, "重复→已有存量", sha=s)); continue
            if s in got_sha:
                kept = got_sha[s]
                log("   重复→本批已下")
                C.recycle(outp)
                records.append(_fail(school, kind, desc, year, url, page, "重复→本批已下", sha=s)); continue
            place(school, kind, desc, outp, page, url, year)
            C.recycle(outp)

    records_path and C.save_json(records, records_path)
    log("\n完成：新增 %d 份，records 共 %d 条" % (added, len(records)))
    return records


def _fail(school, kind, desc, year, url, page, note, sha=""):
    return dict(school=school, kind=kind, desc=desc, year=year, file="", size_mb=0,
                sha1=sha, status=note, url=url, page=page)


def main():
    ap = argparse.ArgumentParser(description="高校公开资料采集·下载器")
    ap.add_argument("jobs", help="jobs.json")
    ap.add_argument("--dest", required=True, help="新增数据根目录")
    ap.add_argument("--existing", help="存量 sha1 的 json（如 03_content_probe.json）")
    ap.add_argument("--records", default="records.json", help="记录输出（幂等续跑用）")
    ap.add_argument("--tmp", help="下载暂存目录")
    ap.add_argument("--exclude-school", help="补漏：剔除该校已有记录防自比")
    ap.add_argument("--no-resume", action="store_true", help="不从 records 续跑（全新）")
    a = ap.parse_args()

    jobs = C.load_json(a.jobs, [])
    existing = load_existing_sha(a.existing)
    print("待下载 %d 项；存量去重集 %d 条" % (len(jobs), len(existing)))
    run(jobs, a.dest, existing_sha=existing, records_path=a.records,
        tmp=a.tmp, exclude_school=a.exclude_school, resume=not a.no_resume)


if __name__ == "__main__":
    main()

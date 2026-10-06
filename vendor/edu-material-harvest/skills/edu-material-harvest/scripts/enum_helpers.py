# -*- coding: utf-8 -*-
"""高校公开资料采集 · 枚举助手

三种常见枚举形态：
  1) 整页直链      —— links_from_html()：从栏目页/文章页抽附件直链
  2) 链式爬取      —— chain_crawl()：“上一篇/下一篇”翻页，BFS 收集文章页
  3) 二级解析      —— resolve_attachments()：详情页里再抽附件（列表页 → 详情页 → 文件）

所有函数只读、不下载文件本体（下载交给 download.py）。
"""
import re
import os
import sys
import html as _html
import urllib.parse
from urllib.parse import urljoin

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402

DOC_EXT = (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".rar", ".zip", ".7z")


def links_from_html(text, base, exts=DOC_EXT):
    """从 HTML 抽附件链接。返回 [(绝对URL, 锚文本)]，已剥标签。

    扩展名匹配用**去 fragment 后的完整 URL**——很多站点把文件名放查询串
    （如 downfile.jsp?classid=0&filename=xxx.rar），只查路径会漏。
    """
    out = []
    for m in re.finditer(r'<a[^>]+href\s*=\s*["\']([^"\']+)["\'][^>]*>(.*?)</a>',
                         text, re.I | re.S):
        href, anchor = m.group(1).strip(), m.group(2)
        full = urljoin(base, href)
        u = full.split("#")[0].lower()
        if exts and not u.endswith(tuple(exts)):
            continue
        txt = re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", "", anchor))).strip()
        out.append((full, txt))
    return out


def all_links(text, base):
    """抽页面所有 <a>（不过滤扩展名）。返回 [(绝对URL, 锚文本)]。"""
    return links_from_html(text, base, exts=None)


def fetch_links(url, exts=DOC_EXT, ref=None):
    """取页面并抽附件链接。"""
    text = C.decode(C.curl(url, ref=ref))
    return links_from_html(text, url, exts)


def resolve_attachments(detail_url, ref=None, exts=DOC_EXT):
    """二级解析：详情页里抽附件直链（如某校 /info/NNNN.htm 式）。

    先按 <a href> 抽；抽不到再抓 __local / /docs/ / upload 资源路径。
    """
    text = C.decode(C.curl(detail_url, ref=ref))
    got = links_from_html(text, detail_url, exts)
    if got:
        return got
    out = []
    for m in re.finditer(r'(?:href|src)\s*=\s*["\']([^"\']*(?:__local|/docs/|/upload|/resources/)[^"\']+)["\']',
                         text, re.I):
        full = urljoin(detail_url, m.group(1))
        if re.search(r"\.(pdf|docx?|xlsx?|rar|zip|7z)(\?|$)", full.split("#")[0], re.I):
            out.append((full, ""))
    return out


def chain_crawl(start_url, article_match, next_texts=("上一篇", "下一篇"),
                max_pages=200, collect=None, ref=None):
    """链式爬取：从 start_url 顺“上一篇/下一篇”BFS，收集所有文章页 URL。

    article_match: 正则或 callable，命中即视为文章页（收集）。
    collect: callable(url, text)->None，可顺手解析每页（如抽附件）。
    返回 (visited_urls, collected_article_urls)。
    """
    if not callable(article_match):
        pat = re.compile(article_match)

        def article_match(u):
            return bool(pat.search(u))

    queue = [urljoin(start_url, start_url)]
    visited, articles = set(), []
    while queue and len(visited) < max_pages:
        u = queue.pop(0)
        u = u.split("#")[0]
        if u in visited:
            continue
        visited.add(u)
        text = C.decode(C.curl(u, ref=ref))
        if not text:
            continue
        if article_match(u):
            articles.append(u)
            if collect:
                collect(u, text)
        for href, anchor in all_links(text, u):
            a = anchor.strip()
            if any(t in a for t in next_texts) or any(t in href for t in next_texts):
                n = urljoin(u, href).split("#")[0]
                if n not in visited:
                    queue.append(n)
    return visited, articles


def probe_numbered(base_tpl, n_from=1, n_to=90, exts=(".pdf",)):
    """编号直链探测：base_tpl 含 {n}，逐个探测可达性。返回 [(url, True/False)]。

    用于无索引页的目录（如某校 zxzy/{N}.pdf）。
    """
    out = []
    for n in range(n_from, n_to + 1):
        url = base_tpl.format(n=n)
        body = C.curl(url, maxt=20)
        ok = bool(body) and body[:4] == b"%PDF"
        if ok:
            out.append((url, True))
    return out


if __name__ == "__main__":
    # 演示：对一个栏目页抽附件链接
    target = sys.argv[1] if len(sys.argv) > 1 else ""
    if not target:
        print("用法：python enum_helpers.py <栏目页URL>")
        sys.exit(0)
    for u, t in fetch_links(target):
        print(t[:40] or "(无锚文本)", "->", u)

"""按需 PDF 正文抽取 + 缓存（用于只有 PDF、没有 txt 的报告类材料）。

就业质量报告、教学质量报告在很多院校只以 PDF 存在；把正文抽出来并缓存到
``data/processed/pdf_text_cache/``，后续分析直接复用，避免每次运行重复解析。

约束：

* 只读原件，不修改 ``data/source``；
* 缓存键 = 文件相对路径 + mtime + size，原件更新会自动失效；
* 页数与字符数可设上限，避免大报告拖慢一次分析。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

DEFAULT_MAX_PAGES = 80
DEFAULT_MAX_CHARS = 400_000


def cache_key(path: Path, project_root: Path) -> str:
    stat = path.stat()
    rel = str(path.resolve().relative_to(Path(project_root).resolve())).replace("\\", "/")
    return hashlib.sha1(f"{rel}|{stat.st_mtime_ns}|{stat.st_size}".encode("utf-8")).hexdigest()[:16]


def cached_pdf_text(
    path: Path,
    *,
    project_root: Path,
    cache_dir: Path | None = None,
    max_pages: int = DEFAULT_MAX_PAGES,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> str:
    """Return the PDF text, reading the cache first; extract and cache on miss."""
    path = Path(path)
    if path.suffix.lower() != ".pdf":
        return path.read_text(encoding="utf-8", errors="ignore")[:max_chars]
    root = Path(project_root).resolve()
    cache_dir = Path(cache_dir) if cache_dir else root / "data" / "processed" / "pdf_text_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    try:
        key = cache_key(path, root)
    except (OSError, ValueError):
        key = hashlib.sha1(str(path).encode("utf-8")).hexdigest()[:16]
    cache_file = cache_dir / f"{key}.txt"
    if cache_file.exists():
        return cache_file.read_text(encoding="utf-8", errors="ignore")[:max_chars]
    text = ""
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        chunks: list[str] = []
        for page in list(reader.pages)[:max_pages]:
            chunks.append(page.extract_text() or "")
            if sum(len(c) for c in chunks) >= max_chars:
                break
        text = "\n".join(chunks)
    except Exception as exc:  # noqa: BLE001 - 抽取失败要如实体现为空，不猜测内容
        text = ""
        (cache_dir / f"{key}.error.json").write_text(
            json.dumps({"path": str(path), "error": f"{type(exc).__name__}: {exc}"},
                       ensure_ascii=False, indent=2),
            encoding="utf-8")
    if text:
        cache_file.write_text(text[:max_chars], encoding="utf-8")
    return text[:max_chars]

"""PDF text extraction (pypdf), page-aware and cached.

Chinese reports published by universities extract well with pypdf; scanned
image-only pages yield empty text and are reported as
``text_status='pdf_no_text_layer'`` instead of being silently dropped.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

try:  # optional dependency: the rest of the system works without it
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError
except Exception:  # noqa: BLE001
    PdfReader = None  # type: ignore[assignment]

    class PdfReadError(Exception):  # type: ignore[no-redef]
        ...


@dataclass
class PdfText:
    path: str
    n_pages: int = 0
    pages_with_text: int = 0
    char_count: int = 0
    sha1: str = ""
    text_status: str = "ok"  # ok | pdf_no_text_layer | extractor_unavailable | error
    error: str = ""
    text: str = ""
    page_offsets: list[int] = field(default_factory=list)
    extracted_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def page_of(self, char_index: int) -> int | None:
        """Map a character offset in ``text`` back to a 1-based page number."""
        for page_no in range(len(self.page_offsets) - 1, -1, -1):
            if char_index >= self.page_offsets[page_no]:
                return page_no + 1
        return 1 if self.page_offsets else None

    def to_dict(self, *, include_text: bool = True) -> dict[str, Any]:
        data = {
            "path": self.path,
            "n_pages": self.n_pages,
            "pages_with_text": self.pages_with_text,
            "char_count": self.char_count,
            "sha1": self.sha1,
            "text_status": self.text_status,
            "error": self.error,
            "extracted_at": self.extracted_at,
            # 页码偏移必须随缓存保存，否则复用缓存时无法定位到页
            "page_offsets": self.page_offsets,
        }
        if include_text:
            data["text"] = self.text
        return data


#: 页分隔符：写盘时保留页码信息，便于"只重跑事实、不重解析 PDF"。
PAGE_SEP = "\f"


def pages_to_text(pages: list[str]) -> str:
    return PAGE_SEP.join(pages)


def text_to_page_offsets(text: str) -> list[int]:
    offsets = [0]
    for index, char in enumerate(text):
        if char == PAGE_SEP:
            offsets.append(index + 1)
    return offsets


def pdftext_from_file(path: Path, *, school: str = "", year: int | None = None) -> PdfText:
    """Rebuild a :class:`PdfText` from a saved text file (with page separators)."""
    text = path.read_text(encoding="utf-8", errors="replace")
    offsets = text_to_page_offsets(text)
    return PdfText(
        path=str(path), n_pages=len(offsets), pages_with_text=len(offsets),
        char_count=len(text.replace(PAGE_SEP, "")), text_status="ok" if text.strip() else "pdf_no_text_layer",
        text=text.replace(PAGE_SEP, "\n"), page_offsets=[0] * 0 or _offsets_without_sep(offsets, text),
        sha1=hashlib.sha1(text.encode("utf-8")).hexdigest()[:16],
    )


def _offsets_without_sep(offsets: list[int], text: str) -> list[int]:
    """Offsets in the separator-free text (page i starts at offsets[i] - i)."""
    return [max(0, off - i) for i, off in enumerate(offsets)]


def source_pdf_for_text(text_path: Path, *, text_root: Path, archive_root: Path,
                        source_root: Path | None = None) -> Path:
    """Map a cached text file back to the PDF it came from (for provenance).

    Facts must all point at the same origin (the PDF), otherwise a re-extraction
    from the text cache would be treated as a different source and duplicate the
    dataset.

    包内规范结构是 ``data/source/<类型>/<院校>/<文件>.pdf``，而正文缓存是
    ``data/raw/pdf_text/<院校>/<类型>/<文件>.txt``——**目录顺序相反**，
    所以要显式换位映射；映射不到再退回旧的归档布局。
    """
    try:
        rel = text_path.relative_to(text_root).with_suffix(".pdf")
    except ValueError:
        return text_path
    candidates: list[Path] = []
    if source_root is not None:
        parts = rel.parts
        if len(parts) >= 3:                      # <院校>/<类型>/<文件>.pdf → <类型>/<院校>/…
            candidates.append(Path(source_root).joinpath(parts[1], parts[0], *parts[2:]))
        candidates.append(Path(source_root) / rel)
    candidates.append(Path(archive_root) / rel)
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return text_path


def _sha1_of(path: Path, chunk: int = 1 << 20) -> str:
    digest = hashlib.sha1()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            digest.update(block)
    return digest.hexdigest()


def extract_pdf(path: Path, *, max_pages: int | None = None) -> PdfText:
    result = PdfText(path=str(path), sha1=_sha1_of(path))
    if PdfReader is None:
        result.text_status = "extractor_unavailable"
        result.error = "pypdf 未安装：pip install pypdf"
        return result
    try:
        reader = PdfReader(str(path))
        result.n_pages = len(reader.pages)
        limit = min(result.n_pages, max_pages) if max_pages else result.n_pages
        parts: list[str] = []
        offsets: list[int] = []
        cursor = 0
        for index in range(limit):
            try:
                page_text = reader.pages[index].extract_text() or ""
            except Exception:  # noqa: BLE001 - a single bad page must not kill the doc
                page_text = ""
            page_text = page_text.strip()
            if page_text:
                result.pages_with_text += 1
            offsets.append(cursor)
            parts.append(page_text)
            cursor += len(page_text) + 1
        result.text = "\n".join(parts)
        result.page_offsets = offsets
        result.char_count = len(result.text)
        result.text_status = "ok" if result.char_count > 0 else "pdf_no_text_layer"
    except PdfReadError as exc:
        result.text_status = "error"
        result.error = f"PdfReadError: {exc}"
    except Exception as exc:  # noqa: BLE001
        result.text_status = "error"
        result.error = f"{type(exc).__name__}: {exc}"
    return result


def extract_many(paths: Iterable[Path], *, cache_dir: Path | None = None,
                 max_pages: int | None = None) -> list[PdfText]:
    """Extract a batch, caching each result as JSON keyed by file sha1."""
    out: list[PdfText] = []
    for path in paths:
        digest = _sha1_of(path)
        cache_file = None
        if cache_dir:
            cache_dir.mkdir(parents=True, exist_ok=True)
            cache_file = cache_dir / f"{digest}.json"
            if cache_file.exists():
                try:
                    payload = json.loads(cache_file.read_text(encoding="utf-8"))
                    cached = PdfText(**{k: v for k, v in payload.items()
                                        if k in PdfText.__dataclass_fields__})
                    out.append(cached)
                    continue
                except Exception:  # noqa: BLE001
                    pass
        result = extract_pdf(path, max_pages=max_pages)
        out.append(result)
        if cache_file:
            cache_file.write_text(json.dumps(result.to_dict(include_text=True), ensure_ascii=False),
                                  encoding="utf-8")
    return out


CACHE_SCHEMA = "pdftext-cache/1"


def cache_path_for(digest: str, cache_dir: Path) -> Path:
    return cache_dir / f"{digest}.json"


def load_cached(path: Path, cache_dir: Path, *, verify_sha1: bool = True) -> PdfText | None:
    """Return a cached :class:`PdfText` (including text) if it matches the file.

    Reuse contract: the cache stores the **full text with page separators**, so a
    later run - or another project - can rebuild every fact without parsing the
    PDF again. ``verify_sha1`` re-hashes the PDF to detect changed files.
    """
    digest = _sha1_of(path)
    cache_file = cache_path_for(digest, cache_dir)
    if not cache_file.exists():
        return None
    try:
        payload = json.loads(cache_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if payload.get("schema") != CACHE_SCHEMA:
        return None
    fields = {k: v for k, v in payload.items() if k in PdfText.__dataclass_fields__}
    cached = PdfText(**fields)
    if verify_sha1 and cached.sha1 != digest:
        return None
    return cached


def save_cache(pdf: PdfText, path: Path, cache_dir: Path) -> Path:
    """Persist the full extracted text (page-separated) keyed by file sha1."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    payload = pdf.to_dict(include_text=True)
    payload["schema"] = CACHE_SCHEMA
    payload["source_file"] = str(path)
    payload["page_separator"] = "\\f"
    cache_file = cache_path_for(pdf.sha1, cache_dir)
    cache_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return cache_file

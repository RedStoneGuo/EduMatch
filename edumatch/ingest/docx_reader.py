"""Stdlib-only .docx / .xlsx text readers (shared by ingestion and scripts)."""

from __future__ import annotations

import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def read_docx_text(path: Path) -> str:
    with zipfile.ZipFile(path) as zf:
        if "word/document.xml" not in zf.namelist():
            raise ValueError(f"not a docx: {path}")
        root = ET.fromstring(zf.read("word/document.xml"))
    lines: list[str] = []
    for para in root.iter(f"{W_NS}p"):
        text = "".join((node.text or "") for node in para.iter(f"{W_NS}t")).strip()
        if text:
            lines.append(text)
    return "\n".join(lines)


def read_xlsx_text(path: Path, max_rows: int = 500) -> str:
    with zipfile.ZipFile(path) as zf:
        shared: list[str] = []
        if "xl/sharedStrings.xml" in zf.namelist():
            root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
            for si in root:
                shared.append("".join(t.text or "" for t in si.iter() if t.tag.endswith("}t")))
        lines: list[str] = []
        for sheet in sorted(n for n in zf.namelist() if re.match(r"xl/worksheets/sheet\d+\.xml$", n)):
            root = ET.fromstring(zf.read(sheet))
            for i, row in enumerate(root.iter()):
                if i > max_rows:
                    break
                if not row.tag.endswith("}row"):
                    continue
                cells: list[str] = []
                for cell in row:
                    value = ""
                    for child in cell:
                        if child.tag.endswith("}v"):
                            value = child.text or ""
                    if cell.get("t") == "s" and value.isdigit():
                        value = shared[int(value)]
                    cells.append(value)
                if any(cells):
                    lines.append("\t".join(cells))
        return "\n".join(lines)


def read_any_text(path: Path) -> str:
    ext = path.suffix.lower()
    if ext == ".docx":
        return read_docx_text(path)
    if ext == ".xlsx":
        return read_xlsx_text(path)
    if ext in {".txt", ".md", ".json"}:
        return path.read_text(encoding="utf-8", errors="replace")
    raise ValueError(f"unsupported extension: {ext}")

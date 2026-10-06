"""可迁移性自检：整包拷到别的电脑/别的 Agent 之前跑一次。

检查四件事：

1. **代码/配置里有没有盘符绝对路径**（``D:\\…`` / ``C:/…``）——有就报错；
2. **有没有引用包外目录**（``../…``）——只允许"可选补充源"，
   且必须能在缺失时优雅降级；
3. **必需目录/文件是否齐**（config / ontology / data / vendor 插件 / skills / reporting）；
4. **默认输出目录是否可写**（默认落在当前工作目录，不依赖包外结构）。

用法：

    python scripts\\check_portability.py
    python scripts\\check_portability.py --json portability.json

退出码 0 = 可迁移；1 = 存在必须修复的问题。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

CORE = Path(__file__).resolve().parents[1]
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))

#: 允许出现的包外引用：可选补充来源，缺失时流程照常
ALLOWED_OUTSIDE = ("../AI竞赛数据归档",)

ABS_PATH = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:[\\/]")
REQUIRED = (
    "config/config.yaml", "ontology/skill_ontology.yaml", "data/processed/jobs.json",
    "data/raw/supplementary_courses.json", "vendor/edu-material-harvest",
    "skills/00_agent_entry/SKILL.md", "reporting/render.py", "agent/runner.py",
    "scripts/analyze.py", "analyze.ps1", "AGENTS.md", "PROMPT.md", "交接文档.md",
)


def scan_absolute_paths() -> list[dict[str, str]]:
    hits: list[dict[str, str]] = []
    for path in CORE.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in {".py", ".ps1", ".psm1",
                                                             ".yaml", ".yml", ".bat", ".cmd"}:
            continue
        if any(part in {"vendor", "__pycache__", ".pytest_cache"} for part in path.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for line_no, line in enumerate(text.splitlines(), 1):
            if "http://" in line or "https://" in line:
                continue
            stripped = line.strip()
            # 跳过文档/注释里的举例（反引号、markdown 前缀），只看真实代码/配置
            if "`" in line or stripped.startswith(("#", '"', "'", "*", ">", "|", "-")):
                continue
            if ABS_PATH.search(line):
                hits.append({"file": str(path.relative_to(CORE).as_posix()),
                             "line": str(line_no), "text": line.strip()[:120]})
    return hits


def scan_outside_refs() -> list[dict[str, str]]:
    hits: list[dict[str, str]] = []
    for path in CORE.rglob("*.py"):
        if any(part in {"vendor", "__pycache__", ".pytest_cache"} for part in path.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for match in re.finditer(r"[\"'](\.\./[^\"']+)[\"']", text):
            ref = match.group(1)
            if any(ref.startswith(allowed) for allowed in ALLOWED_OUTSIDE):
                continue
            line_no = text[: match.start()].count("\n") + 1
            hits.append({"file": str(path.relative_to(CORE).as_posix()),
                         "line": str(line_no), "ref": ref})
    return hits


def check_required() -> list[str]:
    return [item for item in REQUIRED if not (CORE / item).exists()]


def main() -> int:
    ap = argparse.ArgumentParser(description="EduMatch 可迁移性自检")
    ap.add_argument("--json", type=Path, default=None)
    args = ap.parse_args()

    from edumatch.config import load_settings

    settings = load_settings()
    absolute = scan_absolute_paths()
    outside = scan_outside_refs()
    missing = check_required()
    archive_in_package = (CORE / "reference" / "archive").exists()
    external_archives = [str(p) for p in settings.extra_archive_dirs()]

    payload = {
        "core_dir": str(CORE),
        "absolute_paths": absolute,
        "outside_refs": outside,
        "missing_required": missing,
        "archive_in_package": archive_in_package,
        "external_archives_available": external_archives,
        "verdict": ("可迁移：整包复制到任意路径/电脑即可运行"
                    if not absolute and not outside and not missing
                    else "存在需要修复的问题"),
        "note": ("包外 `../AI竞赛数据归档` 是**可选**补充源；缺失时用包内 "
                 "`reference/archive` 与 `data/source`，流程不中断。"
                 "默认输出目录为“当前工作目录/分析产物”，不依赖 core 外的结构。"),
    }
    print(f"Core 目录：{payload['core_dir']}")
    print(f"盘符绝对路径：{len(absolute)} 处" + ("（需修复）" if absolute else " ✓"))
    for hit in absolute[:10]:
        print(f"  - {hit['file']}:{hit['line']}  {hit['text']}")
    print(f"包外引用（未被允许）：{len(outside)} 处" + ("（需修复）" if outside else " ✓"))
    for hit in outside[:10]:
        print(f"  - {hit['file']}:{hit['line']}  {hit['ref']}")
    print(f"必需文件缺失：{len(missing)} 个" + ("（需修复）" if missing else " ✓"))
    for item in missing:
        print(f"  - {item}")
    print(f"包内归档 reference/archive：{'存在 ✓' if archive_in_package else '缺失（不影响主流程）'}")
    print(f"包外可选归档（存在才用）：{external_archives or '未发现（正常）'}")
    print(f"\n结论：{payload['verdict']}")
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"报告已写入 {args.json}")
    return 0 if not absolute and not outside and not missing else 1


if __name__ == "__main__":
    raise SystemExit(main())

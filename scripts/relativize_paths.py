"""把数据文件中的绝对路径改写成可迁移的相对路径。

    python scripts/relativize_paths.py            # 就地改写本目录 data/ 下的 JSON
    python scripts/relativize_paths.py --check    # 只报告，不改写

背景：事实库/课程库里保存的 `source_document` 曾经是 `D:\\...\\AI竞赛数据归档\\...`
这类绝对路径，换一台电脑就全部失效。本脚本按下述规则改写（幂等，可重复运行）：

1. 位于本核心目录内的文件 → 相对本目录，例如 `data/raw/pdf_text/...`；
2. 位于 `reference/archive` 内的归档文件 → `reference/archive/...`（本地可直接解析）；
3. 已随包迁移到 `data/source/` 的原始材料 → 在 `data/source`（「数据类型 → 院校」）
   里按文件名唯一定位，写成 `data/source/...`（包内可直接解析）；
4. 其它工作区文件（未随核心包复制）→ `../<原目录>/...`，
   明确表示"外部引用"，不会伪装成本地文件；
5. URL（`https://`、`doi:` 等）与已相对路径不动。
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parent
ABS = re.compile(r"^(?P<drive>[A-Za-z]):[\\/](?P<rest>.*)$")
URL_LIKE = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*://")


_SOURCE_INDEX: dict[str, list[str]] | None = None


def _source_lookup(name: str) -> str | None:
    """按文件名在 ``data/source`` 里唯一定位（规范结构可能已重排目录）。"""
    global _SOURCE_INDEX
    if _SOURCE_INDEX is None:
        index: dict[str, list[str]] = {}
        base = ROOT / "data" / "source"
        if base.exists():
            for path in base.rglob("*"):
                if path.is_file():
                    index.setdefault(path.name, []).append(path.relative_to(ROOT).as_posix())
        _SOURCE_INDEX = index
    hits = _SOURCE_INDEX.get(name) or []
    return hits[0] if len(hits) == 1 else None


def _rewrite(value: str) -> str | None:
    if not value or URL_LIKE.match(value):
        return None
    match = ABS.match(value)
    if match:
        path = Path(f"{match.group('drive')}:/{match.group('rest')}")
    elif value.startswith(".."):        # 旧一轮已相对化过的外部引用：再尝试收敛到包内
        path = (ROOT / value).resolve()
    else:
        return None
    try:
        rel_to_root = path.relative_to(ROOT)
        return rel_to_root.as_posix()
    except ValueError:
        pass
    try:
        rel_to_ws = path.relative_to(WORKSPACE)
    except ValueError:
        return None
    parts = rel_to_ws.parts
    # 包内的原始材料：在规范结构 data/source 里按文件名唯一定位
    hit = _source_lookup(path.name)
    if hit:
        return hit
    if parts and parts[0] == "AI竞赛数据归档":
        # 归档中随核心包复制的部分用本地引用；其余保留为外部引用
        local = ROOT / "reference" / "archive" / Path(*parts[1:])
        if local.exists():
            return local.relative_to(ROOT).as_posix()
        return (Path("..") / rel_to_ws).as_posix()
    return (Path("..") / rel_to_ws).as_posix()


def _walk(node, counter: list[int]):
    if isinstance(node, dict):
        return {k: _walk(v, counter) for k, v in node.items()}
    if isinstance(node, list):
        return [_walk(v, counter) for v in node]
    if isinstance(node, str):
        new = _rewrite(node)
        if new is not None and new != node:
            counter[0] += 1
            return new
        return node
    return node


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="相对化数据文件中的绝对路径")
    ap.add_argument("--check", action="store_true", help="只报告，不写回")
    ap.add_argument("--include", default="data", help="扫描的目录（默认 data）")
    args = ap.parse_args(argv)

    total = 0
    for path in sorted((ROOT / args.include).rglob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        counter = [0]
        updated = _walk(payload, counter)
        if not counter[0]:
            continue
        total += counter[0]
        if not args.check:
            path.write_text(json.dumps(updated, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"{'[dry]' if args.check else '[fix]'} {path.relative_to(ROOT)}: {counter[0]} 处")
    print(f"{'待改写' if args.check else '已改写'} {total} 处绝对路径")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Central configuration loading (single source of truth)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = PROJECT_ROOT.parent
DEFAULT_CONFIG = PROJECT_ROOT / "config" / "config.yaml"


@dataclass
class Settings:
    """Resolved runtime settings. All paths are absolute."""

    raw: dict[str, Any]
    project_root: Path = PROJECT_ROOT
    workspace_root: Path = WORKSPACE_ROOT
    db_path: Path = field(default_factory=lambda: PROJECT_ROOT / "data" / "db" / "edumatch.sqlite")
    ontology_path: Path = field(default_factory=lambda: PROJECT_ROOT / "ontology" / "skill_ontology.yaml")
    processed_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "data" / "processed")
    reports_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "evaluation" / "reports")

    def section(self, name: str) -> dict[str, Any]:
        return dict(self.raw.get(name) or {})

    def resolve(self, value: str | os.PathLike[str]) -> Path:
        p = Path(value)
        return p if p.is_absolute() else (PROJECT_ROOT / p).resolve()

    @property
    def archive_dir(self) -> Path:
        # 默认指向**包内**最小归档，保证整包拷走也能跑；包外老归档只作可选补充。
        return self.resolve(self.raw.get("paths", {}).get("archive", "reference/archive"))

    def extra_archive_dirs(self) -> list[Path]:
        """可选的外部归档目录（存在才返回；不存在不影响任何流程）。

        默认会看一眼包外的 ``../AI竞赛数据归档``——它只是**补充来源**，
        缺了就走包内 ``reference/archive`` 与 ``data/source``。
        """
        raw = self.raw.get("paths", {}) or {}
        candidates = raw.get("archive_external") or ["../AI竞赛数据归档"]
        if isinstance(candidates, str):
            candidates = [candidates]
        out: list[Path] = []
        for item in candidates:
            path = self.resolve(item)
            if path.exists() and path not in out:
                out.append(path)
        return out


@lru_cache(maxsize=4)
def load_settings(config_path: str | None = None) -> Settings:
    path = Path(config_path) if config_path else DEFAULT_CONFIG
    with path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    paths = raw.get("paths", {})
    settings = Settings(raw=raw)
    settings.db_path = settings.resolve(paths.get("database", "data/db/edumatch.sqlite"))
    settings.ontology_path = settings.resolve(paths.get("ontology", "ontology/skill_ontology.yaml"))
    settings.processed_dir = settings.resolve(paths.get("processed", "data/processed"))
    settings.reports_dir = settings.resolve(paths.get("reports", "evaluation/reports"))
    return settings

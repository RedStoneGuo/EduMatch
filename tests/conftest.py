from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from edumatch.dataset import Dataset  # noqa: E402
from edumatch.engine import ResearchEngine  # noqa: E402


@pytest.fixture(scope="session")
def dataset() -> Dataset:
    return Dataset.build()


@pytest.fixture(scope="session")
def engine(dataset: Dataset) -> ResearchEngine:
    return ResearchEngine(dataset)


@pytest.fixture(scope="session")
def run_result(engine: ResearchEngine) -> dict:
    return engine.run("分析人工智能专业与北京AI招聘市场的供需适配与技能缺口", include_template=True)

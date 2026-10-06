"""edu-material-harvest 插件接入层。

把插件（``vendor/edu-material-harvest``）采集到的官方公开材料接入 EduMatch 的
供给端数据流：调用插件 → 落盘到 ``data/source/收割/<校>/`` → 解析成与本地数据同构的
课程记录 / 正文缓存 / 事实，供 ``local`` / ``plugin`` / ``hybrid`` 三种数据来源模式使用。
"""

from .client import HarvestClient, HarvestConfig, HarvestOutcome, HarvestUnavailable
from .importer import HarvestImporter, HarvestImportResult

__all__ = [
    "HarvestClient",
    "HarvestConfig",
    "HarvestOutcome",
    "HarvestUnavailable",
    "HarvestImporter",
    "HarvestImportResult",
]

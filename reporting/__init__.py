"""报告交付层：主题、版式构件、任意院校专业的 HTML 渲染入口。

* ``theme``      - 页面 CSS/JS（唯一来源）
* ``components`` - 图表与版式构件（缺口条/雷达/数字卡/TSI Tree/S1/检索台账/导航）
* ``render``     - ``render_result(result, scope)`` 与命令行入口
"""

__all__ = ["render_result"]


def __getattr__(name: str):
    """Lazy export so `python -m reporting.render` 不会触发重复导入告警。"""
    if name == "render_result":
        from .render import render_result

        return render_result
    raise AttributeError(name)

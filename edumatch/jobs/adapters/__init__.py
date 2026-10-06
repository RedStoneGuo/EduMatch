"""Site adapters for lawful job-market collection."""

from .zhaopin import ZhaopinHarAdapter, get_adapter, list_adapters

__all__ = ["ZhaopinHarAdapter", "get_adapter", "list_adapters"]

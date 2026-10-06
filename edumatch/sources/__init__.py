"""Web source adapters for the data-acquisition (Phase 0) layer."""

from .education_web import EducationWebCollector, load_source_registry

__all__ = ["EducationWebCollector", "load_source_registry"]

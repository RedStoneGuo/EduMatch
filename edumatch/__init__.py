"""EduMatch core library: config, evidence, ontology, ingestion, tools, agent."""

from .config import PROJECT_ROOT, WORKSPACE_ROOT, Settings, load_settings

__all__ = ["PROJECT_ROOT", "WORKSPACE_ROOT", "Settings", "load_settings"]
__version__ = "2.0.0"

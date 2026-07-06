"""
NEXUS AI v4.0 — Configuration Package Init
Hardware: Intel i3 7th Gen · 12GB RAM · Ollama + Groq API

Exports the main configuration objects used across the entire application.
All imports are lazy to prevent circular dependencies at boot time.
"""

from functools import lru_cache
from nexus_config.settings import get_settings, validate_on_boot, APP_ROOT, BootStatus
from nexus_config.audit_logger import get_audit_logger, auto_redact, audited
from nexus_config.metrics import get_metrics_collector
from nexus_config.crash_reporter import write_crash_report
from nexus_config.health_check import run_health_check, HealthCheckResult

__all__ = [
    "get_settings",
    "validate_on_boot",
    "APP_ROOT",
    "BootStatus",
    "get_audit_logger",
    "auto_redact",
    "audited",
    "get_metrics_collector",
    "write_crash_report",
    "run_health_check",
    "HealthCheckResult",
]
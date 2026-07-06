"""
NEXUS AI v4.0 — Crash report generation and optional anonymous submission.
Hardware: Intel i3 7th Gen · 12GB RAM · Ollama + Groq API

Generates comprehensive crash reports on unhandled exceptions including:
- Exception details and traceback
- Last N audit log entries
- Current system state snapshot
- System metrics at time of crash

Reports are saved to APP_ROOT/crash_reports/ for debugging.
"""

import sys
import json
import datetime
import logging
import traceback
import time
from pathlib import Path
from typing import Optional, List, Dict, Any

from nexus_config.settings import get_settings, APP_ROOT

logger = logging.getLogger("nexus.crash")


def write_crash_report(
    exc_type: type,
    exc_value: BaseException,
    exc_traceback: Optional[object],
    last_audit_entries: Optional[List[Dict[str, Any]]] = None,
    last_state: Optional[Dict[str, Any]] = None,
) -> Path:
    """
    Generate and save a crash report to disk.
    
    Captures:
    - Timestamp and exception details
    - Full traceback
    - Last N audit log entries for context
    - Last state snapshot from the agent
    - System metrics (RAM, CPU, Python version, platform)
    
    Args:
        exc_type: The exception type class.
        exc_value: The exception instance.
        exc_traceback: The traceback object (from sys.exc_info()).
        last_audit_entries: Recent audit log entries (optional).
        last_state: Last known agent state snapshot (optional).
    
    Returns:
        Path to the saved crash report file.
    """
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = APP_ROOT / "crash_reports" / f"crash_{timestamp}.json"
    
    try:
        filepath.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    
    # Format traceback
    tb_lines = traceback.format_exception(exc_type, exc_value, exc_traceback)
    
    # Get audit entries from logger if not provided
    if last_audit_entries is None and "nexus_config.audit_logger" in sys.modules:
        try:
            from nexus_config.audit_logger import get_audit_logger
            last_audit_entries = get_audit_logger().get_recent_entries(10)
        except Exception:
            last_audit_entries = []
    
    report: Dict[str, Any] = {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "exception_type": exc_type.__name__ if hasattr(exc_type, "__name__") else str(exc_type),
        "exception_message": str(exc_value),
        "traceback": tb_lines,
        "last_audit_entries": last_audit_entries or [],
        "last_state_snapshot": last_state or {},
        "system_metrics": {
            "python_version": sys.version,
            "platform": sys.platform,
            "nexus_version": "4.0.0",
            "timestamp": time.time(),
        },
    }
    
    # Try to enrich with psutil metrics
    try:
        import psutil
        process = psutil.Process()
        report["system_metrics"]["ram_used_mb"] = round(process.memory_info().rss / (1024 * 1024), 1)
        report["system_metrics"]["cpu_percent"] = psutil.cpu_percent(interval=0.1)
        report["system_metrics"]["ram_available_mb"] = round(psutil.virtual_memory().available / (1024 * 1024), 1)
        report["system_metrics"]["disk_free_gb"] = round(psutil.disk_usage(APP_ROOT).free / (1024 ** 3), 2)
    except Exception:
        pass
    
    try:
        filepath.write_text(
            json.dumps(report, indent=2, default=str, ensure_ascii=False),
            encoding="utf-8",
        )
        logger.info(f"Crash report written to {filepath}")
    except Exception as e:
        logger.error(f"Failed to write crash report: {e}")
    
    return filepath
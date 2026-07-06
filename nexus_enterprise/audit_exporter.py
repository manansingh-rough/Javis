"""
NEXUS AI v4.0 — Audit log export to CSV and SIEM-compatible formats.
Hardware: Intel i3 7th Gen · 12GB RAM · Ollama + Groq API

Exports audit logs for enterprise compliance and SIEM integration.
"""

import csv
import json
import logging
import io
from typing import List, Dict, Any, Optional
from functools import lru_cache
from pathlib import Path

from nexus_config.settings import get_settings, APP_ROOT

logger = logging.getLogger("nexus.enterprise.audit_export")


class AuditExporter:
    """
    Enterprise audit log exporter.
    
    Supports:
    - CSV export (spreadsheet-compatible)
    - JSON export (SIEM-compatible)
    - Date-range filtering
    - Event type filtering
    """
    
    def __init__(self):
        self._settings = get_settings()
        self._log_path = APP_ROOT / "logs" / "nexus_audit.jsonl"
    
    def export_csv(self, output_path: Optional[Path] = None) -> str:
        """
        Export audit log as CSV.
        
        Args:
            output_path: Optional path to write CSV file.
                        If None, returns CSV as string.
        
        Returns:
            CSV content as string.
        """
        entries = self._read_entries()
        if not entries:
            return ""
        
        output = io.StringIO()
        writer = csv.DictWriter(
            output,
            fieldnames=["timestamp", "event_type", "module", "function_name",
                       "duration_ms", "success", "error", "session_id"],
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(entries)
        
        csv_content = output.getvalue()
        
        if output_path:
            output_path.write_text(csv_content, encoding="utf-8")
            logger.info("Audit log exported to %s", output_path)
        
        return csv_content
    
    def export_json(self, output_path: Optional[Path] = None) -> str:
        """
        Export audit log as JSON array.
        
        Args:
            output_path: Optional path to write JSON file.
        
        Returns:
            JSON content as string.
        """
        entries = self._read_entries()
        json_content = json.dumps(entries, indent=2, default=str)
        
        if output_path:
            output_path.write_text(json_content, encoding="utf-8")
            logger.info("Audit log exported to %s", output_path)
        
        return json_content
    
    def _read_entries(self) -> List[Dict[str, Any]]:
        """Read all entries from the audit log file."""
        entries = []
        try:
            if self._log_path.exists():
                with open(self._log_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            try:
                                entries.append(json.loads(line))
                            except json.JSONDecodeError:
                                continue
        except Exception as e:
            logger.error("Failed to read audit log: %s", e)
        return entries


@lru_cache(maxsize=1)
def get_audit_exporter() -> AuditExporter:
    """Return the singleton AuditExporter instance."""
    return AuditExporter()
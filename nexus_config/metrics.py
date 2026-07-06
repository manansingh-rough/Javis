"""
NEXUS AI v4.0 — Prometheus-compatible local metrics collector.
Hardware: Intel i3 7th Gen · 12GB RAM · Ollama + Groq API

Thread-safe metrics collection with counters, gauges, and histograms.
Metrics are periodically persisted to disk for observability.
"""

import logging
import json
import time
import threading
from typing import Dict, Optional, List, Any, Callable
from functools import lru_cache
from collections import defaultdict

from nexus_config.settings import get_settings, APP_ROOT

logger = logging.getLogger("nexus.metrics")
import logging


class NexusMetrics:
    """
    Thread-safe metrics collector for NEXUS AI.
    
    Supports:
    - Counters: cumulative counts (e.g., tool calls, errors)
    - Gauges: point-in-time values (e.g., RAM usage, active tools)
    - Histograms: value distributions with configurable buckets
    
    Metrics are written to APP_ROOT/metrics/nexus_metrics.json every 60 seconds.
    """
    
    def __init__(self):
        self._settings = get_settings()
        self._lock = threading.Lock()
        self._counters: Dict[str, int] = {}
        self._gauges: Dict[str, float] = {}
        self._histograms: Dict[str, List[float]] = defaultdict(list)
        self._file = APP_ROOT / "metrics" / "nexus_metrics.json"
        
        try:
            self._file.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        
        # Auto-save thread
        self._stop_event = threading.Event()
        self._save_thread = threading.Thread(
            target=self._save_loop,
            daemon=True,
            name="nexus-metrics-save",
        )
        self._save_thread.start()
    
    def counter(self, name: str, tags: Optional[Dict[str, str]] = None) -> int:
        """
        Increment a counter metric.
        
        Args:
            name: Metric name (e.g., "nexus_tool_calls_total").
            tags: Optional key-value tags for dimensional splitting.
        
        Returns:
            New counter value.
        """
        key = self._make_key(name, tags)
        with self._lock:
            self._counters[key] = self._counters.get(key, 0) + 1
            return self._counters[key]
    
    def gauge(self, name: str, value: float) -> None:
        """
        Set a gauge metric to a value.
        
        Args:
            name: Metric name (e.g., "nexus_system_ram_used_bytes").
            value: Current value of the gauge.
        """
        with self._lock:
            self._gauges[name] = value
    
    def histogram(self, name: str, value: float) -> None:
        """
        Record a value in a histogram.
        
        Histograms track distributions of values (e.g., tool durations).
        Buckets are computed at export time.
        
        Args:
            name: Metric name (e.g., "nexus_tool_duration_ms").
            value: The observed value to record.
        """
        with self._lock:
            self._histograms[name].append(value)
            # Keep only last 1000 values to bound memory
            if len(self._histograms[name]) > 1000:
                self._histograms[name] = self._histograms[name][-500:]
    
    def get_counters(self) -> Dict[str, int]:
        """Get snapshot of all counters."""
        with self._lock:
            return dict(self._counters)
    
    def get_gauges(self) -> Dict[str, float]:
        """Get snapshot of all gauges."""
        with self._lock:
            return dict(self._gauges)
    
    def get_histograms(self) -> Dict[str, Dict[str, float]]:
        """
        Get snapshot of histogram percentiles.
        
        Returns:
            Dict mapping metric name to {p50, p90, p95, p99, count}.
        """
        with self._lock:
            result = {}
            for name, values in self._histograms.items():
                if not values:
                    continue
                sorted_vals = sorted(values)
                result[name] = {
                    "min": sorted_vals[0],
                    "max": sorted_vals[-1],
                    "p50": sorted_vals[len(sorted_vals) // 2],
                    "p90": sorted_vals[int(len(sorted_vals) * 0.9)],
                    "p95": sorted_vals[int(len(sorted_vals) * 0.95)],
                    "p99": sorted_vals[int(len(sorted_vals) * 0.99)],
                    "count": len(sorted_vals),
                }
            return result
    
    def get_all_metrics(self) -> Dict[str, Any]:
        """Get complete snapshot of all metrics."""
        return {
            "counters": self.get_counters(),
            "gauges": self.get_gauges(),
            "histograms": self.get_histograms(),
        }
    
    def _make_key(self, name: str, tags: Optional[Dict[str, str]] = None) -> str:
        """Create dimensional key from name and tags."""
        if not tags:
            return name
        tag_str = json.dumps(tags, sort_keys=True)
        return f"{name}:{tag_str}"
    
    def _save_loop(self) -> None:
        """Background thread: persist metrics to disk periodically."""
        while not self._stop_event.is_set():
            if self._stop_event.wait(60):
                break
            try:
                with self._lock:
                    data = {
                        "timestamp": time.time(),
                        "counters": dict(self._counters),
                        "gauges": dict(self._gauges),
                    }
                    self._file.write_text(
                        json.dumps(data, indent=2, default=str),
                        encoding="utf-8",
                    )
            except Exception:
                pass
    
    def shutdown(self) -> None:
        """Stop the save loop and flush metrics to disk."""
        self._stop_event.set()
        try:
            data = self.get_all_metrics()
            data["timestamp"] = time.time()
            self._file.write_text(
                json.dumps(data, indent=2, default=str),
                encoding="utf-8",
            )
        except Exception:
            pass


@lru_cache(maxsize=1)
def get_metrics_collector() -> NexusMetrics:
    """
    Return the singleton NexusMetrics instance.
    
    Returns:
        NexusMetrics: The singleton metrics collector.
    """
    return NexusMetrics()
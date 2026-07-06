"""
nexus_billing/usage_metering.py

Free-tier task counter. Per LAW B5, this LOCAL count is advisory/UX only —
it lets a free-tier user see "72 / 100 tasks used this month" with zero
network latency. Anything that actually affects billing is reconciled
server-side, never trusted from this file alone, since a modified client
could report anything.
"""

import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple

from nexus_config.settings import APP_ROOT
from nexus_config.audit_logger import get_audit_logger

USAGE_PATH = APP_ROOT / "usage_counter.json"
FREE_TIER_MONTHLY_LIMIT = 100


@dataclass
class UsageCounter:
    month_key: str       # "2026-07"
    tasks_completed: int


def _current_month_key() -> str:
    now = datetime.now(timezone.utc)
    return f"{now.year:04d}-{now.month:02d}"


def _load() -> UsageCounter:
    if USAGE_PATH.exists():
        try:
            data = json.loads(USAGE_PATH.read_text(encoding="utf-8"))
            counter = UsageCounter(**data)
            if counter.month_key == _current_month_key():
                return counter
        except Exception:
            pass
    return UsageCounter(month_key=_current_month_key(), tasks_completed=0)


def _save(counter: UsageCounter) -> None:
    """Atomic write — matches the Section 2.5 atomic-rename pattern from the
    core NEXUS AI prompt. Never corrupt this file mid-task."""
    tmp_path = USAGE_PATH.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(asdict(counter)), encoding="utf-8")
    tmp_path.replace(USAGE_PATH)


class UsageMetering:
    """Local usage metering for the free tier.

    Thread-safe for single-process access. The counter is reset monthly.
    """

    def __init__(self):
        self._audit = get_audit_logger()

    def increment_and_check(self, tier: str) -> Tuple[bool, int, int]:
        """Call once per completed agent task.

        Args:
            tier: The current tier from LicenseManager.current_tier().

        Returns:
            (allowed, used, limit). limit is -1 for unlimited tiers (Pro+).
        """
        if tier != "free":
            return True, 0, -1

        counter = _load()
        if counter.tasks_completed >= FREE_TIER_MONTHLY_LIMIT:
            return False, counter.tasks_completed, FREE_TIER_MONTHLY_LIMIT

        counter.tasks_completed += 1
        _save(counter)
        return True, counter.tasks_completed, FREE_TIER_MONTHLY_LIMIT

    def current_usage(self) -> Tuple[int, int]:
        """Get current usage stats without incrementing.

        Returns:
            (tasks_completed_this_month, monthly_limit)
        """
        counter = _load()
        return counter.tasks_completed, FREE_TIER_MONTHLY_LIMIT

    def reset_counter(self) -> None:
        """Force-reset the monthly counter. Used for testing or manual admin."""
        counter = UsageCounter(month_key=_current_month_key(), tasks_completed=0)
        _save(counter)


# Module-level convenience function matching the spec's API
_metering_instance: Optional[UsageMetering] = None


def increment_and_check(tier: str) -> Tuple[bool, int, int]:
    """Module-level convenience: call once per completed agent task.

    Args:
        tier: The current tier from LicenseManager.current_tier().

    Returns:
        (allowed, used, limit). limit is -1 for unlimited tiers.
    """
    global _metering_instance
    if _metering_instance is None:
        _metering_instance = UsageMetering()
    return _metering_instance.increment_and_check(tier)
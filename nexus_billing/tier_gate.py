"""
nexus_billing/tier_gate.py

Tier-gating decorator for tools and features.

Usage:
    @requires_tier("personal_pro")
    @tool
    def sync_memory_to_cloud(...) -> str:
        ...

The decorator enforces LAW B1: never trust the client for entitlement.
Every gated call re-derives the current tier from the signed LicenseToken
via get_license_manager().current_tier().
"""

import json
from functools import wraps
from typing import Callable, Any, Optional

from nexus_billing.license_manager import get_license_manager

# Tier ranking for comparison. Higher index = higher privilege.
TIER_RANK = {"free": 0, "personal_pro": 1, "team": 2, "enterprise": 3}


def requires_tier(minimum_tier: str):
    """Decorator that gates a tool or function behind a minimum subscription tier.

    Args:
        minimum_tier: The minimum tier required ("free", "personal_pro", "team", "enterprise").

    Returns:
        A decorator that wraps the function with entitlement checking.

    The wrapped function returns a JSON dict with the standard NEXUS plugin
    contract (matching v4.0 LAW 5):
        {"success": bool, "result": any, "error": str|null}
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            current = get_license_manager().current_tier()
            if TIER_RANK[current] < TIER_RANK[minimum_tier]:
                return json.dumps({
                    "success": False,
                    "result": None,
                    "error": (
                        f"This capability requires {_tier_display_name(minimum_tier)} "
                        f"or higher. You're currently on {_tier_display_name(current)}. "
                        f"Upgrade at https://nexus-ai.dev/upgrade"
                    ),
                })
            return func(*args, **kwargs)
        return wrapper
    return decorator


def check_tier_access(minimum_tier: str) -> tuple[bool, Optional[str]]:
    """Programmatic tier check (non-decorator) for use in service-layer code.

    Args:
        minimum_tier: The minimum tier required.

    Returns:
        (allowed: bool, error_message: Optional[str])
    """
    current = get_license_manager().current_tier()
    if TIER_RANK[current] < TIER_RANK[minimum_tier]:
        return False, (
            f"This capability requires {_tier_display_name(minimum_tier)} "
            f"or higher. You're currently on {_tier_display_name(current)}."
        )
    return True, None


def _tier_display_name(tier: str) -> str:
    """Convert internal tier name to a user-facing display string."""
    names = {
        "free": "Free",
        "personal_pro": "Personal Pro",
        "team": "Team",
        "enterprise": "Enterprise",
    }
    return names.get(tier, tier.replace("_", " ").title())
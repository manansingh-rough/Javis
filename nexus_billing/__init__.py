"""
NEXUS AI v4.0 — Billing & Licensing Module (Client-Side)

Offline-first license validation, tier gating, usage metering, and
communication with the NEXUS Cloud billing backend.

Architecture:
  - LicenseManager: Ed25519-signed license token verification (air-gapped safe)
  - @requires_tier decorator: feature/tool-level entitlement enforcement
  - UsageMetering: local free-tier task counter (advisory/UX only)
  - BillingClient: communicates with cloud backend for checkout/portal/refresh
  - OfflineGrace: grace-period messaging surfaced to the HUD
"""

from .license_manager import LicenseManager, LicenseToken, get_license_manager, Tier, GRACE_PERIOD_DAYS
from .tier_gate import requires_tier, TIER_RANK
from .usage_metering import UsageMetering, increment_and_check
from .billing_client import BillingClient, get_billing_client
from .offline_grace import OfflineGrace

__all__ = [
    "LicenseManager",
    "LicenseToken",
    "get_license_manager",
    "Tier",
    "GRACE_PERIOD_DAYS",
    "requires_tier",
    "TIER_RANK",
    "UsageMetering",
    "increment_and_check",
    "BillingClient",
    "get_billing_client",
    "OfflineGrace",
]
"""
nexus_billing/license_manager.py

Offline-first license validation for NEXUS AI.

Design goal: a paying Enterprise customer running fully air-gapped (the Tier 4
promise in the core NEXUS AI prompt) must be able to prove their entitlement
WITHOUT any network call. A Personal Pro / Team customer who is online gets a
periodic silent refresh so cancellations/refunds propagate within days.

Cryptographic model:
  - The billing backend holds an Ed25519 PRIVATE key. Never shipped to any client.
  - The corresponding Ed25519 PUBLIC key is embedded as a constant below and
    shipped inside every desktop install.
  - At checkout/renewal the backend issues a small signed JSON payload (a
    LicenseToken) containing tier, seats, feature flags, issue time, and
    expiry. The client verifies the signature locally.
"""

import json
import base64
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Literal

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.exceptions import InvalidSignature

from nexus_config.settings import APP_ROOT, get_settings
from nexus_config.audit_logger import get_audit_logger

# ─── PUBLIC KEY (safe to embed — this only lets us VERIFY, never issue) ──────
# Generate the keypair once, server-side only:
#   openssl genpkey -algorithm ed25519 -out license_signing_private.pem
#   openssl pkey -in license_signing_private.pem -pubout -out license_signing_public.pem
# The private key NEVER leaves the billing backend's secrets manager.
NEXUS_LICENSE_PUBLIC_KEY_B64 = "HI2kKg90OQtTNpB50n1jJbH/O0NnpGcAY87h29/xFKc="

LICENSE_CACHE_PATH = APP_ROOT / "license.json"

Tier = Literal["free", "personal_pro", "team", "enterprise"]

# LAW B2 — grace period before a lapsed/unreachable license soft-downgrades.
GRACE_PERIOD_DAYS: dict[str, int] = {
    "free": 0,
    "personal_pro": 14,
    "team": 14,
    "enterprise": 90,   # air-gapped: long grace, manual refresh via admin_cli
}


@dataclass
class LicenseToken:
    user_id: str
    org_id: Optional[str]
    tier: Tier
    seats: int
    features: List[str]
    issued_at: str        # ISO 8601
    expires_at: str        # ISO 8601 — subscription period end, not license permanence
    signature: str          # base64 Ed25519 signature over the canonical payload


def _canonical_payload(token: LicenseToken) -> bytes:
    """Deterministic bytes for everything EXCEPT the signature. Field order and
    formatting here must exactly match what the backend signs (Section 6.1's
    counterpart in license_issuer.py)."""
    payload = {
        "user_id": token.user_id,
        "org_id": token.org_id,
        "tier": token.tier,
        "seats": token.seats,
        "features": sorted(token.features),
        "issued_at": token.issued_at,
        "expires_at": token.expires_at,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def verify_license_signature(token: LicenseToken) -> bool:
    """Verify the Ed25519 signature entirely offline. No network call.
    Returns False on any malformed input rather than raising — callers must
    treat False as 'fall back to free tier', never crash the app."""
    try:
        public_key = Ed25519PublicKey.from_public_bytes(
            base64.b64decode(NEXUS_LICENSE_PUBLIC_KEY_B64)
        )
        public_key.verify(base64.b64decode(token.signature), _canonical_payload(token))
        return True
    except (InvalidSignature, ValueError, Exception):
        return False


class LicenseManager:
    """Loads, verifies, and caches the active license. Read path is safe from
    any thread; refresh/write happens on the background services thread
    (Thread 3 per the core NEXUS AI Section 2.4 thread plan), never the UI
    thread."""

    def __init__(self):
        self._settings = get_settings()
        self._audit = get_audit_logger()
        self._cached_token: Optional[LicenseToken] = None
        self._load_from_disk()

    def _load_from_disk(self) -> None:
        if not LICENSE_CACHE_PATH.exists():
            return
        try:
            raw = json.loads(LICENSE_CACHE_PATH.read_text(encoding="utf-8"))
            token = LicenseToken(**raw)
            if verify_license_signature(token):
                self._cached_token = token
            else:
                self._audit.log(
                    event_type="SECURITY_REJECT",
                    data={"reason": "license_signature_invalid"},
                    module="nexus_billing.license_manager",
                    function_name="_load_from_disk",
                    success=False,
                )
        except Exception as exc:
            self._audit.log(
                event_type="SYSTEM_ERROR",
                data={"reason": "license_load_failed", "error": str(exc)},
                module="nexus_billing.license_manager",
                function_name="_load_from_disk",
                success=False,
            )

    def install_token(self, raw_token_json: str) -> bool:
        """Called by the onboarding wizard or `nexus license activate <file>`.
        Validates BEFORE writing to disk — never persist an unverifiable token."""
        try:
            token = LicenseToken(**json.loads(raw_token_json))
        except Exception:
            return False

        if not verify_license_signature(token):
            self._audit.log(
                event_type="SECURITY_REJECT",
                data={"reason": "license_install_signature_invalid"},
                module="nexus_billing.license_manager",
                function_name="install_token",
                success=False,
            )
            return False

        LICENSE_CACHE_PATH.write_text(json.dumps(asdict(token)), encoding="utf-8")
        self._cached_token = token
        self._audit.log(
            event_type="CONFIG_CHANGE",
            data={"tier": token.tier, "org_id": token.org_id},
            module="nexus_billing.license_manager",
            function_name="install_token",
            success=True,
        )
        return True

    def current_tier(self) -> Tier:
        """The single source of truth every tool-gate and UI feature flag
        must call. NEVER read settings.TIER directly for entitlement
        decisions — that field is a display cache, not the trust boundary
        (LAW B1)."""
        if self._cached_token is None:
            return "free"

        expires_at = datetime.fromisoformat(self._cached_token.expires_at)
        grace_days = GRACE_PERIOD_DAYS.get(self._cached_token.tier, 0)
        hard_cutoff = expires_at + timedelta(days=grace_days)

        if datetime.now(timezone.utc) > hard_cutoff:
            # Past subscription end AND past grace period: soft-downgrade.
            # Never delete synthesized tools, memory, or workflows (LAW B2) —
            # only gate tier-restricted features going forward.
            return "free"

        return self._cached_token.tier

    def has_feature(self, feature_name: str) -> bool:
        if self._cached_token is None:
            return False
        return feature_name in self._cached_token.features

    def days_until_hard_cutoff(self) -> Optional[int]:
        """Used by the HUD to show a friendly 'renew within N days' banner."""
        if self._cached_token is None:
            return None
        expires_at = datetime.fromisoformat(self._cached_token.expires_at)
        grace_days = GRACE_PERIOD_DAYS.get(self._cached_token.tier, 0)
        remaining = (expires_at + timedelta(days=grace_days) - datetime.now(timezone.utc)).days
        return max(remaining, 0)

    def get_token_info(self) -> Optional[dict]:
        """Return the current token info for display/debug purposes.
        Never use this for entitlement decisions — always call current_tier()."""
        if self._cached_token is None:
            return None
        return {
            "tier": self._cached_token.tier,
            "org_id": self._cached_token.org_id,
            "seats": self._cached_token.seats,
            "features": self._cached_token.features,
            "issued_at": self._cached_token.issued_at,
            "expires_at": self._cached_token.expires_at,
            "days_remaining": self.days_until_hard_cutoff(),
        }


_manager: Optional[LicenseManager] = None


def get_license_manager() -> LicenseManager:
    global _manager
    if _manager is None:
        _manager = LicenseManager()
    return _manager
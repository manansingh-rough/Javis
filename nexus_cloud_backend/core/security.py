"""
nexus_cloud_backend/core/security.py

Ed25519 signing for license tokens, JWT auth helpers, and password hashing.
"""

import base64
import json
from datetime import datetime, timezone, timedelta
from typing import Optional

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization

from nexus_cloud_backend.core.config import get_settings


def get_signing_key() -> Ed25519PrivateKey:
    """Load the Ed25519 private key from settings.

    The key is stored as base64-encoded raw bytes in the environment.
    """
    settings = get_settings()
    key_bytes = base64.b64decode(settings.LICENSE_SIGNING_PRIVATE_KEY)
    return Ed25519PrivateKey.from_private_bytes(key_bytes)


def sign_license_payload(payload: dict) -> str:
    """Sign a license payload with the Ed25519 private key.

    Args:
        payload: Dict with fields: user_id, org_id, tier, seats, features,
                issued_at, expires_at. Must match the canonical ordering
                expected by the client's _canonical_payload().

    Returns:
        Base64-encoded Ed25519 signature.
    """
    # Canonical serialization — must match nexus_billing.license_manager._canonical_payload
    canonical = {
        "user_id": payload["user_id"],
        "org_id": payload.get("org_id"),
        "tier": payload["tier"],
        "seats": payload.get("seats", 1),
        "features": sorted(payload.get("features", [])),
        "issued_at": payload["issued_at"],
        "expires_at": payload["expires_at"],
    }
    data = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")

    private_key = get_signing_key()
    signature = private_key.sign(data)
    return base64.b64encode(signature).decode("utf-8")
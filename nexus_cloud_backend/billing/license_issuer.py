"""
nexus_cloud_backend/billing/license_issuer.py

Issues signed LicenseTokens for the desktop client.

Called by webhook handlers after successful checkout/renewal, and by the
license refresh endpoint when the client polls for updates.

The /refresh endpoint looks up the user's active subscription from the
database and issues a new token if the subscription is still active.
"""

import json
import uuid
import logging
from datetime import datetime, timezone
from typing import Optional, List

from fastapi import APIRouter, HTTPException, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus_cloud_backend.core.security import sign_license_payload
from nexus_cloud_backend.core.config import get_settings
from nexus_cloud_backend.db.models import User, Subscription, TierEnum
from nexus_cloud_backend.db.session import get_async_db

logger = logging.getLogger("nexus.cloud.billing.license")

router = APIRouter(prefix="/license", tags=["billing"])


def issue_license_token(
    user_id: str,
    tier: str,
    expires_at: datetime,
    org_id: Optional[str] = None,
    seats: int = 1,
    features: Optional[List[str]] = None,
) -> str:
    """Create and sign a license token for a user.

    Args:
        user_id: The user's UUID.
        tier: Subscription tier ("personal_pro", "team", "enterprise").
        expires_at: When the subscription period ends.
        org_id: Optional organization ID for Team/Enterprise.
        seats: Number of seats (default 1).
        features: List of feature flags.

    Returns:
        JSON string of the signed LicenseToken, ready to send to the client.
    """
    if features is None:
        # Default feature sets per tier — keep in sync with the pricing table
        feature_map = {
            "free": ["local_tasks", "ollama_inference"],
            "personal_pro": [
                "local_tasks", "ollama_inference", "cloud_memory_sync",
                "hosted_api_key", "workflow_library", "unlimited_tasks",
            ],
            "team": [
                "local_tasks", "ollama_inference", "cloud_memory_sync",
                "hosted_api_key", "workflow_library", "unlimited_tasks",
                "shared_workflows", "org_memory", "admin_dashboard", "google_sso",
            ],
            "enterprise": [
                "local_tasks", "ollama_inference", "cloud_memory_sync",
                "hosted_api_key", "workflow_library", "unlimited_tasks",
                "shared_workflows", "org_memory", "admin_dashboard",
                "google_sso", "saml_sso", "policy_engine", "audit_export",
                "air_gapped", "support_sla",
            ],
        }
        features = feature_map.get(tier, feature_map["free"])

    now = datetime.now(timezone.utc)

    payload = {
        "user_id": user_id,
        "org_id": org_id,
        "tier": tier,
        "seats": seats,
        "features": features,
        "issued_at": now.isoformat(),
        "expires_at": expires_at.isoformat(),
    }

    signature = sign_license_payload(payload)
    payload["signature"] = signature

    return json.dumps(payload, separators=(",", ":"))


@router.get("/refresh")
async def refresh_license(
    user_id: str = Query(..., description="The user's UUID"),
    db: AsyncSession = Depends(get_async_db),
):
    """Refresh a license token for the requesting user.

    Called periodically by the desktop client. Returns a new signed token
    if the user's subscription is still active.

    Args:
        user_id: The user's UUID (passed as query parameter).

    Returns:
        {"token": "..."} with a signed LicenseToken JSON string.

    Raises:
        404: If the user is not found.
        402: If the user has no active subscription.
    """
    # Look up the user
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Look up the user's active subscription
    result = await db.execute(
        select(Subscription)
        .where(Subscription.user_id == user_id)
        .where(Subscription.status.in_(["active", "trialing"]))
        .order_by(Subscription.current_period_end.desc())
        .limit(1)
    )
    sub = result.scalar_one_or_none()

    if sub:
        # Active subscription found — issue token with subscription details
        tier = sub.tier.value
        expires_at = sub.current_period_end
        logger.info(
            "License refresh for user %s: tier=%s, expires=%s",
            user_id, tier, expires_at.isoformat(),
        )
    else:
        # No active subscription — issue a free-tier token with short expiry
        tier = "free"
        expires_at = datetime.now(timezone.utc).replace(
            hour=23, minute=59, second=59, microsecond=0
        )
        logger.info("License refresh for user %s: no active sub, issuing free token", user_id)

    token = issue_license_token(
        user_id=user_id,
        org_id=user.org_id,
        tier=tier,
        expires_at=expires_at,
    )
    return {"token": token}


@router.post("/activate")
async def activate_license(
    license_key: str = Query(..., description="License key for manual activation"),
    db: AsyncSession = Depends(get_async_db),
):
    """Activate a license key (for offline/Enterprise manual activation).

    In production, this would validate the license key against the database
    and return a signed token. For now, returns a stub enterprise token.

    Args:
        license_key: The license key to activate.

    Returns:
        {"token": "..."} with a signed LicenseToken.
    """
    # Stub: accept any key and issue an enterprise token
    logger.info("License activation requested with key: %s", license_key[:8] + "...")

    expires_at = datetime.now(timezone.utc).replace(
        year=datetime.now(timezone.utc).year + 1
    )
    token = issue_license_token(
        user_id=str(uuid.uuid4()),
        tier="enterprise",
        expires_at=expires_at,
        features=[
            "local_tasks", "ollama_inference", "unlimited_tasks",
            "air_gapped", "support_sla",
        ],
    )
    return {"token": token}
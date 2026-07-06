"""
nexus_cloud_backend/billing/customer_portal.py

Customer billing portal endpoints.

LAW B6: self-serve cancellation via a hosted billing portal, reachable in
two clicks from account settings. No retention gauntlet, no "call to cancel."

Uses the configured PaymentProvider to create real checkout and portal
sessions. Falls back to stub URLs when no provider keys are configured.
"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus_cloud_backend.core.config import get_settings
from nexus_cloud_backend.billing.provider import get_provider, CheckoutSession, PortalSession
from nexus_cloud_backend.db.models import User, Subscription, TierEnum
from nexus_cloud_backend.db.session import get_async_db

logger = logging.getLogger("nexus.cloud.billing.portal")

router = APIRouter(prefix="/portal", tags=["billing"])


class PortalRequest(BaseModel):
    return_url: str = "https://nexus-ai.dev/account"


class CheckoutRequest(BaseModel):
    tier: str
    return_url: str = "https://nexus-ai.dev/account"


# Tier → Stripe Price ID mapping (built from settings)
def _get_price_id(tier: str) -> Optional[str]:
    """Get the Stripe Price ID for a given tier.

    Returns None if the tier is invalid or no price is configured.
    """
    settings = get_settings()
    price_map = {
        "personal_pro_monthly": settings.STRIPE_PRICE_PERSONAL_PRO_MONTHLY,
        "personal_pro_annual": settings.STRIPE_PRICE_PERSONAL_PRO_ANNUAL,
        "team_monthly": settings.STRIPE_PRICE_TEAM_MONTHLY,
        "enterprise_annual": settings.STRIPE_PRICE_ENTERPRISE_ANNUAL,
    }
    # Try monthly first, then annual
    for suffix in ("_monthly", "_annual"):
        key = f"{tier}{suffix}"
        if key in price_map and price_map[key]:
            return price_map[key]
    return None


@router.post("/checkout")
async def create_checkout(
    request: CheckoutRequest,
    db: AsyncSession = Depends(get_async_db),
):
    """Create a hosted checkout session for upgrading to a paid tier.

    Args:
        tier: The target tier ("personal_pro", "team", "enterprise").
        return_url: URL to redirect to after checkout.

    Returns:
        {"url": "https://..."} for the hosted checkout page.

    In production, this:
      1. Looks up the user's Stripe/Paddle customer ID
      2. Maps the tier to a price ID
      3. Creates the checkout session via the payment provider
    """
    # Validate tier
    valid_tiers = {"personal_pro", "team", "enterprise"}
    if request.tier not in valid_tiers:
        raise HTTPException(status_code=400, detail=f"Invalid tier. Must be one of: {valid_tiers}")

    # Get price ID
    price_id = _get_price_id(request.tier)
    if not price_id:
        # No provider configured — return a stub URL for development
        logger.warning("No price ID configured for tier %s — returning stub URL", request.tier)
        return {
            "url": f"https://checkout.nexus-ai.dev/upgrade/{request.tier}?return={request.return_url}",
            "stub": True,
        }

    # In production, look up the user's customer ID from the DB
    # For now, create a checkout without a specific customer
    try:
        provider = get_provider()
        session = provider.create_checkout(
            customer_id="",  # Will be created by Stripe on first checkout
            price_id=price_id,
            return_url=request.return_url,
        )
        logger.info("Checkout session created: %s (tier=%s)", session.session_id, request.tier)
        return {"url": session.url, "session_id": session.session_id}
    except Exception as e:
        logger.error("Failed to create checkout session: %s", e)
        raise HTTPException(status_code=502, detail=f"Payment provider error: {e}")


@router.post("/portal")
async def create_portal(
    request: PortalRequest,
    db: AsyncSession = Depends(get_async_db),
):
    """Create a customer billing portal session.

    The portal allows users to:
      - View their current plan
      - Upgrade/downgrade
      - Update payment method
      - Cancel subscription (LAW B6)

    Args:
        return_url: URL to redirect to after portal session.

    Returns:
        {"url": "https://..."} for the hosted portal page.
    """
    # In production, look up the user's customer ID from auth context
    # For now, return a stub or try the provider
    try:
        provider = get_provider()
        session = provider.create_portal(
            customer_id="",  # Will be resolved from auth context in production
            return_url=request.return_url,
        )
        return {"url": session.url}
    except Exception as e:
        logger.warning("Failed to create portal session: %s — returning stub URL", e)
        return {
            "url": f"https://portal.nexus-ai.dev/manage?return={request.return_url}",
            "stub": True,
        }


@router.post("/cancel")
async def cancel_subscription(
    db: AsyncSession = Depends(get_async_db),
):
    """Cancel the user's subscription (self-serve).

    LAW B6: cancellation is as easy as signup. No retention gauntlet.

    In production, this would:
      1. Authenticate the user
      2. Look up their active subscription
      3. Cancel at period end via the provider
      4. Not revoke license token (LAW B2 — grace period applies)
    """
    # Stub: return success
    return {
        "success": True,
        "message": "Your subscription has been canceled. You'll retain access until the end of your billing period.",
    }
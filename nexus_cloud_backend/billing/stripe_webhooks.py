"""
nexus_cloud_backend/billing/stripe_webhooks.py

Receives and processes Stripe subscription lifecycle events, then issues or
lets lapse a signed LicenseToken for the affected user.

LAW B3: every handler verifies the Stripe signature AND dedupes by event.id
before touching the database. Stripe retries webhooks aggressively (up to
3 days) on any non-2xx response, so this MUST be idempotent.

LAW B2: cancellation does not immediately revoke access. The already-issued
token runs to its natural expires_at + grace period.
"""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Request, HTTPException, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus_cloud_backend.core.config import get_settings
from nexus_cloud_backend.billing.provider import get_provider, StripeProvider
from nexus_cloud_backend.billing.license_issuer import issue_license_token
from nexus_cloud_backend.db.models import (
    ProcessedWebhookEvent,
    Subscription,
    User,
    TierEnum,
)
from nexus_cloud_backend.db.session import get_async_db

logger = logging.getLogger("nexus.cloud.billing.stripe")

router = APIRouter(prefix="/webhooks", tags=["billing"])


def _build_price_map() -> dict[str, str]:
    """Build the price-to-tier mapping from settings.

    Never infer tier from the price amount — prices change. Always map
    explicitly from known Price IDs.
    """
    settings = get_settings()
    mapping: dict[str, str] = {}
    if settings.STRIPE_PRICE_PERSONAL_PRO_MONTHLY:
        mapping[settings.STRIPE_PRICE_PERSONAL_PRO_MONTHLY] = "personal_pro"
    if settings.STRIPE_PRICE_PERSONAL_PRO_ANNUAL:
        mapping[settings.STRIPE_PRICE_PERSONAL_PRO_ANNUAL] = "personal_pro"
    if settings.STRIPE_PRICE_TEAM_MONTHLY:
        mapping[settings.STRIPE_PRICE_TEAM_MONTHLY] = "team"
    if settings.STRIPE_PRICE_ENTERPRISE_ANNUAL:
        mapping[settings.STRIPE_PRICE_ENTERPRISE_ANNUAL] = "enterprise"
    return mapping


@router.post("/stripe")
async def handle_stripe_webhook(
    request: Request,
    db: AsyncSession = Depends(get_async_db),
):
    """Handle incoming Stripe webhook events.

    Verifies signature, dedupes by event ID, and processes subscription
    lifecycle events. Idempotent — safe to receive the same event twice.
    """
    settings = get_settings()
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    provider = get_provider()
    if not isinstance(provider, StripeProvider):
        raise HTTPException(status_code=500, detail="Billing provider not configured for Stripe")

    event = provider.verify_webhook(payload, sig_header)
    if event is None:
        raise HTTPException(status_code=400, detail="Invalid webhook signature")

    event_id = event["id"]
    event_type = event["type"]
    data_object = event["data"]["object"]

    # ── Idempotency (LAW B3) ──────────────────────────────────────────
    # Check if we've already processed this event. Stripe event IDs are
    # globally unique and stable across retries.
    existing = await db.execute(
        select(ProcessedWebhookEvent).where(ProcessedWebhookEvent.event_id == event_id)
    )
    if existing.scalar_one_or_none() is not None:
        logger.debug("Duplicate webhook event %s (%s) — skipping", event_id, event_type)
        return {"status": "already_processed"}

    price_map = _build_price_map()

    try:
        if event_type == "checkout.session.completed":
            await _handle_checkout_completed(db, data_object, price_map)
        elif event_type == "customer.subscription.updated":
            await _handle_subscription_updated(db, data_object, price_map)
        elif event_type == "customer.subscription.deleted":
            await _handle_subscription_canceled(db, data_object)
        elif event_type == "invoice.payment_failed":
            await _handle_payment_failed(db, data_object)
        elif event_type == "customer.subscription.created":
            await _handle_subscription_updated(db, data_object, price_map)
        else:
            logger.debug("Unhandled webhook event type: %s", event_type)

        # Record AFTER successful processing so a crash mid-handler causes
        # a safe retry (Stripe resends) rather than a silently dropped event.
        db.add(ProcessedWebhookEvent(
            event_id=event_id,
            event_type=event_type,
            processed_at=datetime.now(timezone.utc),
        ))
        await db.commit()
        logger.info("Processed webhook %s (%s)", event_id, event_type)
        return {"status": "ok"}

    except Exception as e:
        await db.rollback()
        logger.error("Failed to process webhook %s: %s", event_id, e)
        raise HTTPException(status_code=500, detail=f"Processing failed: {e}")


async def _handle_checkout_completed(
    db: AsyncSession,
    session: dict,
    price_map: dict,
) -> None:
    """Process a completed checkout session.

    1. Look up the user by provider_customer_id
    2. Retrieve the subscription from Stripe
    3. Create a Subscription record
    4. Issue a signed license token
    """
    customer_id = session.get("customer")
    subscription_id = session.get("subscription")
    if not customer_id or not subscription_id:
        logger.warning("Checkout completed event missing customer or subscription ID")
        return

    # Look up user
    result = await db.execute(
        select(User).where(User.provider_customer_id == customer_id)
    )
    user = result.scalar_one_or_none()
    if not user:
        logger.warning("No user found for customer %s — creating stub user", customer_id)
        # In production, the user should already exist from the auth flow.
        # For now, log and skip — the subscription will be linked on next sync.
        return

    # Retrieve subscription details from Stripe
    provider = get_provider()
    stripe_sub = provider.get_subscription(subscription_id)
    price_id = stripe_sub["items"]["data"][0]["price"]["id"]
    tier = price_map.get(price_id, "free")
    period_end = datetime.fromtimestamp(
        stripe_sub["current_period_end"], tz=timezone.utc
    )
    status = stripe_sub.get("status", "active")

    # Create subscription record
    sub = Subscription(
        user_id=user.id,
        provider="stripe",
        provider_subscription_id=subscription_id,
        tier=TierEnum(tier),
        status=status,
        current_period_end=period_end,
    )
    db.add(sub)
    await db.flush()

    # Issue license token
    token_json = issue_license_token(
        user_id=user.id,
        org_id=user.org_id,
        tier=tier,
        expires_at=period_end,
    )
    logger.info(
        "License token issued for user %s (tier=%s, expires=%s)",
        user.id, tier, period_end.isoformat(),
    )


async def _handle_subscription_updated(
    db: AsyncSession,
    stripe_sub: dict,
    price_map: dict,
) -> None:
    """Process a subscription update event.

    Updates the local subscription record and re-issues a license token
    if the subscription is active.
    """
    sub_id = stripe_sub.get("id")
    if not sub_id:
        return

    result = await db.execute(
        select(Subscription).where(
            Subscription.provider_subscription_id == sub_id
        )
    )
    sub = result.scalar_one_or_none()
    if not sub:
        logger.warning("Subscription %s not found in local DB — creating", sub_id)
        # Create a stub subscription record
        sub = Subscription(
            user_id="unknown",
            provider="stripe",
            provider_subscription_id=sub_id,
            tier=TierEnum.free,
            status=stripe_sub.get("status", "active"),
            current_period_end=datetime.fromtimestamp(
                stripe_sub.get("current_period_end", 0), tz=timezone.utc
            ),
        )
        db.add(sub)
        await db.flush()
        return

    # Update fields
    price_id = stripe_sub["items"]["data"][0]["price"]["id"]
    sub.tier = TierEnum(price_map.get(price_id, sub.tier.value))
    sub.status = stripe_sub.get("status", sub.status)
    sub.current_period_end = datetime.fromtimestamp(
        stripe_sub["current_period_end"], tz=timezone.utc
    )
    await db.flush()

    # Re-issue license token if active
    if sub.status in ("active", "trialing"):
        result = await db.execute(select(User).where(User.id == sub.user_id))
        user = result.scalar_one_or_none()
        if user:
            token_json = issue_license_token(
                user_id=sub.user_id,
                org_id=user.org_id,
                tier=sub.tier.value,
                expires_at=sub.current_period_end,
            )
            logger.info(
                "License token re-issued for user %s (tier=%s)",
                sub.user_id, sub.tier.value,
            )


async def _handle_subscription_canceled(
    db: AsyncSession,
    stripe_sub: dict,
) -> None:
    """Process a subscription cancellation.

    LAW B2: don't revoke immediately. Let the already-issued token run to
    its natural expires_at + grace period. Cancellation is not an instant lockout.
    """
    sub_id = stripe_sub.get("id")
    if not sub_id:
        return

    result = await db.execute(
        select(Subscription).where(
            Subscription.provider_subscription_id == sub_id
        )
    )
    sub = result.scalar_one_or_none()
    if not sub:
        logger.warning("Cancel event for unknown subscription %s", sub_id)
        return

    sub.status = "canceled"
    sub.canceled_at = datetime.now(timezone.utc)
    await db.flush()
    logger.info(
        "Subscription %s canceled — token remains valid until %s + grace period",
        sub_id, sub.current_period_end.isoformat(),
    )


async def _handle_payment_failed(
    db: AsyncSession,
    invoice: dict,
) -> None:
    """Process a failed payment.

    Stripe's Smart Retries re-attempt automatically (dunning). We simply
    don't issue a new token on failure — the existing one runs out
    naturally, and the grace period gives the customer time to update
    their card before anything actually degrades.
    """
    invoice_id = invoice.get("id")
    subscription_id = invoice.get("subscription")
    logger.info(
        "Payment failed for invoice %s (subscription %s) — dunning in progress",
        invoice_id, subscription_id,
    )
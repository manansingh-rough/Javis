"""
nexus_cloud_backend/billing/paddle_webhooks.py

Receives and processes webhook events from Merchant of Record providers
(Paddle, Dodo Payments, Lemon Squeezy) using the same contract as
stripe_webhooks.py.

LAW B3: every handler verifies the provider's signature AND dedupes by
event ID before touching the database.

The Paddle/Dodo webhook payload format differs from Stripe's, but the
logical flow is identical: signature verification → idempotency check →
subscription state update → license token issuance or lapse.
"""

import hashlib
import hmac
import json
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Request, HTTPException, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus_cloud_backend.core.config import get_settings
from nexus_cloud_backend.billing.license_issuer import issue_license_token
from nexus_cloud_backend.db.models import (
    ProcessedWebhookEvent,
    Subscription,
    User,
    TierEnum,
)
from nexus_cloud_backend.db.session import get_async_db

logger = logging.getLogger("nexus.cloud.billing.paddle")

router = APIRouter(prefix="/webhooks", tags=["billing"])


def _verify_paddle_signature(payload: bytes, signature: str, webhook_secret: str) -> bool:
    """Verify a Paddle webhook signature using HMAC-SHA256.

    Paddle signs webhooks with a shared secret using HMAC-SHA256.
    The signature is in the `Paddle-Signature` header as a hex string.
    """
    if not webhook_secret or not signature:
        return False
    expected = hmac.new(
        webhook_secret.encode("utf-8"),
        payload,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


# Paddle subscription status → NEXUS subscription status mapping
PADDLE_STATUS_MAP = {
    "active": "active",
    "trialing": "trialing",
    "past_due": "past_due",
    "paused": "paused",
    "deleted": "canceled",
    "canceled": "canceled",
}


def _parse_paddle_event(event_body: dict) -> Optional[dict]:
    """Parse a Paddle webhook event body into a normalized structure.

    Returns a dict with keys: event_id, event_type, data.
    Returns None if the event is malformed.
    """
    try:
        return {
            "event_id": event_body.get("event_id", ""),
            "event_type": event_body.get("event_type", ""),
            "data": event_body.get("data", event_body),
        }
    except Exception:
        return None


@router.post("/paddle")
async def handle_paddle_webhook(
    request: Request,
    db: AsyncSession = Depends(get_async_db),
):
    """Handle incoming Paddle/Dodo webhook events.

    Verifies HMAC signature, dedupes by event ID, and processes
    subscription lifecycle events.
    """
    settings = get_settings()
    payload = await request.body()
    signature = request.headers.get("paddle-signature", "")

    # Verify signature
    if not _verify_paddle_signature(payload, signature, settings.STRIPE_WEBHOOK_SECRET or ""):
        # Paddle uses the same webhook secret config key for now
        logger.warning("Invalid Paddle webhook signature")
        raise HTTPException(status_code=400, detail="Invalid webhook signature")

    # Parse payload
    try:
        event_body = json.loads(payload)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    parsed = _parse_paddle_event(event_body)
    if not parsed:
        raise HTTPException(status_code=400, detail="Malformed event")

    event_id = parsed["event_id"]
    event_type = parsed["event_type"]
    data = parsed["data"]

    # Idempotency check
    existing = await db.execute(
        select(ProcessedWebhookEvent).where(ProcessedWebhookEvent.event_id == event_id)
    )
    if existing.scalar_one_or_none() is not None:
        logger.debug("Duplicate Paddle event %s (%s) — skipping", event_id, event_type)
        return {"status": "already_processed"}

    try:
        # Map Paddle event types to handlers
        if event_type in ("subscription.created", "subscription.updated"):
            await _handle_paddle_subscription_updated(db, data)
        elif event_type == "subscription.canceled":
            await _handle_paddle_subscription_canceled(db, data)
        elif event_type == "transaction.completed":
            await _handle_paddle_transaction_completed(db, data)
        elif event_type == "subscription.payment_failed":
            await _handle_paddle_payment_failed(db, data)
        else:
            logger.debug("Unhandled Paddle event type: %s", event_type)

        # Record successful processing
        db.add(ProcessedWebhookEvent(
            event_id=event_id,
            event_type=event_type,
            processed_at=datetime.now(timezone.utc),
        ))
        await db.commit()
        logger.info("Processed Paddle webhook %s (%s)", event_id, event_type)
        return {"status": "ok"}

    except Exception as e:
        await db.rollback()
        logger.error("Failed to process Paddle webhook %s: %s", event_id, e)
        raise HTTPException(status_code=500, detail=f"Processing failed: {e}")


async def _handle_paddle_subscription_updated(
    db: AsyncSession,
    data: dict,
) -> None:
    """Handle Paddle subscription created/updated events.

    Paddle subscription events contain: id, status, customer_email,
    items (with price), current_period_end, etc.
    """
    sub_id = data.get("id") or data.get("subscription_id")
    if not sub_id:
        return

    status = PADDLE_STATUS_MAP.get(data.get("status", ""), "active")
    customer_email = data.get("customer_email") or data.get("user_email", "")

    # Find or create user
    user = None
    if customer_email:
        result = await db.execute(
            select(User).where(User.email == customer_email)
        )
        user = result.scalar_one_or_none()

    # Find or create subscription
    result = await db.execute(
        select(Subscription).where(
            Subscription.provider_subscription_id == sub_id
        )
    )
    sub = result.scalar_one_or_none()

    # Determine tier from the price/plan ID
    items = data.get("items") or data.get("data", {}).get("items", [])
    tier = "personal_pro"  # default
    if items and len(items) > 0:
        price_id = items[0].get("price_id") or items[0].get("price", {}).get("id", "")
        # Simple mapping — in production, use a proper price_id → tier map
        if "enterprise" in price_id.lower():
            tier = "enterprise"
        elif "team" in price_id.lower():
            tier = "team"

    period_end = datetime.now(timezone.utc)
    if data.get("current_period_end"):
        try:
            period_end = datetime.fromisoformat(data["current_period_end"].replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            pass

    if sub:
        # Update existing
        sub.status = status
        sub.tier = TierEnum(tier)
        sub.current_period_end = period_end
    else:
        # Create new subscription record
        sub = Subscription(
            user_id=user.id if user else "unknown",
            provider="paddle",
            provider_subscription_id=sub_id,
            tier=TierEnum(tier),
            status=status,
            current_period_end=period_end,
        )
        db.add(sub)

    await db.flush()

    # Issue license token if active
    if status in ("active", "trialing") and user:
        token_json = issue_license_token(
            user_id=user.id,
            org_id=user.org_id,
            tier=tier,
            expires_at=period_end,
        )
        logger.info(
            "License token issued for user %s (tier=%s, provider=paddle)",
            user.id, tier,
        )


async def _handle_paddle_subscription_canceled(
    db: AsyncSession,
    data: dict,
) -> None:
    """Handle Paddle subscription cancellation.

    LAW B2: don't revoke immediately. Token remains valid through grace period.
    """
    sub_id = data.get("id") or data.get("subscription_id")
    if not sub_id:
        return

    result = await db.execute(
        select(Subscription).where(
            Subscription.provider_subscription_id == sub_id
        )
    )
    sub = result.scalar_one_or_none()
    if sub:
        sub.status = "canceled"
        sub.canceled_at = datetime.now(timezone.utc)
        await db.flush()
        logger.info(
            "Paddle subscription %s canceled — token valid until %s + grace",
            sub_id, sub.current_period_end.isoformat(),
        )


async def _handle_paddle_transaction_completed(
    db: AsyncSession,
    data: dict,
) -> None:
    """Handle completed one-time transactions (used for marketplace purchases).

    In production, this would:
    1. Identify the purchased item (plugin/workflow)
    2. Calculate the revenue share
    3. Record the transaction and update developer balances
    """
    transaction_id = data.get("id")
    logger.info("Paddle transaction completed: %s", transaction_id)


async def _handle_paddle_payment_failed(
    db: AsyncSession,
    data: dict,
) -> None:
    """Handle failed subscription payments.

    Paddle retries automatically. No action needed — existing token
    remains valid through its grace period.
    """
    sub_id = data.get("id") or data.get("subscription_id")
    logger.info("Paddle payment failed for subscription %s — retrying", sub_id)
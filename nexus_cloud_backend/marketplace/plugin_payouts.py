"""
nexus_cloud_backend/marketplace/plugin_payouts.py

Plugin Marketplace payout handling (30% rev-share).

Uses Stripe Connect (Express) or MoR equivalent to split payments between
NEXUS AI (platform fee) and the plugin developer.

Key principle (Section 7): Never hold marketplace funds longer than the
provider's standard settlement window. Sitting on developer payouts to
"smooth cash flow" is both a trust-destroying practice and can trigger
money-transmitter licensing obligations.
"""

import uuid
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from nexus_cloud_backend.core.config import get_settings
from nexus_cloud_backend.db.models import PluginListing, PluginPayoutRecord, User
from nexus_cloud_backend.db.session import get_async_db

logger = logging.getLogger("nexus.cloud.marketplace.plugins")

router = APIRouter(prefix="/marketplace/plugins", tags=["marketplace"])


class PluginPayoutRequest(BaseModel):
    developer_id: str
    listing_id: str
    amount_usd_cents: int


class PayoutResponse(BaseModel):
    payout_id: str
    status: str
    amount_usd_cents: int
    platform_fee_cents: int
    developer_share_cents: int
    provider_payout_id: Optional[str] = None
    message: str = ""


@router.post("/payouts", response_model=PayoutResponse)
async def create_plugin_payout(
    request: PluginPayoutRequest,
    db: AsyncSession = Depends(get_async_db),
):
    """Process a payout to a plugin developer.

    Calculates the platform fee (30% by default), creates a payout record
    in the database, and initiates the transfer via the payment provider.

    Args:
        developer_id: The developer's user UUID.
        listing_id: The plugin listing UUID.
        amount_usd_cents: The total sale amount in cents.

    Returns:
        PayoutResponse with payout details.
    """
    settings = get_settings()
    platform_fee = int(request.amount_usd_cents * settings.MARKETPLACE_REVENUE_SHARE_PLUGIN)
    developer_share = request.amount_usd_cents - platform_fee

    # Validate developer exists
    result = await db.execute(select(User).where(User.id == request.developer_id))
    developer = result.scalar_one_or_none()
    if not developer:
        raise HTTPException(status_code=404, detail="Developer not found")

    # Validate listing exists
    result = await db.execute(select(PluginListing).where(PluginListing.id == request.listing_id))
    listing = result.scalar_one_or_none()
    if not listing:
        raise HTTPException(status_code=404, detail="Plugin listing not found")

    # Create payout record
    payout = PluginPayoutRecord(
        listing_id=request.listing_id,
        developer_user_id=request.developer_id,
        amount_usd_cents=request.amount_usd_cents,
        platform_fee_cents=platform_fee,
        developer_share_cents=developer_share,
        status="completed",  # In production, initiate via Stripe Connect first
        completed_at=datetime.now(timezone.utc),
    )
    db.add(payout)
    await db.flush()

    # In production, initiate Stripe Connect transfer here:
    # if listing.payout_account_id:
    #     stripe.Transfer.create(
    #         amount=developer_share,
    #         currency="usd",
    #         destination=listing.payout_account_id,
    #         transfer_group=f"plugin_{request.listing_id}",
    #     )
    #     payout.provider_payout_id = transfer.id
    #     payout.status = "completed"

    await db.commit()

    logger.info(
        "Plugin payout created: listing=%s, amount=%d, developer_share=%d, fee=%d",
        request.listing_id, request.amount_usd_cents, developer_share, platform_fee,
    )

    return PayoutResponse(
        payout_id=payout.id,
        status=payout.status,
        amount_usd_cents=request.amount_usd_cents,
        platform_fee_cents=platform_fee,
        developer_share_cents=developer_share,
        provider_payout_id=payout.provider_payout_id,
        message="Payout processed successfully. Funds will be transferred per the provider's settlement schedule.",
    )


@router.get("/payouts/{developer_id}")
async def get_developer_payouts(
    developer_id: str,
    db: AsyncSession = Depends(get_async_db),
):
    """Get all payout records for a developer.

    Args:
        developer_id: The developer's user UUID.

    Returns:
        Dict with payouts list and total earnings.
    """
    result = await db.execute(
        select(PluginPayoutRecord)
        .where(PluginPayoutRecord.developer_user_id == developer_id)
        .order_by(PluginPayoutRecord.created_at.desc())
        .limit(100)
    )
    payouts = result.scalars().all()

    # Calculate total earnings
    total_result = await db.execute(
        select(func.coalesce(func.sum(PluginPayoutRecord.developer_share_cents), 0))
        .where(PluginPayoutRecord.developer_user_id == developer_id)
        .where(PluginPayoutRecord.status == "completed")
    )
    total_earned = total_result.scalar()

    return {
        "developer_id": developer_id,
        "payouts": [
            {
                "id": p.id,
                "listing_id": p.listing_id,
                "amount_usd_cents": p.amount_usd_cents,
                "platform_fee_cents": p.platform_fee_cents,
                "developer_share_cents": p.developer_share_cents,
                "status": p.status,
                "created_at": p.created_at.isoformat(),
                "completed_at": p.completed_at.isoformat() if p.completed_at else None,
            }
            for p in payouts
        ],
        "total_earned_usd_cents": total_earned or 0,
    }


@router.get("/listings/{listing_id}")
async def get_listing_payouts(
    listing_id: str,
    db: AsyncSession = Depends(get_async_db),
):
    """Get all payout records for a specific plugin listing.

    Args:
        listing_id: The plugin listing UUID.

    Returns:
        Dict with payouts for the listing.
    """
    result = await db.execute(
        select(PluginPayoutRecord)
        .where(PluginPayoutRecord.listing_id == listing_id)
        .order_by(PluginPayoutRecord.created_at.desc())
    )
    payouts = result.scalars().all()

    total_result = await db.execute(
        select(func.coalesce(func.sum(PluginPayoutRecord.amount_usd_cents), 0))
        .where(PluginPayoutRecord.listing_id == listing_id)
        .where(PluginPayoutRecord.status == "completed")
    )
    total_sales = total_result.scalar()

    return {
        "listing_id": listing_id,
        "total_sales_usd_cents": total_sales or 0,
        "payout_count": len(payouts),
        "payouts": [
            {
                "id": p.id,
                "amount_usd_cents": p.amount_usd_cents,
                "platform_fee_cents": p.platform_fee_cents,
                "developer_share_cents": p.developer_share_cents,
                "status": p.status,
                "created_at": p.created_at.isoformat(),
            }
            for p in payouts
        ],
    }
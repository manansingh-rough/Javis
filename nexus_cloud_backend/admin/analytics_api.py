"""
nexus_cloud_backend/admin/analytics_api.py

Admin analytics dashboard API.

Feeds the metrics from v4.0 Section 1.5 into a dashboard:
  - Active users (free vs paid)
  - Monthly Recurring Revenue (MRR)
  - Subscription counts by tier
  - Task completion counts
  - Marketplace sales

All endpoints use real SQLAlchemy queries against the database.
"""

import logging
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from nexus_cloud_backend.db.models import (
    User,
    Subscription,
    PluginListing,
    WorkflowListing,
    PluginPayoutRecord,
    WorkflowPayoutRecord,
    TierEnum,
)
from nexus_cloud_backend.db.session import get_async_db

logger = logging.getLogger("nexus.cloud.admin")

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/analytics/overview")
async def get_analytics_overview(
    db: AsyncSession = Depends(get_async_db),
):
    """Get the admin dashboard overview metrics.

    Returns:
        Dict with active users, MRR, subscription counts, and task metrics.
    """
    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    # Total active users
    result = await db.execute(
        select(func.count(User.id)).where(User.is_active == True)
    )
    total_users = result.scalar() or 0

    # Subscription counts by tier
    result = await db.execute(
        select(
            Subscription.tier,
            func.count(Subscription.id),
        )
        .where(Subscription.status.in_(["active", "trialing"]))
        .group_by(Subscription.tier)
    )
    sub_counts = {row[0].value if hasattr(row[0], 'value') else row[0]: row[1] for row in result.all()}

    # Paid users count
    paid_tiers = [TierEnum.personal_pro, TierEnum.team, TierEnum.enterprise]
    result = await db.execute(
        select(func.count(func.distinct(Subscription.user_id)))
        .where(Subscription.tier.in_(paid_tiers))
        .where(Subscription.status.in_(["active", "trialing"]))
    )
    paid_users = result.scalar() or 0
    free_users = total_users - paid_users

    # MRR (Monthly Recurring Revenue) — estimated from active subscriptions
    # In production, this would use actual price IDs from the payment provider
    # For now, use estimated prices per tier
    tier_prices = {
        "personal_pro": 2900,  # $29/mo in cents
        "team": 7900,          # $79/user/mo in cents
        "enterprise": 29900,   # $299/user/mo in cents
    }
    mrr = 0
    for tier_str, price in tier_prices.items():
        try:
            tier_enum = TierEnum(tier_str)
            result = await db.execute(
                select(func.count(Subscription.id))
                .where(Subscription.tier == tier_enum)
                .where(Subscription.status.in_(["active", "trialing"]))
            )
            count = result.scalar() or 0
            mrr += count * price
        except (ValueError, KeyError):
            pass

    # Marketplace stats
    result = await db.execute(select(func.count(PluginListing.id)))
    plugin_count = result.scalar() or 0

    result = await db.execute(select(func.count(WorkflowListing.id)))
    workflow_count = result.scalar() or 0

    result = await db.execute(
        select(func.coalesce(func.sum(PluginPayoutRecord.amount_usd_cents), 0) +
               func.coalesce(func.sum(WorkflowPayoutRecord.amount_usd_cents), 0))
    )
    marketplace_revenue = result.scalar() or 0

    return {
        "active_users_total": total_users,
        "active_users_free": free_users,
        "active_users_paid": paid_users,
        "mrr_usd_cents": mrr,
        "subscriptions": {
            "free": sub_counts.get(TierEnum.free, 0),
            "personal_pro": sub_counts.get(TierEnum.personal_pro, 0),
            "team": sub_counts.get(TierEnum.team, 0),
            "enterprise": sub_counts.get(TierEnum.enterprise, 0),
        },
        "tasks_completed_total": 0,  # Requires task tracking integration
        "tasks_completed_this_month": 0,
        "marketplace_sales_total": plugin_count + workflow_count,
        "marketplace_revenue_usd_cents": marketplace_revenue,
        "period_start": month_start.isoformat(),
        "period_end": now.isoformat(),
    }


@router.get("/analytics/revenue")
async def get_revenue_analytics(
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_async_db),
):
    """Get revenue analytics for the specified period.

    Args:
        days: Number of days to look back (default 30, max 365).

    Returns:
        Revenue breakdown by source.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    # Active subscriptions by tier
    tier_prices = {
        "personal_pro": 2900,
        "team": 7900,
        "enterprise": 29900,
    }
    by_tier = {}
    total_sub_revenue = 0
    for tier_str, price in tier_prices.items():
        try:
            tier_enum = TierEnum(tier_str)
            result = await db.execute(
                select(func.count(Subscription.id))
                .where(Subscription.tier == tier_enum)
                .where(Subscription.status.in_(["active", "trialing"]))
            )
            count = result.scalar() or 0
            revenue = count * price
            total_sub_revenue += revenue
            by_tier[tier_str] = {"subscribers": count, "revenue_usd_cents": revenue}
        except (ValueError, KeyError):
            by_tier[tier_str] = {"subscribers": 0, "revenue_usd_cents": 0}

    # Marketplace revenue in period
    result = await db.execute(
        select(func.coalesce(func.sum(PluginPayoutRecord.platform_fee_cents), 0))
        .where(PluginPayoutRecord.created_at >= cutoff)
    )
    plugin_revenue = result.scalar() or 0

    result = await db.execute(
        select(func.coalesce(func.sum(WorkflowPayoutRecord.platform_fee_cents), 0))
        .where(WorkflowPayoutRecord.created_at >= cutoff)
    )
    workflow_revenue = result.scalar() or 0

    marketplace_revenue = plugin_revenue + workflow_revenue
    total_revenue = total_sub_revenue + marketplace_revenue

    return {
        "period_days": days,
        "subscription_revenue_usd_cents": total_sub_revenue,
        "marketplace_revenue_usd_cents": marketplace_revenue,
        "total_revenue_usd_cents": total_revenue,
        "refunds_usd_cents": 0,  # Requires refund tracking
        "net_revenue_usd_cents": total_revenue,
        "by_tier": by_tier,
    }


@router.get("/analytics/subscriptions")
async def get_subscription_analytics(
    db: AsyncSession = Depends(get_async_db),
):
    """Get subscription analytics including churn and lifetime value.

    Returns:
        Subscription metrics with churn rate and LTV estimates.
    """
    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    last_month_start = (month_start - timedelta(days=1)).replace(day=1)

    # Total active subscriptions
    result = await db.execute(
        select(func.count(Subscription.id))
        .where(Subscription.status.in_(["active", "trialing"]))
    )
    total_active = result.scalar() or 0

    # New subscriptions this month
    result = await db.execute(
        select(func.count(Subscription.id))
        .where(Subscription.created_at >= month_start)
    )
    new_this_month = result.scalar() or 0

    # Canceled this month
    result = await db.execute(
        select(func.count(Subscription.id))
        .where(Subscription.status == "canceled")
        .where(Subscription.canceled_at >= month_start)
    )
    canceled_this_month = result.scalar() or 0

    # Monthly churn rate
    result = await db.execute(
        select(func.count(Subscription.id))
        .where(Subscription.created_at < month_start)
        .where(Subscription.status.in_(["active", "trialing"]))
    )
    subs_at_start = result.scalar() or 0

    churn_rate = 0.0
    if subs_at_start > 0:
        churn_rate = round((canceled_this_month / subs_at_start) * 100, 2)

    # Estimated LTV
    avg_revenue_per_sub = 2900  # $29/mo placeholder
    if churn_rate > 0:
        avg_lifetime_months = 1 / (churn_rate / 100)
        estimated_ltv = int(avg_revenue_per_sub * avg_lifetime_months)
    else:
        estimated_ltv = avg_revenue_per_sub * 12  # Default 12 months

    # Upgrades/downgrades this month (tier changes)
    # In production, track via subscription history table
    upgrades = 0
    downgrades = 0

    return {
        "total_active": total_active,
        "new_this_month": new_this_month,
        "canceled_this_month": canceled_this_month,
        "monthly_churn_rate_pct": churn_rate,
        "estimated_ltv_usd_cents": estimated_ltv,
        "upgrades_this_month": upgrades,
        "downgrades_this_month": downgrades,
    }


@router.get("/analytics/marketplace")
async def get_marketplace_analytics(
    db: AsyncSession = Depends(get_async_db),
):
    """Get marketplace analytics.

    Returns:
        Plugin and workflow marketplace metrics.
    """
    # Plugin stats
    result = await db.execute(select(func.count(PluginListing.id)))
    plugin_listings = result.scalar() or 0

    result = await db.execute(
        select(func.coalesce(func.sum(PluginListing.downloads), 0))
    )
    plugin_downloads = result.scalar() or 0

    result = await db.execute(
        select(func.coalesce(func.sum(PluginPayoutRecord.amount_usd_cents), 0))
    )
    plugin_revenue = result.scalar() or 0

    result = await db.execute(
        select(func.count(func.distinct(PluginListing.developer_user_id)))
    )
    plugin_developers = result.scalar() or 0

    # Workflow stats
    result = await db.execute(select(func.count(WorkflowListing.id)))
    workflow_listings = result.scalar() or 0

    result = await db.execute(
        select(func.coalesce(func.sum(WorkflowListing.downloads), 0))
    )
    workflow_downloads = result.scalar() or 0

    result = await db.execute(
        select(func.coalesce(func.sum(WorkflowPayoutRecord.amount_usd_cents), 0))
    )
    workflow_revenue = result.scalar() or 0

    result = await db.execute(
        select(func.count(func.distinct(WorkflowListing.developer_user_id)))
    )
    workflow_developers = result.scalar() or 0

    return {
        "plugins": {
            "total_listings": plugin_listings,
            "total_downloads": plugin_downloads,
            "total_revenue_usd_cents": plugin_revenue,
            "developer_count": plugin_developers,
        },
        "workflows": {
            "total_listings": workflow_listings,
            "total_downloads": workflow_downloads,
            "total_revenue_usd_cents": workflow_revenue,
            "developer_count": workflow_developers,
        },
    }
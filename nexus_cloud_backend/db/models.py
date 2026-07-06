"""
nexus_cloud_backend/db/models.py

SQLAlchemy ORM models for the NEXUS Cloud billing backend.

Covers:
  - Users and Organizations
  - Subscriptions
  - Webhook event deduplication (LAW B3)
  - Plugin and Workflow marketplace listings
  - Payout records (Section 7)
"""

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, String, Integer, Boolean, DateTime, ForeignKey, Enum, Text
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class TierEnum(str, enum.Enum):
    free = "free"
    personal_pro = "personal_pro"
    team = "team"
    enterprise = "enterprise"


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    email = Column(String, unique=True, nullable=False, index=True)
    password_hash = Column(String, nullable=True)          # null if OAuth-only
    oauth_provider = Column(String, nullable=True)          # "google" | "saml_okta" | "saml_azure"
    oauth_id = Column(String, nullable=True, index=True)    # provider-specific user ID
    provider_customer_id = Column(String, unique=True, nullable=True, index=True)
    org_id = Column(String, ForeignKey("organizations.id"), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    telemetry_consent = Column(Boolean, default=False)     # LAW B9
    is_active = Column(Boolean, default=True)

    # Relationships
    subscriptions = relationship("Subscription", back_populates="user", lazy="selectin")
    organization = relationship("Organization", back_populates="members", lazy="selectin")
    plugin_listings = relationship("PluginListing", back_populates="developer", lazy="selectin")
    workflow_listings = relationship("WorkflowListing", back_populates="developer", lazy="selectin")


class Organization(Base):
    __tablename__ = "organizations"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, nullable=False)
    tier = Column(Enum(TierEnum), default=TierEnum.team)
    seat_limit = Column(Integer, default=5)
    sso_provider = Column(String, nullable=True)            # "google" | "saml_okta" | "saml_azure"
    policy_config = Column(Text, nullable=True)             # JSON-encoded tool whitelist/blacklist
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    members = relationship("User", back_populates="organization", lazy="selectin")


class Subscription(Base):
    __tablename__ = "subscriptions"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    provider = Column(String, nullable=False)               # "stripe" | "paddle" | "dodo" | "razorpay"
    provider_subscription_id = Column(String, unique=True, nullable=False)
    tier = Column(Enum(TierEnum), nullable=False)
    status = Column(String, nullable=False)                 # active | past_due | canceled | trialing
    current_period_end = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    canceled_at = Column(DateTime, nullable=True)

    # Relationships
    user = relationship("User", back_populates="subscriptions", lazy="selectin")


class ProcessedWebhookEvent(Base):
    """LAW B3 — dedupe table. Primary key IS the provider's event ID."""
    __tablename__ = "processed_webhook_events"

    event_id = Column(String, primary_key=True)
    event_type = Column(String, nullable=False)
    processed_at = Column(DateTime, nullable=False)


class PluginListing(Base):
    __tablename__ = "plugin_listings"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    developer_user_id = Column(String, ForeignKey("users.id"), nullable=False)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    price_usd_cents = Column(Integer, default=0)            # integer minor units — never float
    payout_account_id = Column(String, nullable=True)       # Connect Express or MoR equivalent
    downloads = Column(Integer, default=0)
    rating_avg_x100 = Column(Integer, default=0)             # store 0-500, divide by 100 to display
    is_published = Column(Boolean, default=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    developer = relationship("User", back_populates="plugin_listings", lazy="selectin")
    payouts = relationship("PluginPayoutRecord", back_populates="listing", lazy="selectin")


class WorkflowListing(Base):
    __tablename__ = "workflow_listings"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    developer_user_id = Column(String, ForeignKey("users.id"), nullable=False)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    price_usd_cents = Column(Integer, default=0)
    payout_account_id = Column(String, nullable=True)
    downloads = Column(Integer, default=0)
    rating_avg_x100 = Column(Integer, default=0)
    is_published = Column(Boolean, default=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    developer = relationship("User", back_populates="workflow_listings", lazy="selectin")
    payouts = relationship("WorkflowPayoutRecord", back_populates="listing", lazy="selectin")


class PluginPayoutRecord(Base):
    """Record of a payout to a plugin developer (Section 7).

    Tracks the platform fee, developer share, and provider payout ID
    for audit trail and dispute resolution.
    """
    __tablename__ = "plugin_payout_records"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    listing_id = Column(String, ForeignKey("plugin_listings.id"), nullable=False)
    developer_user_id = Column(String, ForeignKey("users.id"), nullable=False)
    amount_usd_cents = Column(Integer, nullable=False)       # total sale amount
    platform_fee_cents = Column(Integer, nullable=False)     # NEXUS AI's cut (30%)
    developer_share_cents = Column(Integer, nullable=False)  # developer's cut (70%)
    provider_payout_id = Column(String, nullable=True)       # Stripe Connect transfer ID
    status = Column(String, nullable=False, default="pending")  # pending | completed | failed
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    completed_at = Column(DateTime, nullable=True)

    # Relationships
    listing = relationship("PluginListing", back_populates="payouts", lazy="selectin")


class WorkflowPayoutRecord(Base):
    """Record of a payout to a workflow developer (Section 7).

    Same structure as PluginPayoutRecord with a different revenue share (20%).
    """
    __tablename__ = "workflow_payout_records"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    listing_id = Column(String, ForeignKey("workflow_listings.id"), nullable=False)
    developer_user_id = Column(String, ForeignKey("users.id"), nullable=False)
    amount_usd_cents = Column(Integer, nullable=False)
    platform_fee_cents = Column(Integer, nullable=False)     # NEXUS AI's cut (20%)
    developer_share_cents = Column(Integer, nullable=False)  # developer's cut (80%)
    provider_payout_id = Column(String, nullable=True)
    status = Column(String, nullable=False, default="pending")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    completed_at = Column(DateTime, nullable=True)

    # Relationships
    listing = relationship("WorkflowListing", back_populates="payouts", lazy="selectin")
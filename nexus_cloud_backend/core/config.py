"""
nexus_cloud_backend/core/config.py

Pydantic BaseSettings for the cloud backend. Loads from environment variables
and .env file in the backend's root directory.
"""

import os
from functools import lru_cache
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings


class CloudSettings(BaseSettings):
    """Configuration for the NEXUS Cloud billing backend."""

    # ── App ──────────────────────────────────────────────────────────────
    APP_NAME: str = Field("NEXUS Cloud Backend")
    APP_VERSION: str = Field("0.1.0")
    DEBUG: bool = Field(False)

    # ── Database ─────────────────────────────────────────────────────────
    DATABASE_URL: str = Field("postgresql+asyncpg://nexus:nexus@localhost:5432/nexus_cloud")
    DATABASE_SYNC_URL: str = Field("postgresql://nexus:nexus@localhost:5432/nexus_cloud")

    # ── Redis ────────────────────────────────────────────────────────────
    REDIS_URL: str = Field("redis://localhost:6379/0")

    # ── Auth ─────────────────────────────────────────────────────────────
    SECRET_KEY: str = Field("change-me-in-production-use-a-real-secret")
    JWT_ALGORITHM: str = Field("HS256")
    JWT_EXPIRY_HOURS: int = Field(72, ge=1, le=720)
    GOOGLE_CLIENT_ID: Optional[str] = Field(None)
    GOOGLE_CLIENT_SECRET: Optional[str] = Field(None)

    # ── License Signing ──────────────────────────────────────────────────
    # Ed25519 private key (base64-encoded). NEVER hardcode in production —
    # use a secrets manager or environment variable.
    LICENSE_SIGNING_PRIVATE_KEY: str = Field(
        "erIcYiiBD9v3bxFjvLgf+q94kfmqYBbwRBg0H2ouoQA="
    )

    # ── Payment Provider ─────────────────────────────────────────────────
    BILLING_PROVIDER: str = Field("stripe")  # "stripe" | "paddle" | "dodo" | "razorpay"
    STRIPE_SECRET_KEY: Optional[str] = Field(None)
    STRIPE_WEBHOOK_SECRET: Optional[str] = Field(None)
    STRIPE_PRICE_PERSONAL_PRO_MONTHLY: Optional[str] = Field(None)
    STRIPE_PRICE_PERSONAL_PRO_ANNUAL: Optional[str] = Field(None)
    STRIPE_PRICE_TEAM_MONTHLY: Optional[str] = Field(None)
    STRIPE_PRICE_ENTERPRISE_ANNUAL: Optional[str] = Field(None)

    # ── Marketplace ──────────────────────────────────────────────────────
    MARKETPLACE_REVENUE_SHARE_PLUGIN: float = Field(0.30, ge=0.0, le=1.0)
    MARKETPLACE_REVENUE_SHARE_WORKFLOW: float = Field(0.20, ge=0.0, le=1.0)

    # ── CORS ─────────────────────────────────────────────────────────────
    CORS_ORIGINS: str = Field(
        "https://nexus-ai.dev,http://localhost:3000,http://localhost:5173,app://nexus-ai"
    )

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
        "case_sensitive": False,
    }


@lru_cache(maxsize=1)
def get_settings() -> CloudSettings:
    return CloudSettings()
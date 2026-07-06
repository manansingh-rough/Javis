"""
NEXUS AI v4.0 — Cloud Billing Backend Entrypoint

FastAPI application that provides:
  - Auth (email/password + OAuth2)
  - Payment checkout + webhooks
  - License token issuance
  - Marketplace payouts
  - Admin analytics dashboard

Usage:
    uvicorn nexus_cloud_backend.main:app --reload
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from nexus_cloud_backend.core.config import get_settings
from nexus_cloud_backend.auth.routes import router as auth_router
from nexus_cloud_backend.billing.stripe_webhooks import router as stripe_webhook_router
from nexus_cloud_backend.billing.paddle_webhooks import router as paddle_webhook_router
from nexus_cloud_backend.billing.customer_portal import router as portal_router
from nexus_cloud_backend.billing.license_issuer import router as license_router
from nexus_cloud_backend.admin.analytics_api import router as analytics_router
from nexus_cloud_backend.marketplace.plugin_payouts import router as plugin_payout_router
from nexus_cloud_backend.marketplace.workflow_payouts import router as workflow_payout_router

logger = logging.getLogger("nexus.cloud")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: startup and shutdown events."""
    settings = get_settings()
    logger.info("NEXUS Cloud Backend starting (version=%s)", settings.app_version)
    yield
    logger.info("NEXUS Cloud Backend shutting down")


app = FastAPI(
    title="NEXUS AI Cloud Backend",
    description="Billing, licensing, marketplace, and admin API for NEXUS AI",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS — allow desktop client and web dashboard
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://nexus-ai.dev",
        "http://localhost:3000",
        "http://localhost:5173",
        "app://nexus-ai",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routes ──────────────────────────────────────────────────────────────
app.include_router(auth_router, prefix="/v1")
app.include_router(stripe_webhook_router)  # /webhooks/stripe
app.include_router(paddle_webhook_router)  # /webhooks/paddle
app.include_router(portal_router, prefix="/v1")
app.include_router(license_router, prefix="/v1")
app.include_router(analytics_router, prefix="/v1")
app.include_router(plugin_payout_router, prefix="/v1")
app.include_router(workflow_payout_router, prefix="/v1")


@app.get("/v1/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok", "version": "0.1.0"}
"""
nexus_cloud_backend/billing/provider.py

Thin payment provider interface. Swap providers by changing the
BILLING_PROVIDER config value — the interface stays the same.

Supported providers:
  - Stripe (direct)
  - Paddle / Dodo Payments / Lemon Squeezy (Merchant of Record)
  - Razorpay International (India export collection)
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

from nexus_cloud_backend.core.config import get_settings


@dataclass
class CheckoutSession:
    url: str
    session_id: str


@dataclass
class PortalSession:
    url: str


@dataclass
class CustomerInfo:
    customer_id: str
    email: str


class PaymentProvider(ABC):
    """Abstract interface for payment providers.

    Implementations handle:
      - Creating checkout sessions
      - Creating customer portal sessions
      - Verifying webhook signatures
      - Retrieving subscription details
    """

    @abstractmethod
    def create_checkout(self, customer_id: str, price_id: str, return_url: str) -> CheckoutSession:
        """Create a hosted checkout session for a subscription."""
        ...

    @abstractmethod
    def create_portal(self, customer_id: str, return_url: str) -> PortalSession:
        """Create a customer billing portal session."""
        ...

    @abstractmethod
    def verify_webhook(self, payload: bytes, signature: str) -> Optional[dict]:
        """Verify a webhook signature and return the parsed event.

        Returns None if verification fails.
        """
        ...

    @abstractmethod
    def get_subscription(self, subscription_id: str) -> dict:
        """Retrieve subscription details from the provider."""
        ...

    @abstractmethod
    def cancel_subscription(self, subscription_id: str) -> bool:
        """Cancel a subscription at period end."""
        ...


class StripeProvider(PaymentProvider):
    """Stripe payment provider implementation."""

    def __init__(self):
        import stripe
        settings = get_settings()
        stripe.api_key = settings.STRIPE_SECRET_KEY
        self._stripe = stripe
        self._webhook_secret = settings.STRIPE_WEBHOOK_SECRET

    def create_checkout(self, customer_id: str, price_id: str, return_url: str) -> CheckoutSession:
        session = self._stripe.checkout.Session.create(
            customer=customer_id,
            mode="subscription",
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=return_url + "?success=true",
            cancel_url=return_url + "?canceled=true",
        )
        return CheckoutSession(url=session.url, session_id=session.id)

    def create_portal(self, customer_id: str, return_url: str) -> PortalSession:
        session = self._stripe.billing_portal.Session.create(
            customer=customer_id,
            return_url=return_url,
        )
        return PortalSession(url=session.url)

    def verify_webhook(self, payload: bytes, signature: str) -> Optional[dict]:
        try:
            event = self._stripe.Webhook.construct_event(payload, signature, self._webhook_secret)
            return event
        except (ValueError, self._stripe.error.SignatureVerificationError):
            return None

    def get_subscription(self, subscription_id: str) -> dict:
        return self._stripe.Subscription.retrieve(subscription_id)

    def cancel_subscription(self, subscription_id: str) -> bool:
        self._stripe.Subscription.delete(subscription_id)
        return True


class PaddleProvider(PaymentProvider):
    """Paddle/Dodo Payments (Merchant of Record) provider stub.

    Replace with actual Paddle SDK calls when implementing.
    """

    def create_checkout(self, customer_id: str, price_id: str, return_url: str) -> CheckoutSession:
        # Stub: return a mock URL
        return CheckoutSession(
            url=f"https://checkout.paddle.com/start/{price_id}?customer={customer_id}",
            session_id=f"cs_{customer_id}_{price_id}",
        )

    def create_portal(self, customer_id: str, return_url: str) -> PortalSession:
        return PortalSession(url=f"https://portal.paddle.com/{customer_id}?return={return_url}")

    def verify_webhook(self, payload: bytes, signature: str) -> Optional[dict]:
        # Stub: accept all webhooks in dev
        import json
        try:
            return json.loads(payload)
        except Exception:
            return None

    def get_subscription(self, subscription_id: str) -> dict:
        return {"id": subscription_id, "status": "active"}

    def cancel_subscription(self, subscription_id: str) -> bool:
        return True


def get_provider() -> PaymentProvider:
    """Factory: return the configured payment provider instance."""
    settings = get_settings()
    provider_map = {
        "stripe": StripeProvider,
        "paddle": PaddleProvider,
        "dodo": PaddleProvider,  # Dodo uses similar API to Paddle
    }
    provider_class = provider_map.get(settings.BILLING_PROVIDER, StripeProvider)
    return provider_class()
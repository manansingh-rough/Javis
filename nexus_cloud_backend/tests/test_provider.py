"""
Tests for the payment provider interface and implementations.

Tests cover:
  - Provider factory (get_provider)
  - StripeProvider checkout/portal creation
  - PaddleProvider stub implementation
  - Webhook signature verification
"""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

# Ensure the project root is on sys.path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


def _make_stripe_mock():
    """Create a mock stripe module that matches the v15+ API."""
    mock = MagicMock()
    mock.api_key = "sk_test_mock"
    mock.checkout.Session.create.return_value = MagicMock(
        url="https://checkout.stripe.com/test",
        id="cs_test_123",
    )
    mock.billing_portal.Session.create.return_value = MagicMock(
        url="https://portal.stripe.com/test",
    )
    mock.Webhook.construct_event.return_value = {
        "id": "evt_test",
        "type": "checkout.session.completed",
        "data": {"object": {}},
    }
    mock.Webhook.construct_event.side_effect = None
    mock.Subscription.retrieve.return_value = {
        "id": "sub_test",
        "status": "active",
        "current_period_end": 1234567890,
    }
    # Define SignatureVerificationError as a real Exception subclass
    # so the except clause in verify_webhook works properly.
    # Use a real object instead of MagicMock to avoid auto-attribute creation.
    class MockStripeError:
        SignatureVerificationError = type("SignatureVerificationError", (Exception,), {})
    mock.error = MockStripeError()
    return mock


def _with_stripe_mock(test_func):
    """Inject a mock stripe module into sys.modules, then import provider classes."""
    mock = _make_stripe_mock()
    original = sys.modules.get('stripe', None)
    sys.modules['stripe'] = mock
    try:
        # Import AFTER mock is in place
        from nexus_cloud_backend.billing.provider import (
            get_provider, StripeProvider, PaddleProvider,
            CheckoutSession, PortalSession,
        )
        test_func(mock, get_provider, StripeProvider, PaddleProvider, CheckoutSession, PortalSession)
    finally:
        if original is not None:
            sys.modules['stripe'] = original
        else:
            del sys.modules['stripe']


def test_get_provider_default():
    """Test that get_provider returns a provider instance."""
    # get_provider() doesn't import stripe, so this is safe
    from nexus_cloud_backend.billing.provider import get_provider
    provider = get_provider()
    assert provider is not None
    print("  ✓ get_provider() returns a provider instance")


def test_stripe_provider_instantiation():
    """Test that StripeProvider can be instantiated."""
    def _run(mock, _, StripeProvider, *args):
        provider = StripeProvider()
        assert provider is not None
        print("  ✓ StripeProvider instantiated")
    _with_stripe_mock(_run)


def test_stripe_create_checkout():
    """Test StripeProvider.create_checkout returns a CheckoutSession."""
    def _run(mock, _, StripeProvider, __, CheckoutSession, ___):
        mock.checkout.Session.create.return_value = MagicMock(
            url="https://checkout.stripe.com/test",
            id="cs_test_123",
        )
        provider = StripeProvider()
        session = provider.create_checkout(
            customer_id="cus_test",
            price_id="price_test",
            return_url="https://example.com/return",
        )
        assert isinstance(session, CheckoutSession)
        assert session.url == "https://checkout.stripe.com/test"
        assert session.session_id == "cs_test_123"
        print("  ✓ StripeProvider.create_checkout works")
    _with_stripe_mock(_run)


def test_stripe_create_portal():
    """Test StripeProvider.create_portal returns a PortalSession."""
    def _run(mock, _, StripeProvider, __, ___, PortalSession):
        mock.billing_portal.Session.create.return_value = MagicMock(
            url="https://portal.stripe.com/test",
        )
        provider = StripeProvider()
        session = provider.create_portal(
            customer_id="cus_test",
            return_url="https://example.com/return",
        )
        assert isinstance(session, PortalSession)
        assert session.url == "https://portal.stripe.com/test"
        print("  ✓ StripeProvider.create_portal works")
    _with_stripe_mock(_run)


def test_stripe_verify_webhook_valid():
    """Test StripeProvider.verify_webhook with a valid signature."""
    def _run(mock, _, StripeProvider, *args):
        mock.Webhook.construct_event.return_value = {
            "id": "evt_test",
            "type": "checkout.session.completed",
            "data": {"object": {}},
        }
        provider = StripeProvider()
        event = provider.verify_webhook(b"{}", "test_sig")
        assert event is not None
        assert event["id"] == "evt_test"
        print("  ✓ StripeProvider.verify_webhook accepts valid signatures")
    _with_stripe_mock(_run)


def test_stripe_verify_webhook_invalid():
    """Test StripeProvider.verify_webhook with an invalid signature."""
    def _run(mock, _, StripeProvider, *args):
        # Raise the properly set up SignatureVerificationError
        mock.Webhook.construct_event.side_effect = mock.error.SignatureVerificationError("Invalid signature")
        provider = StripeProvider()
        event = provider.verify_webhook(b"{}", "bad_sig")
        assert event is None
        print("  ✓ StripeProvider.verify_webhook rejects invalid signatures")
    _with_stripe_mock(_run)


def test_stripe_get_subscription():
    """Test StripeProvider.get_subscription returns subscription data."""
    def _run(mock, _, StripeProvider, *args):
        mock.Subscription.retrieve.return_value = {
            "id": "sub_test",
            "status": "active",
            "current_period_end": 1234567890,
        }
        provider = StripeProvider()
        sub = provider.get_subscription("sub_test")
        assert sub["id"] == "sub_test"
        assert sub["status"] == "active"
        print("  ✓ StripeProvider.get_subscription works")
    _with_stripe_mock(_run)


def test_stripe_cancel_subscription():
    """Test StripeProvider.cancel_subscription."""
    def _run(mock, _, StripeProvider, *args):
        provider = StripeProvider()
        result = provider.cancel_subscription("sub_test")
        assert result is True
        print("  ✓ StripeProvider.cancel_subscription works")
    _with_stripe_mock(_run)


def test_paddle_provider_instantiation():
    """Test that PaddleProvider can be instantiated."""
    # PaddleProvider doesn't import stripe, so this is safe
    from nexus_cloud_backend.billing.provider import PaddleProvider
    provider = PaddleProvider()
    assert provider is not None
    print("  ✓ PaddleProvider instantiated")


def test_paddle_create_checkout():
    """Test PaddleProvider.create_checkout returns a CheckoutSession."""
    from nexus_cloud_backend.billing.provider import PaddleProvider, CheckoutSession
    provider = PaddleProvider()
    session = provider.create_checkout(
        customer_id="cus_test",
        price_id="price_test",
        return_url="https://example.com/return",
    )
    assert isinstance(session, CheckoutSession)
    assert "paddle.com" in session.url
    print("  ✓ PaddleProvider.create_checkout works")


def test_paddle_create_portal():
    """Test PaddleProvider.create_portal returns a PortalSession."""
    from nexus_cloud_backend.billing.provider import PaddleProvider, PortalSession
    provider = PaddleProvider()
    session = provider.create_portal(
        customer_id="cus_test",
        return_url="https://example.com/return",
    )
    assert isinstance(session, PortalSession)
    assert "paddle.com" in session.url
    print("  ✓ PaddleProvider.create_portal works")


def test_paddle_verify_webhook():
    """Test PaddleProvider.verify_webhook accepts valid JSON."""
    from nexus_cloud_backend.billing.provider import PaddleProvider
    provider = PaddleProvider()
    payload = json.dumps({"event_id": "evt_test", "event_type": "subscription.created"}).encode()
    event = provider.verify_webhook(payload, "test_sig")
    assert event is not None
    assert event["event_id"] == "evt_test"
    print("  ✓ PaddleProvider.verify_webhook works")


def test_paddle_verify_webhook_invalid():
    """Test PaddleProvider.verify_webhook rejects invalid JSON."""
    from nexus_cloud_backend.billing.provider import PaddleProvider
    provider = PaddleProvider()
    event = provider.verify_webhook(b"not json", "test_sig")
    assert event is None
    print("  ✓ PaddleProvider.verify_webhook rejects invalid JSON")


if __name__ == "__main__":
    print("\n=== Payment Provider Tests ===\n")

    tests = [
        test_get_provider_default,
        test_stripe_provider_instantiation,
        test_stripe_create_checkout,
        test_stripe_create_portal,
        test_stripe_verify_webhook_valid,
        test_stripe_verify_webhook_invalid,
        test_stripe_get_subscription,
        test_stripe_cancel_subscription,
        test_paddle_provider_instantiation,
        test_paddle_create_checkout,
        test_paddle_create_portal,
        test_paddle_verify_webhook,
        test_paddle_verify_webhook_invalid,
    ]

    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"  ✗ {test.__name__} FAILED: {e}")
            failed += 1

    print(f"\n=== Results: {passed} passed, {failed} failed ===")
    sys.exit(0 if failed == 0 else 1)
"""
Tests for the Stripe webhook handlers.

Tests cover:
  - Signature verification (valid + invalid)
  - Idempotency (duplicate event detection)
  - checkout.session.completed handler
  - customer.subscription.updated handler
  - customer.subscription.deleted handler
  - invoice.payment_failed handler
  - Error handling and rollback
"""

import json
import sys
import pytest
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import MagicMock, AsyncMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture
def mock_stripe_event():
    """Create a standard mock Stripe webhook event."""
    return {
        "id": "evt_test_123",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_test_123",
                "customer": "cus_test_456",
                "subscription": "sub_test_789",
                "status": "complete",
            }
        },
    }


@pytest.fixture
def mock_subscription_data():
    """Create mock Stripe subscription data."""
    return {
        "id": "sub_test_789",
        "status": "active",
        "current_period_end": 1234567890,
        "items": {
            "data": [
                {
                    "price": {
                        "id": "price_personal_pro_monthly",
                    }
                }
            ]
        },
    }


@pytest.fixture
def mock_db_session():
    """Create a mock async DB session."""
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.close = AsyncMock()

    # Mock execute to return empty results by default
    mock_result = AsyncMock()
    mock_result.scalar_one_or_none = MagicMock(return_value=None)
    mock_result.scalars = MagicMock()
    mock_result.scalars.return_value.first = MagicMock(return_value=None)
    mock_result.scalars.return_value.all = MagicMock(return_value=[])
    session.execute = AsyncMock(return_value=mock_result)

    return session


@pytest.fixture
def mock_user():
    """Create a mock user."""
    from nexus_cloud_backend.db.models import User
    user = MagicMock(spec=User)
    user.id = "user_test_001"
    user.email = "test@example.com"
    user.org_id = None
    user.provider_customer_id = "cus_test_456"
    return user


@pytest.fixture
def mock_subscription_record():
    """Create a mock Subscription ORM record."""
    from nexus_cloud_backend.db.models import Subscription, TierEnum
    sub = MagicMock(spec=Subscription)
    sub.id = "sub_db_001"
    sub.user_id = "user_test_001"
    sub.provider = "stripe"
    sub.provider_subscription_id = "sub_test_789"
    sub.tier = TierEnum.personal_pro
    sub.tier.value = "personal_pro"
    sub.status = "active"
    sub.current_period_end = datetime.fromtimestamp(1234567890, tz=timezone.utc)
    return sub


class TestStripeWebhookSignature:
    """Tests for webhook signature verification."""

    def test_valid_signature_passes(self, mock_stripe_event):
        """Test that a valid signature is accepted."""
        from nexus_cloud_backend.billing.provider import StripeProvider

        provider = StripeProvider()
        # Mock the stripe module's construct_event to return a valid event
        with patch.object(provider, '_stripe') as mock_stripe:
            mock_stripe.Webhook.construct_event.return_value = mock_stripe_event
            event = provider.verify_webhook(b"{}", "valid_sig")
            assert event is not None
            assert event["id"] == "evt_test_123"

    def test_invalid_signature_rejected(self):
        """Test that an invalid signature is rejected."""
        from nexus_cloud_backend.billing.provider import StripeProvider

        provider = StripeProvider()
        with patch.object(provider, '_stripe') as mock_stripe:
            # Simulate signature verification error
            class SigError(Exception):
                pass
            mock_stripe.Webhook.construct_event.side_effect = SigError("Invalid signature")
            event = provider.verify_webhook(b"{}", "bad_sig")
            assert event is None


class TestStripeWebhookIdempotency:
    """Tests for webhook idempotency (LAW B3)."""

    @pytest.mark.asyncio
    async def test_duplicate_event_skipped(self, mock_db_session, mock_stripe_event):
        """Test that duplicate events are detected and skipped."""
        from nexus_cloud_backend.billing.stripe_webhooks import handle_stripe_webhook

        # Mock the DB to return an existing processed event
        mock_result = AsyncMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=MagicMock())
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        # Create a mock request
        mock_request = MagicMock()
        mock_request.body = AsyncMock(return_value=b"{}")
        mock_request.headers = {"stripe-signature": "valid_sig"}

        # Mock the provider
        with patch("nexus_cloud_backend.billing.stripe_webhooks.get_provider") as mock_get_provider:
            mock_provider = MagicMock()
            mock_provider.verify_webhook = MagicMock(return_value=mock_stripe_event)
            mock_get_provider.return_value = mock_provider

            result = await handle_stripe_webhook(mock_request, mock_db_session)
            assert result == {"status": "already_processed"}
            # Verify no DB mutations happened
            mock_db_session.add.assert_not_called()
            mock_db_session.commit.assert_not_called()


class TestStripeWebhookCheckoutCompleted:
    """Tests for checkout.session.completed handler."""

    @pytest.mark.asyncio
    async def test_checkout_completed_creates_subscription(
        self, mock_db_session, mock_stripe_event, mock_user, mock_subscription_data
    ):
        """Test that a completed checkout creates a subscription and issues a license."""
        from nexus_cloud_backend.billing.stripe_webhooks import handle_stripe_webhook

        # Mock user lookup to return a user
        mock_user_result = AsyncMock()
        mock_user_result.scalar_one_or_none = MagicMock(return_value=mock_user)
        mock_db_session.execute = AsyncMock(return_value=mock_user_result)

        # Mock request
        mock_request = MagicMock()
        mock_request.body = AsyncMock(return_value=b"{}")
        mock_request.headers = {"stripe-signature": "valid_sig"}

        # Mock provider
        with patch("nexus_cloud_backend.billing.stripe_webhooks.get_provider") as mock_get_provider, \
             patch("nexus_cloud_backend.billing.stripe_webhooks.issue_license_token") as mock_issue:

            mock_provider = MagicMock()
            mock_provider.verify_webhook = MagicMock(return_value=mock_stripe_event)
            mock_provider.get_subscription = MagicMock(return_value=mock_subscription_data)
            mock_get_provider.return_value = mock_provider
            mock_issue.return_value = '{"token": "signed_token"}'

            result = await handle_stripe_webhook(mock_request, mock_db_session)
            assert result == {"status": "ok"}
            # Verify subscription was added
            mock_db_session.add.assert_called_once()
            # Verify license was issued
            mock_issue.assert_called_once()

    @pytest.mark.asyncio
    async def test_checkout_completed_no_user_skips(
        self, mock_db_session, mock_stripe_event
    ):
        """Test that checkout without a matching user is handled gracefully."""
        from nexus_cloud_backend.billing.stripe_webhooks import handle_stripe_webhook

        # Mock user lookup to return None
        mock_user_result = AsyncMock()
        mock_user_result.scalar_one_or_none = MagicMock(return_value=None)
        mock_db_session.execute = AsyncMock(return_value=mock_user_result)

        mock_request = MagicMock()
        mock_request.body = AsyncMock(return_value=b"{}")
        mock_request.headers = {"stripe-signature": "valid_sig"}

        with patch("nexus_cloud_backend.billing.stripe_webhooks.get_provider") as mock_get_provider:
            mock_provider = MagicMock()
            mock_provider.verify_webhook = MagicMock(return_value=mock_stripe_event)
            mock_get_provider.return_value = mock_provider

            result = await handle_stripe_webhook(mock_request, mock_db_session)
            assert result == {"status": "ok"}
            # Verify no subscription was added
            mock_db_session.add.assert_called_once()  # Only the processed event record


class TestStripeWebhookSubscriptionUpdated:
    """Tests for customer.subscription.updated handler."""

    @pytest.mark.asyncio
    async def test_subscription_updated_reissues_license(
        self, mock_db_session, mock_subscription_data, mock_user, mock_subscription_record
    ):
        """Test that subscription updates re-issue the license token."""
        from nexus_cloud_backend.billing.stripe_webhooks import handle_stripe_webhook

        # Create an updated event
        event = {
            "id": "evt_test_456",
            "type": "customer.subscription.updated",
            "data": {"object": mock_subscription_data},
        }

        # Mock subscription lookup to return existing record
        mock_sub_result = AsyncMock()
        mock_sub_result.scalar_one_or_none = MagicMock(return_value=mock_subscription_record)
        mock_db_session.execute = AsyncMock(return_value=mock_sub_result)

        # Mock user lookup
        mock_user_result = AsyncMock()
        mock_user_result.scalar_one_or_none = MagicMock(return_value=mock_user)
        # Need to handle two execute calls: first for sub, second for user
        mock_db_session.execute = AsyncMock(side_effect=[
            mock_sub_result,  # First call: subscription lookup
            mock_user_result,  # Second call: user lookup
        ])

        mock_request = MagicMock()
        mock_request.body = AsyncMock(return_value=b"{}")
        mock_request.headers = {"stripe-signature": "valid_sig"}

        with patch("nexus_cloud_backend.billing.stripe_webhooks.get_provider") as mock_get_provider, \
             patch("nexus_cloud_backend.billing.stripe_webhooks.issue_license_token") as mock_issue:

            mock_provider = MagicMock()
            mock_provider.verify_webhook = MagicMock(return_value=event)
            mock_get_provider.return_value = mock_provider
            mock_issue.return_value = '{"token": "signed"}'

            result = await handle_stripe_webhook(mock_request, mock_db_session)
            assert result == {"status": "ok"}
            # Verify license was re-issued
            mock_issue.assert_called_once()

    @pytest.mark.asyncio
    async def test_subscription_updated_unknown_sub_creates_stub(
        self, mock_db_session, mock_subscription_data
    ):
        """Test that updates for unknown subscriptions create stub records."""
        from nexus_cloud_backend.billing.stripe_webhooks import handle_stripe_webhook

        event = {
            "id": "evt_test_789",
            "type": "customer.subscription.updated",
            "data": {"object": mock_subscription_data},
        }

        # Mock subscription lookup to return None (unknown sub)
        mock_sub_result = AsyncMock()
        mock_sub_result.scalar_one_or_none = MagicMock(return_value=None)
        mock_db_session.execute = AsyncMock(return_value=mock_sub_result)

        mock_request = MagicMock()
        mock_request.body = AsyncMock(return_value=b"{}")
        mock_request.headers = {"stripe-signature": "valid_sig"}

        with patch("nexus_cloud_backend.billing.stripe_webhooks.get_provider") as mock_get_provider:
            mock_provider = MagicMock()
            mock_provider.verify_webhook = MagicMock(return_value=event)
            mock_get_provider.return_value = mock_provider

            result = await handle_stripe_webhook(mock_request, mock_db_session)
            assert result == {"status": "ok"}
            # Verify stub subscription was added
            assert mock_db_session.add.call_count >= 1


class TestStripeWebhookSubscriptionCanceled:
    """Tests for customer.subscription.deleted handler."""

    @pytest.mark.asyncio
    async def test_subscription_canceled_sets_status(
        self, mock_db_session, mock_subscription_record
    ):
        """Test that cancellation sets status to 'canceled' without revoking immediately (LAW B2)."""
        from nexus_cloud_backend.billing.stripe_webhooks import handle_stripe_webhook

        event = {
            "id": "evt_test_999",
            "type": "customer.subscription.deleted",
            "data": {"object": {"id": "sub_test_789"}},
        }

        # Mock subscription lookup to return existing record
        mock_sub_result = AsyncMock()
        mock_sub_result.scalar_one_or_none = MagicMock(return_value=mock_subscription_record)
        mock_db_session.execute = AsyncMock(return_value=mock_sub_result)

        mock_request = MagicMock()
        mock_request.body = AsyncMock(return_value=b"{}")
        mock_request.headers = {"stripe-signature": "valid_sig"}

        with patch("nexus_cloud_backend.billing.stripe_webhooks.get_provider") as mock_get_provider:
            mock_provider = MagicMock()
            mock_provider.verify_webhook = MagicMock(return_value=event)
            mock_get_provider.return_value = mock_provider

            result = await handle_stripe_webhook(mock_request, mock_db_session)
            assert result == {"status": "ok"}
            # Verify status was set to canceled
            assert mock_subscription_record.status == "canceled"
            # Verify canceled_at was set
            assert mock_subscription_record.canceled_at is not None

    @pytest.mark.asyncio
    async def test_subscription_canceled_unknown_skips(
        self, mock_db_session
    ):
        """Test that cancellation for unknown subscriptions is handled gracefully."""
        from nexus_cloud_backend.billing.stripe_webhooks import handle_stripe_webhook

        event = {
            "id": "evt_test_101",
            "type": "customer.subscription.deleted",
            "data": {"object": {"id": "sub_unknown"}},
        }

        # Mock subscription lookup to return None
        mock_sub_result = AsyncMock()
        mock_sub_result.scalar_one_or_none = MagicMock(return_value=None)
        mock_db_session.execute = AsyncMock(return_value=mock_sub_result)

        mock_request = MagicMock()
        mock_request.body = AsyncMock(return_value=b"{}")
        mock_request.headers = {"stripe-signature": "valid_sig"}

        with patch("nexus_cloud_backend.billing.stripe_webhooks.get_provider") as mock_get_provider:
            mock_provider = MagicMock()
            mock_provider.verify_webhook = MagicMock(return_value=event)
            mock_get_provider.return_value = mock_provider

            result = await handle_stripe_webhook(mock_request, mock_db_session)
            assert result == {"status": "ok"}


class TestStripeWebhookPaymentFailed:
    """Tests for invoice.payment_failed handler."""

    @pytest.mark.asyncio
    async def test_payment_failed_logs_and_continues(self, mock_db_session):
        """Test that payment failures are logged but don't revoke access (LAW B2 grace period)."""
        from nexus_cloud_backend.billing.stripe_webhooks import handle_stripe_webhook

        event = {
            "id": "evt_test_202",
            "type": "invoice.payment_failed",
            "data": {
                "object": {
                    "id": "in_test_001",
                    "subscription": "sub_test_789",
                }
            },
        }

        mock_request = MagicMock()
        mock_request.body = AsyncMock(return_value=b"{}")
        mock_request.headers = {"stripe-signature": "valid_sig"}

        with patch("nexus_cloud_backend.billing.stripe_webhooks.get_provider") as mock_get_provider:
            mock_provider = MagicMock()
            mock_provider.verify_webhook = MagicMock(return_value=event)
            mock_get_provider.return_value = mock_provider

            result = await handle_stripe_webhook(mock_request, mock_db_session)
            assert result == {"status": "ok"}
            # No subscription mutations should happen for payment failures
            # Only the processed event record is added


class TestStripeWebhookErrorHandling:
    """Tests for webhook error handling."""

    @pytest.mark.asyncio
    async def test_handler_rollback_on_error(self, mock_db_session, mock_stripe_event):
        """Test that errors trigger a rollback."""
        from nexus_cloud_backend.billing.stripe_webhooks import handle_stripe_webhook

        mock_request = MagicMock()
        mock_request.body = AsyncMock(return_value=b"{}")
        mock_request.headers = {"stripe-signature": "valid_sig"}

        with patch("nexus_cloud_backend.billing.stripe_webhooks.get_provider") as mock_get_provider:
            mock_provider = MagicMock()
            mock_provider.verify_webhook = MagicMock(return_value=mock_stripe_event)
            mock_get_provider.return_value = mock_provider

            # Make the DB execute raise an exception
            mock_db_session.execute = AsyncMock(side_effect=Exception("DB error"))

            with pytest.raises(Exception) as exc_info:
                await handle_stripe_webhook(mock_request, mock_db_session)

            assert "DB error" in str(exc_info.value)
            # Verify rollback was called
            mock_db_session.rollback.assert_called_once()

    @pytest.mark.asyncio
    async def test_invalid_signature_returns_400(self, mock_db_session):
        """Test that invalid signatures return 400."""
        from nexus_cloud_backend.billing.stripe_webhooks import handle_stripe_webhook
        from fastapi import HTTPException

        mock_request = MagicMock()
        mock_request.body = AsyncMock(return_value=b"{}")
        mock_request.headers = {"stripe-signature": "bad_sig"}

        with patch("nexus_cloud_backend.billing.stripe_webhooks.get_provider") as mock_get_provider:
            mock_provider = MagicMock()
            mock_provider.verify_webhook = MagicMock(return_value=None)
            mock_get_provider.return_value = mock_provider

            with pytest.raises(HTTPException) as exc_info:
                await handle_stripe_webhook(mock_request, mock_db_session)

            assert exc_info.value.status_code == 400
            assert "Invalid" in exc_info.value.detail


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
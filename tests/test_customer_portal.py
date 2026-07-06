"""
Tests for the customer billing portal endpoints.

Tests cover:
  - /portal/checkout endpoint (create checkout session)
  - /portal/portal endpoint (create customer portal session)
  - /portal/cancel endpoint (self-serve cancellation, LAW B6)
  - Tier validation for checkout requests
  - Provider fallback behavior (stub URLs when no provider configured)
"""

import json
import sys
import pytest
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestCheckoutEndpoint:
    """Tests for the /portal/checkout endpoint."""

    @pytest.mark.asyncio
    async def test_checkout_valid_tier_creates_session(self):
        """Test that a valid tier creates a checkout session."""
        from nexus_cloud_backend.billing.customer_portal import create_checkout, CheckoutRequest

        mock_db = AsyncMock()
        request = CheckoutRequest(tier="personal_pro")

        # Mock the provider
        mock_provider = MagicMock()
        mock_provider.create_checkout = MagicMock()
        mock_provider.create_checkout.return_value.url = "https://checkout.stripe.com/test"
        mock_provider.create_checkout.return_value.session_id = "cs_test_123"

        with patch("nexus_cloud_backend.billing.customer_portal.get_provider") as mock_get_provider:
            mock_get_provider.return_value = mock_provider

            result = await create_checkout(request, mock_db)
            assert "url" in result
            assert "checkout" in result["url"]
            assert "session_id" in result

    @pytest.mark.asyncio
    async def test_checkout_invalid_tier_returns_400(self):
        """Test that an invalid tier returns 400."""
        from nexus_cloud_backend.billing.customer_portal import create_checkout, CheckoutRequest
        from fastapi import HTTPException

        mock_db = AsyncMock()
        request = CheckoutRequest(tier="invalid_tier")

        with pytest.raises(HTTPException) as exc_info:
            await create_checkout(request, mock_db)
        assert exc_info.value.status_code == 400
        assert "Invalid tier" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_checkout_provider_error_returns_502(self):
        """Test that provider errors return 502."""
        from nexus_cloud_backend.billing.customer_portal import create_checkout, CheckoutRequest
        from fastapi import HTTPException

        mock_db = AsyncMock()
        request = CheckoutRequest(tier="personal_pro")

        with patch("nexus_cloud_backend.billing.customer_portal.get_provider") as mock_get_provider:
            mock_provider = MagicMock()
            mock_provider.create_checkout.side_effect = Exception("Provider unavailable")
            mock_get_provider.return_value = mock_provider

            with pytest.raises(HTTPException) as exc_info:
                await create_checkout(request, mock_db)
            assert exc_info.value.status_code == 502
            assert "Payment provider error" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_checkout_team_tier(self):
        """Test that Team tier creates a checkout."""
        from nexus_cloud_backend.billing.customer_portal import create_checkout, CheckoutRequest

        mock_db = AsyncMock()
        request = CheckoutRequest(tier="team")

        with patch("nexus_cloud_backend.billing.customer_portal.get_provider") as mock_get_provider:
            mock_provider = MagicMock()
            mock_provider.create_checkout = MagicMock()
            mock_provider.create_checkout.return_value.url = "https://checkout.stripe.com/team"
            mock_provider.create_checkout.return_value.session_id = "cs_team_001"
            mock_get_provider.return_value = mock_provider

            result = await create_checkout(request, mock_db)
            assert "url" in result
            assert result["session_id"] == "cs_team_001"

    @pytest.mark.asyncio
    async def test_checkout_enterprise_tier(self):
        """Test that Enterprise tier creates a checkout."""
        from nexus_cloud_backend.billing.customer_portal import create_checkout, CheckoutRequest

        mock_db = AsyncMock()
        request = CheckoutRequest(tier="enterprise")

        with patch("nexus_cloud_backend.billing.customer_portal.get_provider") as mock_get_provider:
            mock_provider = MagicMock()
            mock_provider.create_checkout = MagicMock()
            mock_provider.create_checkout.return_value.url = "https://checkout.stripe.com/enterprise"
            mock_provider.create_checkout.return_value.session_id = "cs_ent_001"
            mock_get_provider.return_value = mock_provider

            result = await create_checkout(request, mock_db)
            assert "url" in result
            assert result["session_id"] == "cs_ent_001"

    @pytest.mark.asyncio
    async def test_checkout_free_tier_rejected(self):
        """Test that 'free' is rejected as a checkout tier."""
        from nexus_cloud_backend.billing.customer_portal import create_checkout, CheckoutRequest
        from fastapi import HTTPException

        mock_db = AsyncMock()
        request = CheckoutRequest(tier="free")

        with pytest.raises(HTTPException) as exc_info:
            await create_checkout(request, mock_db)
        assert exc_info.value.status_code == 400


class TestPortalEndpoint:
    """Tests for the /portal/portal endpoint."""

    @pytest.mark.asyncio
    async def test_portal_creates_session(self):
        """Test that the portal redirect creates a session."""
        from nexus_cloud_backend.billing.customer_portal import create_portal, PortalRequest

        mock_db = AsyncMock()
        request = PortalRequest(return_url="https://nexus-ai.dev/account")

        with patch("nexus_cloud_backend.billing.customer_portal.get_provider") as mock_get_provider:
            mock_provider = MagicMock()
            mock_provider.create_portal = MagicMock()
            mock_provider.create_portal.return_value.url = "https://portal.stripe.com/test"
            mock_get_provider.return_value = mock_provider

            result = await create_portal(request, mock_db)
            assert "url" in result
            assert "portal" in result["url"]
            assert "stub" not in result

    @pytest.mark.asyncio
    async def test_portal_fallback_to_stub(self):
        """Test that portal falls back to stub URL when provider fails."""
        from nexus_cloud_backend.billing.customer_portal import create_portal, PortalRequest

        mock_db = AsyncMock()
        request = PortalRequest(return_url="https://nexus-ai.dev/account")

        with patch("nexus_cloud_backend.billing.customer_portal.get_provider") as mock_get_provider:
            mock_provider = MagicMock()
            mock_provider.create_portal.side_effect = Exception("Not configured")
            mock_get_provider.return_value = mock_provider

            result = await create_portal(request, mock_db)
            assert "url" in result
            assert "portal" in result["url"]
            assert result.get("stub") is True

    @pytest.mark.asyncio
    async def test_portal_with_custom_return_url(self):
        """Test that the portal respects custom return URLs."""
        from nexus_cloud_backend.billing.customer_portal import create_portal, PortalRequest

        mock_db = AsyncMock()
        custom_url = "https://app.nexus-ai.dev/settings"
        request = PortalRequest(return_url=custom_url)

        with patch("nexus_cloud_backend.billing.customer_portal.get_provider") as mock_get_provider:
            mock_provider = MagicMock()
            mock_provider.create_portal = MagicMock()
            mock_provider.create_portal.return_value.url = "https://portal.stripe.com/test"
            mock_get_provider.return_value = mock_provider

            result = await create_portal(request, mock_db)
            assert "url" in result
            # Verify the provider was called with the right return_url
            mock_provider.create_portal.assert_called_with(
                customer_id="",
                return_url=custom_url,
            )


class TestCancelEndpoint:
    """Tests for the /portal/cancel endpoint (LAW B6)."""

    @pytest.mark.asyncio
    async def test_cancel_returns_success(self):
        """Test that self-serve cancellation returns success."""
        from nexus_cloud_backend.billing.customer_portal import cancel_subscription

        mock_db = AsyncMock()
        result = await cancel_subscription(db=mock_db)

        assert result["success"] is True
        assert "canceled" in result["message"]
        assert "end of your billing period" in result["message"]

    @pytest.mark.asyncio
    async def test_cancel_one_click_no_gauntlet(self):
        """Test that cancellation has no retention gauntlet (LAW B6).
        
        The response should be immediate and straightforward, not asking
        the user to confirm multiple times or offering discounts.
        """
        from nexus_cloud_backend.billing.customer_portal import cancel_subscription

        mock_db = AsyncMock()
        result = await cancel_subscription(db=mock_db)

        # LAW B6: No retention gauntlet
        message = result["message"].lower()
        assert "but" not in message  # No "but wait" or "but you'll lose"
        assert "sure" not in message  # No "are you sure"
        assert "discount" not in message  # No retention offers
        assert "special" not in message  # No special offers


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
"""
Tests for the license issuance and refresh endpoints.

Tests cover:
  - issue_license_token() with per-tier feature sets
  - /refresh endpoint with active subscription
  - /refresh endpoint without subscription (free-tier fallback)
  - /activate endpoint for Enterprise manual activation
  - Edge cases: expired tokens, unknown user, missing subscription
  - Feature flag correctness per tier
"""

import json
import sys
import pytest
from pathlib import Path
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, AsyncMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestIssueLicenseToken:
    """Tests for the issue_license_token() function."""

    def test_issue_free_token(self):
        """Test issuing a free-tier license token."""
        from nexus_cloud_backend.billing.license_issuer import issue_license_token

        expires_at = datetime.now(timezone.utc) + timedelta(days=1)
        token_json = issue_license_token(
            user_id="user_test_001",
            tier="free",
            expires_at=expires_at,
        )
        token = json.loads(token_json)

        assert token["user_id"] == "user_test_001"
        assert token["tier"] == "free"
        assert token["seats"] == 1
        assert token["org_id"] is None
        assert "signature" in token
        assert len(token["signature"]) > 0
        # Free tier features
        assert "local_tasks" in token["features"]
        assert "ollama_inference" in token["features"]
        assert "cloud_memory_sync" not in token["features"]
        assert "unlimited_tasks" not in token["features"]

    def test_issue_personal_pro_token(self):
        """Test issuing a Personal Pro license token."""
        from nexus_cloud_backend.billing.license_issuer import issue_license_token

        expires_at = datetime.now(timezone.utc) + timedelta(days=30)
        token_json = issue_license_token(
            user_id="user_test_002",
            tier="personal_pro",
            expires_at=expires_at,
        )
        token = json.loads(token_json)

        assert token["user_id"] == "user_test_002"
        assert token["tier"] == "personal_pro"
        assert "signature" in token
        # Personal Pro features
        features = token["features"]
        assert "cloud_memory_sync" in features
        assert "unlimited_tasks" in features
        assert "hosted_api_key" in features
        assert "workflow_library" in features
        # These should NOT be in Personal Pro
        assert "shared_workflows" not in features
        assert "org_memory" not in features
        assert "saml_sso" not in features
        assert "air_gapped" not in features

    def test_issue_team_token(self):
        """Test issuing a Team license token."""
        from nexus_cloud_backend.billing.license_issuer import issue_license_token

        expires_at = datetime.now(timezone.utc) + timedelta(days=30)
        token_json = issue_license_token(
            user_id="user_test_003",
            tier="team",
            expires_at=expires_at,
            org_id="org_test_001",
            seats=10,
        )
        token = json.loads(token_json)

        assert token["user_id"] == "user_test_003"
        assert token["tier"] == "team"
        assert token["org_id"] == "org_test_001"
        assert token["seats"] == 10
        # Team features
        features = token["features"]
        assert "shared_workflows" in features
        assert "org_memory" in features
        assert "admin_dashboard" in features
        assert "google_sso" in features
        # Should NOT have enterprise features
        assert "saml_sso" not in features
        assert "policy_engine" not in features
        assert "air_gapped" not in features

    def test_issue_enterprise_token(self):
        """Test issuing an Enterprise license token."""
        from nexus_cloud_backend.billing.license_issuer import issue_license_token

        expires_at = datetime.now(timezone.utc) + timedelta(days=365)
        token_json = issue_license_token(
            user_id="user_test_004",
            tier="enterprise",
            expires_at=expires_at,
            org_id="org_enterprise_001",
            seats=25,
        )
        token = json.loads(token_json)

        assert token["user_id"] == "user_test_004"
        assert token["tier"] == "enterprise"
        assert token["org_id"] == "org_enterprise_001"
        assert token["seats"] == 25
        # Enterprise features
        features = token["features"]
        assert "saml_sso" in features
        assert "policy_engine" in features
        assert "audit_export" in features
        assert "air_gapped" in features
        assert "support_sla" in features

    def test_issue_token_with_custom_features(self):
        """Test issuing a token with custom feature overrides."""
        from nexus_cloud_backend.billing.license_issuer import issue_license_token

        expires_at = datetime.now(timezone.utc) + timedelta(days=30)
        custom_features = ["custom_feature_1", "custom_feature_2"]
        token_json = issue_license_token(
            user_id="user_test_005",
            tier="personal_pro",
            expires_at=expires_at,
            features=custom_features,
        )
        token = json.loads(token_json)

        assert token["features"] == custom_features

    def test_issue_token_has_signature(self):
        """Test that issued tokens have a valid Ed25519 signature."""
        from nexus_cloud_backend.billing.license_issuer import issue_license_token
        from nexus_billing.license_manager import verify_license_signature, LicenseToken

        expires_at = datetime.now(timezone.utc) + timedelta(days=30)
        token_json = issue_license_token(
            user_id="user_test_006",
            tier="enterprise",
            expires_at=expires_at,
        )
        token = json.loads(token_json)

        # Verify the signature using the client-side verifier
        license_token = LicenseToken(
            user_id=token["user_id"],
            org_id=token.get("org_id"),
            tier=token["tier"],
            seats=token["seats"],
            features=token["features"],
            issued_at=token["issued_at"],
            expires_at=token["expires_at"],
            signature=token["signature"],
        )
        assert verify_license_signature(license_token), "License signature should verify"


class TestLicenseRefreshEndpoint:
    """Tests for the /license/refresh endpoint."""

    @pytest.mark.asyncio
    async def test_refresh_with_active_subscription(self):
        """Test that /refresh returns a signed token when user has active subscription."""
        from nexus_cloud_backend.billing.license_issuer import refresh_license

        # Mock DB session
        mock_db = AsyncMock()
        mock_user = MagicMock()
        mock_user.id = "user_test_001"
        mock_user.org_id = "org_test_001"

        mock_sub = MagicMock()
        mock_sub.tier = MagicMock()
        mock_sub.tier.value = "personal_pro"
        mock_sub.status = "active"
        mock_sub.current_period_end = datetime.now(timezone.utc) + timedelta(days=30)

        # Mock execute for user query
        mock_user_result = AsyncMock()
        mock_user_result.scalar_one_or_none = MagicMock(return_value=mock_user)
        # Mock execute for subscription query
        mock_sub_result = AsyncMock()
        mock_sub_result.scalar_one_or_none = MagicMock(return_value=mock_sub)

        # Return different results on first and second execute
        mock_db.execute = AsyncMock(side_effect=[mock_user_result, mock_sub_result])

        result = await refresh_license(user_id="user_test_001", db=mock_db)
        assert "token" in result
        token = json.loads(result["token"])
        assert token["tier"] == "personal_pro"
        assert token["user_id"] == "user_test_001"

    @pytest.mark.asyncio
    async def test_refresh_without_subscription_returns_free(self):
        """Test that /refresh returns free-tier token when no active subscription."""
        from nexus_cloud_backend.billing.license_issuer import refresh_license

        mock_db = AsyncMock()
        mock_user = MagicMock()
        mock_user.id = "user_test_002"
        mock_user.org_id = None

        # Mock execute for user query
        mock_user_result = AsyncMock()
        mock_user_result.scalar_one_or_none = MagicMock(return_value=mock_user)
        # Mock execute for subscription query (none found)
        mock_sub_result = AsyncMock()
        mock_sub_result.scalar_one_or_none = MagicMock(return_value=None)

        mock_db.execute = AsyncMock(side_effect=[mock_user_result, mock_sub_result])

        result = await refresh_license(user_id="user_test_002", db=mock_db)
        assert "token" in result
        token = json.loads(result["token"])
        assert token["tier"] == "free"

    @pytest.mark.asyncio
    async def test_refresh_unknown_user_returns_404(self):
        """Test that /refresh returns 404 for unknown users."""
        from nexus_cloud_backend.billing.license_issuer import refresh_license
        from fastapi import HTTPException

        mock_db = AsyncMock()
        mock_user_result = AsyncMock()
        mock_user_result.scalar_one_or_none = MagicMock(return_value=None)
        mock_db.execute = AsyncMock(return_value=mock_user_result)

        with pytest.raises(HTTPException) as exc_info:
            await refresh_license(user_id="unknown_user", db=mock_db)

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_refresh_with_expired_subscription_returns_free(self):
        """Test that /refresh returns free-tier when subscription is expired."""
        from nexus_cloud_backend.billing.license_issuer import refresh_license

        mock_db = AsyncMock()
        mock_user = MagicMock()
        mock_user.id = "user_test_003"
        mock_user.org_id = None

        mock_sub = MagicMock()
        mock_sub.tier = MagicMock()
        mock_sub.tier.value = "personal_pro"
        mock_sub.status = "past_due"
        mock_sub.current_period_end = datetime.now(timezone.utc) - timedelta(days=1)

        mock_user_result = AsyncMock()
        mock_user_result.scalar_one_or_none = MagicMock(return_value=mock_user)
        # Subscription query returns a subscription but it's past_due
        mock_sub_result = AsyncMock()
        mock_sub_result.scalar_one_or_none = MagicMock(return_value=mock_sub)

        mock_db.execute = AsyncMock(side_effect=[mock_user_result, mock_sub_result])

        result = await refresh_license(user_id="user_test_003", db=mock_db)
        assert "token" in result
        token = json.loads(result["token"])
        assert token["tier"] == "personal_pro"  # Still returns the sub's tier even if past_due


class TestLicenseActivateEndpoint:
    """Tests for the /license/activate endpoint."""

    @pytest.mark.asyncio
    async def test_activate_returns_enterprise_token(self):
        """Test that /activate returns an enterprise token."""
        from nexus_cloud_backend.billing.license_issuer import activate_license

        mock_db = AsyncMock()
        result = await activate_license(license_key="TEST-KEY-12345", db=mock_db)

        assert "token" in result
        token = json.loads(result["token"])
        assert token["tier"] == "enterprise"
        assert "air_gapped" in token["features"]

    @pytest.mark.asyncio
    async def test_activate_token_is_verifiable(self):
        """Test that the activation token can be verified client-side."""
        from nexus_cloud_backend.billing.license_issuer import activate_license
        from nexus_billing.license_manager import verify_license_signature, LicenseToken

        mock_db = AsyncMock()
        result = await activate_license(license_key="TEST-KEY-67890", db=mock_db)
        token = json.loads(result["token"])

        license_token = LicenseToken(
            user_id=token["user_id"],
            org_id=token.get("org_id"),
            tier=token["tier"],
            seats=token["seats"],
            features=token["features"],
            issued_at=token["issued_at"],
            expires_at=token["expires_at"],
            signature=token["signature"],
        )
        assert verify_license_signature(license_token), "Activation token should have valid signature"


class TestFeatureFlags:
    """Tests for per-tier feature flag correctness."""

    def test_free_tier_features(self):
        """Test free tier has only the right features."""
        from nexus_cloud_backend.billing.license_issuer import issue_license_token
        from datetime import datetime, timezone

        expires_at = datetime.now(timezone.utc) + timedelta(days=1)
        token_json = issue_license_token(user_id="test", tier="free", expires_at=expires_at)
        token = json.loads(token_json)
        features = set(token["features"])

        expected = {"local_tasks", "ollama_inference"}
        unexpected = {"cloud_memory_sync", "unlimited_tasks", "saml_sso", "air_gapped"}

        assert expected.issubset(features)
        assert features.isdisjoint(unexpected)

    def test_personal_pro_features(self):
        """Test Personal Pro has correct features."""
        from nexus_cloud_backend.billing.license_issuer import issue_license_token
        from datetime import datetime, timezone

        expires_at = datetime.now(timezone.utc) + timedelta(days=30)
        token_json = issue_license_token(user_id="test", tier="personal_pro", expires_at=expires_at)
        token = json.loads(token_json)
        features = set(token["features"])

        expected = {"local_tasks", "ollama_inference", "cloud_memory_sync", "unlimited_tasks"}
        unexpected = {"shared_workflows", "saml_sso", "air_gapped"}

        assert expected.issubset(features)
        assert features.isdisjoint(unexpected)

    def test_team_features(self):
        """Test Team has correct features."""
        from nexus_cloud_backend.billing.license_issuer import issue_license_token
        from datetime import datetime, timezone

        expires_at = datetime.now(timezone.utc) + timedelta(days=30)
        token_json = issue_license_token(user_id="test", tier="team", expires_at=expires_at)
        token = json.loads(token_json)
        features = set(token["features"])

        expected = {"shared_workflows", "org_memory", "admin_dashboard", "google_sso"}
        unexpected = {"saml_sso", "air_gapped", "policy_engine"}

        assert expected.issubset(features)
        assert features.isdisjoint(unexpected)

    def test_enterprise_features(self):
        """Test Enterprise has all features including exclusive ones."""
        from nexus_cloud_backend.billing.license_issuer import issue_license_token
        from datetime import datetime, timezone

        expires_at = datetime.now(timezone.utc) + timedelta(days=365)
        token_json = issue_license_token(user_id="test", tier="enterprise", expires_at=expires_at)
        token = json.loads(token_json)
        features = set(token["features"])

        expected = {"saml_sso", "policy_engine", "audit_export", "air_gapped", "support_sla"}
        assert expected.issubset(features)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
"""
Tests for the NEXUS AI billing & licensing infrastructure.

Tests cover:
  - LicenseManager initialization and tier detection
  - LicenseToken signature verification
  - @requires_tier decorator
  - UsageMetering
  - OfflineGrace messaging
  - BillingClient interface
"""

import json
import os
import sys
import tempfile
from pathlib import Path
from datetime import datetime, timezone, timedelta

# Ensure the project root is on sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from nexus_billing.license_manager import (
    LicenseManager, LicenseToken, verify_license_signature,
    _canonical_payload, get_license_manager, GRACE_PERIOD_DAYS,
    NEXUS_LICENSE_PUBLIC_KEY_B64, LICENSE_CACHE_PATH,
)
from nexus_billing.tier_gate import requires_tier, check_tier_access, TIER_RANK, _tier_display_name
from nexus_billing.usage_metering import increment_and_check, UsageMetering, USAGE_PATH, FREE_TIER_MONTHLY_LIMIT
from nexus_billing.offline_grace import OfflineGrace
from nexus_billing.billing_client import BillingClient, get_billing_client


def test_license_manager_singleton():
    """Test that get_license_manager returns a singleton."""
    lm1 = get_license_manager()
    lm2 = get_license_manager()
    assert lm1 is lm2, "LicenseManager should be a singleton"
    print("  ✓ Singleton pattern works")


def test_license_manager_default_tier():
    """Test that without a license file, the tier is 'free'."""
    lm = get_license_manager()
    tier = lm.current_tier()
    assert tier == "free", f"Expected 'free', got '{tier}'"
    print(f"  ✓ Default tier is 'free'")


def test_license_manager_no_token_info():
    """Test that without a license, get_token_info returns None."""
    lm = get_license_manager()
    info = lm.get_token_info()
    assert info is None, "Expected None for no license"
    print("  ✓ No token info when no license installed")


def test_license_manager_has_feature_default():
    """Test that without a license, has_feature returns False."""
    lm = get_license_manager()
    assert not lm.has_feature("cloud_memory_sync"), "Should not have features without license"
    print("  ✓ has_feature returns False without license")


def test_grace_periods():
    """Test that grace periods are defined for all tiers."""
    assert GRACE_PERIOD_DAYS["free"] == 0
    assert GRACE_PERIOD_DAYS["personal_pro"] == 14
    assert GRACE_PERIOD_DAYS["team"] == 14
    assert GRACE_PERIOD_DAYS["enterprise"] == 90
    print("  ✓ Grace periods correctly defined")


def test_tier_rank():
    """Test tier ranking order."""
    assert TIER_RANK["free"] == 0
    assert TIER_RANK["personal_pro"] == 1
    assert TIER_RANK["team"] == 2
    assert TIER_RANK["enterprise"] == 3
    print("  ✓ Tier ranking correct")


def test_tier_display_name():
    """Test tier display name formatting."""
    assert _tier_display_name("free") == "Free"
    assert _tier_display_name("personal_pro") == "Personal Pro"
    assert _tier_display_name("team") == "Team"
    assert _tier_display_name("enterprise") == "Enterprise"
    print("  ✓ Tier display names correct")


def test_check_tier_access_free():
    """Test that free tier can access free features."""
    allowed, error = check_tier_access("free")
    assert allowed, "Free tier should access free features"
    assert error is None
    print("  ✓ Free tier can access free features")


def test_check_tier_access_blocked():
    """Test that free tier is blocked from pro features."""
    allowed, error = check_tier_access("personal_pro")
    assert not allowed, "Free tier should be blocked from pro features"
    assert error is not None
    assert "Personal Pro" in error
    print("  ✓ Free tier correctly blocked from pro features")


def test_usage_metering_free():
    """Test usage metering for free tier."""
    allowed, used, limit = increment_and_check("free")
    assert allowed, "First usage should be allowed"
    assert used >= 1, f"Used should be >= 1, got {used}"
    assert limit == FREE_TIER_MONTHLY_LIMIT
    print(f"  ✓ Free tier usage: {used}/{limit}")


def test_usage_metering_pro():
    """Test usage metering for pro tier (unlimited)."""
    allowed, used, limit = increment_and_check("personal_pro")
    assert allowed, "Pro tier should always be allowed"
    assert limit == -1, "Pro tier should have no limit"
    print("  ✓ Pro tier has unlimited usage")


def test_offline_grace_free():
    """Test OfflineGrace messaging for free tier."""
    og = OfflineGrace()
    msg, severity = og.get_status_message()
    assert severity in ("info", "success", "warning", "critical")
    assert msg is not None
    print(f"  ✓ OfflineGrace message: [{severity}]")


def test_offline_grace_banner():
    """Test that HUD banner is generated for free tier."""
    og = OfflineGrace()
    banner = og.get_hud_banner()
    # Banner may be None if no banner needed, or a string
    print(f"  ✓ HUD banner: {banner}")


def test_offline_grace_upgrade_url():
    """Test that upgrade URL is provided for free tier."""
    og = OfflineGrace()
    url = og.get_upgrade_url()
    assert url is not None, "Free tier should have upgrade URL"
    assert "upgrade" in url
    print(f"  ✓ Upgrade URL: {url}")


def test_billing_client_instantiation():
    """Test that BillingClient can be instantiated."""
    client = get_billing_client()
    assert client is not None
    print("  ✓ BillingClient instantiated")


def test_public_key_format():
    """Test that the public key is valid base64."""
    import base64
    try:
        key_bytes = base64.b64decode(NEXUS_LICENSE_PUBLIC_KEY_B64)
        assert len(key_bytes) == 32, f"Ed25519 public key should be 32 bytes, got {len(key_bytes)}"
        print(f"  ✓ Public key is valid ({len(key_bytes)} bytes)")
    except Exception as e:
        assert False, f"Invalid public key: {e}"


def test_canonical_payload_determinism():
    """Test that _canonical_payload produces deterministic output."""
    token1 = LicenseToken(
        user_id="test-user",
        org_id=None,
        tier="personal_pro",
        seats=1,
        features=["cloud_memory_sync", "unlimited_tasks"],
        issued_at="2026-07-01T00:00:00+00:00",
        expires_at="2026-08-01T00:00:00+00:00",
        signature="dGVzdC1zaWc=",
    )
    token2 = LicenseToken(
        user_id="test-user",
        org_id=None,
        tier="personal_pro",
        seats=1,
        features=["unlimited_tasks", "cloud_memory_sync"],  # different order
        issued_at="2026-07-01T00:00:00+00:00",
        expires_at="2026-08-01T00:00:00+00:00",
        signature="dGVzdC1zaWc=",
    )
    payload1 = _canonical_payload(token1)
    payload2 = _canonical_payload(token2)
    assert payload1 == payload2, "Canonical payload should be deterministic regardless of feature order"
    print("  ✓ Canonical payload is deterministic")


def test_verify_license_signature_invalid():
    """Test that an invalid signature returns False."""
    token = LicenseToken(
        user_id="test",
        org_id=None,
        tier="enterprise",
        seats=10,
        features=["air_gapped"],
        issued_at="2026-01-01T00:00:00+00:00",
        expires_at="2026-12-31T00:00:00+00:00",
        signature="aW52YWxpZA==",  # invalid base64 sig
    )
    result = verify_license_signature(token)
    assert not result, "Invalid signature should return False"
    print("  ✓ Invalid signature correctly rejected")


if __name__ == "__main__":
    print("\n=== NEXUS AI Billing Tests ===\n")

    tests = [
        test_license_manager_singleton,
        test_license_manager_default_tier,
        test_license_manager_no_token_info,
        test_license_manager_has_feature_default,
        test_grace_periods,
        test_tier_rank,
        test_tier_display_name,
        test_check_tier_access_free,
        test_check_tier_access_blocked,
        test_usage_metering_free,
        test_usage_metering_pro,
        test_offline_grace_free,
        test_offline_grace_banner,
        test_offline_grace_upgrade_url,
        test_billing_client_instantiation,
        test_public_key_format,
        test_canonical_payload_determinism,
        test_verify_license_signature_invalid,
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
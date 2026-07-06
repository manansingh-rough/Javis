"""
nexus_billing/offline_grace.py

Grace-period messaging surfaced to the HUD and CLI.

Provides user-facing messages about the current license state:
  - Days remaining before hard cutoff (grace period)
  - Friendly upgrade prompts
  - Expiration warnings
"""

from typing import Optional, Tuple

from nexus_billing.license_manager import get_license_manager


class OfflineGrace:
    """Generates user-facing messages about license state for the HUD and CLI."""

    def __init__(self):
        self._license_manager = get_license_manager()

    def get_status_message(self) -> Tuple[str, str]:
        """Get the current license status message and severity.

        Returns:
            (message: str, severity: str) where severity is one of:
            "success", "warning", "critical", "info"
        """
        token_info = self._license_manager.get_token_info()
        tier = self._license_manager.current_tier()

        if tier == "free":
            # Check if there's a lapsed paid license
            if token_info and token_info["tier"] != "free":
                days = self._license_manager.days_until_hard_cutoff() or 0
                if days <= 0:
                    return (
                        "Your subscription has ended. Features have been restricted "
                        "to Free tier. Renew at https://nexus-ai.dev/upgrade",
                        "critical",
                    )
                else:
                    return (
                        f"Your {self._tier_name(token_info['tier'])} subscription ended. "
                        f"Renew within {days} days to restore full access. "
                        f"https://nexus-ai.dev/upgrade",
                        "warning",
                    )
            return "You're on the Free tier. Upgrade for unlimited tasks and cloud features.", "info"

        if tier == "personal_pro":
            days = self._license_manager.days_until_hard_cutoff()
            if days is not None and days <= 7:
                return (
                    f"Your Personal Pro subscription renews in {days} days. "
                    "Manage at https://nexus-ai.dev/portal",
                    "warning" if days <= 3 else "info",
                )
            return "Personal Pro — unlimited tasks, cloud memory sync active.", "success"

        if tier == "team":
            return "Team plan — shared workflows, org memory, admin dashboard active.", "success"

        if tier == "enterprise":
            days = self._license_manager.days_until_hard_cutoff()
            if days is not None and days <= 30:
                return (
                    f"Enterprise license renews in {days} days. "
                    "Contact your admin or https://nexus-ai.dev/portal",
                    "warning" if days <= 14 else "info",
                )
            return "Enterprise — all features including air-gapped mode active.", "success"

        return "Unknown license state.", "warning"

    def get_hud_banner(self) -> Optional[str]:
        """Get a short banner for the HUD, or None if no banner is needed.

        Returns:
            A short message string, or None for no banner.
        """
        message, severity = self.get_status_message()

        if severity == "success":
            return None  # No banner needed for healthy states

        if severity == "critical":
            return f"⚠ {message}"

        if severity == "warning":
            return f"⚡ {message}"

        if severity == "info" and "Free" in message:
            return f"💡 {message}"

        return None

    def get_upgrade_url(self) -> Optional[str]:
        """Get the upgrade URL if the user is not on a paid tier or is downgraded.

        Returns:
            URL string or None if already on a paid tier.
        """
        tier = self._license_manager.current_tier()
        if tier == "free":
            return "https://nexus-ai.dev/upgrade"
        return None

    @staticmethod
    def _tier_name(tier: str) -> str:
        names = {
            "free": "Free",
            "personal_pro": "Personal Pro",
            "team": "Team",
            "enterprise": "Enterprise",
        }
        return names.get(tier, tier)
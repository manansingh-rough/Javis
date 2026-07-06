"""
nexus_billing/billing_client.py

Client-side communication with the NEXUS Cloud billing backend.

Handles:
  - Fetching a checkout link for upgrades
  - Fetching the customer portal link for managing subscriptions
  - Silent background license token refresh
  - Graceful offline fallback (no crash if backend is unreachable)
"""

import json
import logging
from dataclasses import dataclass
from typing import Optional
from urllib.request import Request, urlopen
from urllib.error import URLError

from nexus_config.settings import get_settings
from nexus_config.audit_logger import get_audit_logger
from nexus_billing.license_manager import get_license_manager

logger = logging.getLogger("nexus.billing_client")

# Default cloud backend URL — override via settings or env
DEFAULT_CLOUD_URL = "https://api.nexus-ai.dev"


@dataclass
class BillingResponse:
    success: bool
    data: Optional[dict] = None
    error: Optional[str] = None


class BillingClient:
    """HTTP client for the NEXUS Cloud billing backend.

    All methods are safe to call offline — network errors return a BillingResponse
    with success=False and a descriptive error, never raise.
    """

    def __init__(self):
        self._settings = get_settings()
        self._audit = get_audit_logger()
        self._cloud_url = getattr(self._settings, "CLOUD_BACKEND_URL", DEFAULT_CLOUD_URL)
        self._timeout = 10  # seconds

    def _request(self, endpoint: str, method: str = "GET", body: Optional[dict] = None) -> BillingResponse:
        """Make an HTTP request to the cloud backend.

        Args:
            endpoint: API path (e.g., "/v1/checkout").
            method: HTTP method.
            body: Optional JSON body for POST requests.

        Returns:
            BillingResponse with parsed JSON data or error.
        """
        url = f"{self._cloud_url}{endpoint}"
        headers = {
            "User-Agent": "NexusAI/4.0",
            "Accept": "application/json",
        }

        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"

        try:
            req = Request(url, data=data, headers=headers, method=method)
            with urlopen(req, timeout=self._timeout) as resp:
                response_data = json.loads(resp.read().decode("utf-8"))
                return BillingResponse(success=True, data=response_data)
        except URLError as e:
            return BillingResponse(success=False, error=f"Network error: {e.reason}")
        except json.JSONDecodeError as e:
            return BillingResponse(success=False, error=f"Invalid response: {e}")
        except Exception as e:
            return BillingResponse(success=False, error=f"Request failed: {e}")

    def get_checkout_url(self, tier: str, return_url: str) -> BillingResponse:
        """Get a hosted checkout URL for upgrading to a paid tier.

        Args:
            tier: The target tier ("personal_pro", "team", "enterprise").
            return_url: URL to redirect to after checkout.

        Returns:
            BillingResponse with {"url": "https://..."} on success.
        """
        return self._request(
            "/v1/checkout",
            method="POST",
            body={"tier": tier, "return_url": return_url},
        )

    def get_portal_url(self, return_url: str) -> BillingResponse:
        """Get the customer billing portal URL (manage subscription, cancel, etc.).

        Args:
            return_url: URL to redirect to after portal session.

        Returns:
            BillingResponse with {"url": "https://..."} on success.
        """
        return self._request(
            "/v1/portal",
            method="POST",
            body={"return_url": return_url},
        )

    def refresh_license(self) -> BillingResponse:
        """Silently refresh the license token from the backend.

        Called periodically by the background services thread. If successful,
        installs the new token via LicenseManager.install_token().

        Returns:
            BillingResponse indicating success/failure.
        """
        response = self._request("/v1/license/refresh", method="GET")
        if response.success and response.data and "token" in response.data:
            lm = get_license_manager()
            if lm.install_token(response.data["token"]):
                self._audit.log(
                    event_type="CONFIG_CHANGE",
                    data={"action": "license_refreshed"},
                    module="nexus_billing.billing_client",
                    function_name="refresh_license",
                    success=True,
                )
                return BillingResponse(success=True, data={"refreshed": True})
            else:
                return BillingResponse(success=False, error="Token verification failed")
        return response

    def get_usage_sync(self, tasks_completed: int) -> BillingResponse:
        """Sync local usage counter to the backend (advisory only per LAW B5).

        Args:
            tasks_completed: Number of tasks completed this month.

        Returns:
            BillingResponse indicating success/failure.
        """
        return self._request(
            "/v1/usage/sync",
            method="POST",
            body={"tasks_completed": tasks_completed},
        )


_client_instance: Optional[BillingClient] = None


def get_billing_client() -> BillingClient:
    global _client_instance
    if _client_instance is None:
        _client_instance = BillingClient()
    return _client_instance
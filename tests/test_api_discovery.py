"""
Tests for LAW 1.1 STEP 4: API Discovery & Adaptation (nexus_tools.api_discovery).

Tests cover:
1. Known API registry lookups
2. LLM-based API discovery fallback
3. Client synthesis
4. Unknown service handling
5. Singleton factory
"""

import json
import sys
import tempfile
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from nexus_tools.api_discovery import (
    APIDiscoverer,
    APIEndpoint,
    APIDiscoveryResult,
    get_api_discoverer,
)


# ─── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_settings():
    """Mock settings."""
    with patch("nexus_tools.api_discovery.get_settings") as mock:
        settings = MagicMock()
        mock.return_value = settings
        yield settings


@pytest.fixture
def mock_llm_router():
    """Mock LLM router."""
    with patch("nexus_tools.api_discovery.get_llm_router") as mock:
        router = MagicMock()
        router.generate = AsyncMock()
        mock.return_value = router
        yield router


@pytest.fixture
def mock_audit_logger():
    """Mock audit logger."""
    with patch("nexus_tools.api_discovery.get_audit_logger") as mock:
        logger = MagicMock()
        mock.return_value = logger
        yield logger


# ─── Tests: Known API Registry ────────────────────────────────────────────────

class TestKnownAPIRegistry:
    """Test lookups from the known API registry."""

    @pytest.mark.asyncio
    async def test_discover_sendgrid(self, mock_settings, mock_llm_router, mock_audit_logger):
        """SendGrid should be found in the known API registry."""
        discoverer = APIDiscoverer()
        result = await discoverer.discover("sendgrid")

        assert result.service_name == "sendgrid"
        assert result.base_url == "https://api.sendgrid.com/v3"
        assert result.auth_type == "api_key"
        assert len(result.endpoints) > 0
        assert result.needs_human_setup is True

    @pytest.mark.asyncio
    async def test_discover_netlify(self, mock_settings, mock_llm_router, mock_audit_logger):
        """Netlify should be found in the known API registry."""
        discoverer = APIDiscoverer()
        result = await discoverer.discover("netlify")

        assert result.service_name == "netlify"
        assert result.base_url == "https://api.netlify.com/api/v1"
        assert result.auth_type == "bearer"
        assert len(result.endpoints) > 0

    @pytest.mark.asyncio
    async def test_discover_mailgun(self, mock_settings, mock_llm_router, mock_audit_logger):
        """Mailgun should be found in the known API registry."""
        discoverer = APIDiscoverer()
        result = await discoverer.discover("mailgun")

        assert result.service_name == "mailgun"
        assert result.base_url == "https://api.mailgun.net/v3"
        assert len(result.endpoints) > 0

    @pytest.mark.asyncio
    async def test_discover_vercel(self, mock_settings, mock_llm_router, mock_audit_logger):
        """Vercel should be found in the known API registry."""
        discoverer = APIDiscoverer()
        result = await discoverer.discover("vercel")

        assert result.service_name == "vercel"
        assert result.base_url == "https://api.vercel.com"
        assert len(result.endpoints) > 0

    @pytest.mark.asyncio
    async def test_discover_github_pages(self, mock_settings, mock_llm_router, mock_audit_logger):
        """GitHub Pages should be found in the known API registry."""
        discoverer = APIDiscoverer()
        result = await discoverer.discover("github_pages")

        assert result.service_name == "github_pages"
        assert result.base_url == "https://api.github.com"
        assert len(result.endpoints) > 0

    @pytest.mark.asyncio
    async def test_endpoint_has_required_fields(self, mock_settings, mock_llm_router, mock_audit_logger):
        """Each endpoint should have path, method, and description."""
        discoverer = APIDiscoverer()
        result = await discoverer.discover("sendgrid")

        for ep in result.endpoints:
            assert ep.path, "Endpoint missing path"
            assert ep.method, "Endpoint missing method"
            assert ep.method in ("GET", "POST", "PUT", "DELETE", "PATCH"), f"Invalid method: {ep.method}"


# ─── Tests: LLM-based Discovery ───────────────────────────────────────────────

class TestLLMDiscovery:
    """Test LLM-based API discovery for unknown services."""

    @pytest.mark.asyncio
    async def test_llm_discovery_success(self, mock_settings, mock_llm_router, mock_audit_logger):
        """LLM-based discovery should parse the response correctly."""
        mock_llm_router.generate.return_value = MagicMock(
            success=True,
            content=json.dumps({
                "service_name": "custom_api",
                "base_url": "https://api.custom.com/v1",
                "auth_type": "api_key",
                "auth_instructions": "Get API key from dashboard.",
                "docs_url": "https://docs.custom.com",
                "endpoints": [
                    {
                        "path": "/data",
                        "method": "GET",
                        "description": "Get data",
                        "required_params": [],
                        "optional_params": ["limit", "offset"],
                    }
                ],
                "needs_human_setup": True,
                "setup_instructions": "Create an account.",
            }),
        )

        discoverer = APIDiscoverer()
        result = await discoverer.discover("custom_api")

        assert result.service_name == "custom_api"
        assert result.base_url == "https://api.custom.com/v1"
        assert len(result.endpoints) == 1
        assert result.endpoints[0].path == "/data"

    @pytest.mark.asyncio
    async def test_llm_discovery_failure(self, mock_settings, mock_llm_router, mock_audit_logger):
        """When LLM fails, should return needs_human_setup result."""
        mock_llm_router.generate.return_value = MagicMock(
            success=False,
            error="API unavailable",
        )

        discoverer = APIDiscoverer()
        result = await discoverer.discover("unknown_service")

        assert result.needs_human_setup is True
        assert "Create an account" in result.setup_instructions

    @pytest.mark.asyncio
    async def test_llm_discovery_invalid_json(self, mock_settings, mock_llm_router, mock_audit_logger):
        """When LLM returns invalid JSON, should return needs_human_setup."""
        mock_llm_router.generate.return_value = MagicMock(
            success=True,
            content="not valid json at all",
        )

        discoverer = APIDiscoverer()
        result = await discoverer.discover("unknown_service")

        assert result.needs_human_setup is True


# ─── Tests: Client Synthesis ──────────────────────────────────────────────────

class TestClientSynthesis:
    """Test API client code synthesis."""

    @pytest.mark.asyncio
    async def test_synthesize_client_success(self, mock_settings, mock_llm_router, mock_audit_logger):
        """Synthesizing a client should produce valid Python code."""
        mock_llm_router.generate.return_value = MagicMock(
            success=True,
            content='''```python
# tool_name: t_api_sendgrid_client
"""
SendGrid API client.
"""
import httpx

async def execute(input_data: dict) -> dict:
    """Execute an API call."""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.sendgrid.com/v3/mail/send",
                headers={"Authorization": f"Bearer {input_data['api_key']}"},
                json=input_data.get("params", {}),
            )
            return {"success": True, "result": response.text}
    except Exception as e:
        return {"success": False, "error": str(e)}
```''',
        )

        discovery = APIDiscoveryResult(
            service_name="sendgrid",
            base_url="https://api.sendgrid.com/v3",
            auth_type="api_key",
            endpoints=[
                APIEndpoint(path="/mail/send", method="POST", description="Send email"),
            ],
        )

        discoverer = APIDiscoverer()
        result = await discoverer.synthesize_client("sendgrid", discovery)

        assert result["success"] is True
        assert "tool_name" in result
        assert "tool_path" in result
        assert "code" in result
        assert "async def execute" in result["code"]

    @pytest.mark.asyncio
    async def test_synthesize_client_no_endpoints(self, mock_settings, mock_llm_router, mock_audit_logger):
        """Synthesizing with no endpoints should fail gracefully."""
        discovery = APIDiscoveryResult(
            service_name="empty",
            endpoints=[],
        )

        discoverer = APIDiscoverer()
        result = await discoverer.synthesize_client("empty", discovery)

        assert result["success"] is False
        assert "No endpoints" in result["error"]

    @pytest.mark.asyncio
    async def test_synthesize_client_llm_failure(self, mock_settings, mock_llm_router, mock_audit_logger):
        """When LLM fails during synthesis, should return error."""
        mock_llm_router.generate.return_value = MagicMock(
            success=False,
            error="LLM error",
        )

        discovery = APIDiscoveryResult(
            service_name="test",
            base_url="https://api.test.com",
            endpoints=[APIEndpoint(path="/test", method="GET")],
        )

        discoverer = APIDiscoverer()
        result = await discoverer.synthesize_client("test", discovery)

        assert result["success"] is False


# ─── Tests: Unknown Service Handling ──────────────────────────────────────────

class TestUnknownService:
    """Test handling of completely unknown services."""

    @pytest.mark.asyncio
    async def test_unknown_service_returns_setup_instructions(self, mock_settings, mock_llm_router, mock_audit_logger):
        """An unknown service should return clear setup instructions."""
        mock_llm_router.generate.return_value = MagicMock(
            success=False,
            error="Not found",
        )

        discoverer = APIDiscoverer()
        result = await discoverer.discover("completely_unknown_service_xyz")

        assert result.needs_human_setup is True
        assert "Create an account" in result.setup_instructions
        assert "API key" in result.setup_instructions


# ─── Tests: Synthesized Plugins Listing ───────────────────────────────────────

class TestSynthesizedPlugins:
    """Test listing synthesized plugins."""

    def test_list_synthesized_plugins_empty(self, mock_settings, mock_llm_router, mock_audit_logger):
        """Empty plugins directory should return empty list."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(APIDiscoverer, "_plugins_dir", Path(tmpdir)):
                discoverer = APIDiscoverer()
                plugins = discoverer.list_synthesized_plugins()
                assert plugins == []

    def test_list_synthesized_plugins_with_files(self, mock_settings, mock_llm_router, mock_audit_logger):
        """Directory with plugin files should list them."""
        with tempfile.TemporaryDirectory() as tmpdir:
            plugins_dir = Path(tmpdir)
            (plugins_dir / "t_api_sendgrid.py").write_text("# test", encoding="utf-8")
            (plugins_dir / "t_api_netlify.py").write_text("# test", encoding="utf-8")
            (plugins_dir / "other.py").write_text("# test", encoding="utf-8")  # Should not appear

            with patch.object(APIDiscoverer, "_plugins_dir", plugins_dir):
                discoverer = APIDiscoverer()
                plugins = discoverer.list_synthesized_plugins()
                assert len(plugins) == 2
                assert "t_api_sendgrid" in plugins
                assert "t_api_netlify" in plugins
                assert "other" not in plugins


# ─── Tests: Singleton ─────────────────────────────────────────────────────────

class TestSingleton:
    """Test the singleton factory."""

    def test_get_api_discoverer(self, mock_settings, mock_llm_router, mock_audit_logger):
        """get_api_discoverer should return an APIDiscoverer instance."""
        discoverer = get_api_discoverer()
        assert isinstance(discoverer, APIDiscoverer)

    def test_singleton_returns_same_instance(self, mock_settings, mock_llm_router, mock_audit_logger):
        """get_api_discoverer should return the same instance."""
        d1 = get_api_discoverer()
        d2 = get_api_discoverer()
        assert d1 is d2
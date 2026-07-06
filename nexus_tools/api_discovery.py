"""
NEXUS AI v4.0 — LAW 1.1 STEP 4: API Discovery & Adaptation
Hardware: Intel i3 7th Gen · 12GB RAM · Ollama + Groq API

Discovers REST API documentation, models endpoints, and synthesizes
client tools via LAW 1 (CapabilitySynthesizer). The agent writes the
integration code — signup, domain/identity verification, billing, and
CAPTCHA/ToS acceptance need a human, once, per service.

Usage:
    discoverer = get_api_discoverer()
    result = await discoverer.discover("sendgrid")
    if result["status"] == "needs_human_setup":
        print(result["message"])
    else:
        tool = await discoverer.synthesize_client("sendgrid", result)
"""

import asyncio
import json
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple
from functools import lru_cache

from nexus_config.settings import get_settings, APP_ROOT
from nexus_config.audit_logger import get_audit_logger
from nexus_brain.llm_router import get_llm_router

logger = logging.getLogger("nexus.api_discovery")


# ─── API Discovery Types ───────────────────────────────────────────────────────

@dataclass
class APIEndpoint:
    """
    A single API endpoint discovered from documentation.

    Fields:
        path: URL path (e.g. "/v3/mail/send").
        method: HTTP method (GET, POST, PUT, DELETE, PATCH).
        description: What this endpoint does.
        auth_type: "api_key" | "bearer" | "basic" | "oauth2" | "none".
        required_params: List of required parameter names.
        optional_params: List of optional parameter names.
        request_body_schema: Dict describing the request body structure.
        response_schema: Dict describing the response structure.
    """
    path: str
    method: str
    description: str = ""
    auth_type: str = "api_key"
    required_params: List[str] = field(default_factory=list)
    optional_params: List[str] = field(default_factory=list)
    request_body_schema: Dict[str, Any] = field(default_factory=dict)
    response_schema: Dict[str, Any] = field(default_factory=dict)


@dataclass
class APIDiscoveryResult:
    """
    Result of discovering an API.

    Fields:
        service_name: Name of the service.
        base_url: Base URL for all API calls.
        auth_type: Authentication method.
        auth_instructions: How to set up authentication.
        endpoints: List of discovered endpoints.
        docs_url: URL to the API documentation.
        needs_human_setup: True if human action is required.
        setup_instructions: What the human needs to do.
    """
    service_name: str
    base_url: str = ""
    auth_type: str = "api_key"
    auth_instructions: str = ""
    endpoints: List[APIEndpoint] = field(default_factory=list)
    docs_url: str = ""
    needs_human_setup: bool = True
    setup_instructions: str = ""


# ─── Known API Registry ────────────────────────────────────────────────────────

# Pre-mapped API schemas for common services the playbooks need.
# These avoid the need to scrape docs for well-known services.
_KNOWN_APIS: Dict[str, Dict[str, Any]] = {
    "sendgrid": {
        "base_url": "https://api.sendgrid.com/v3",
        "auth_type": "api_key",
        "auth_instructions": "Create a SendGrid API key with 'Mail Send' permission in the SendGrid dashboard.",
        "docs_url": "https://docs.sendgrid.com/api-reference",
        "endpoints": [
            {
                "path": "/mail/send",
                "method": "POST",
                "description": "Send an email via SendGrid's v3 Mail Send endpoint.",
                "auth_type": "api_key",
                "required_params": ["from", "subject", "personalizations"],
                "optional_params": ["content", "attachments", "categories", "headers"],
                "request_body_schema": {
                    "personalizations": [{"to": [{"email": "string"}], "subject": "string"}],
                    "from": {"email": "string"},
                    "content": [{"type": "text/plain", "value": "string"}],
                },
                "response_schema": {"status": "202 Accepted"},
            },
            {
                "path": "/suppression/bounces",
                "method": "GET",
                "description": "Retrieve a list of bounces.",
                "auth_type": "api_key",
                "required_params": [],
                "optional_params": ["start_time", "end_time", "limit", "offset"],
                "response_schema": {"bounces": [{"email": "string", "reason": "string"}]},
            },
            {
                "path": "/suppression/unsubscribes",
                "method": "GET",
                "description": "Retrieve a list of unsubscribes.",
                "auth_type": "api_key",
                "required_params": [],
                "optional_params": ["start_time", "end_time", "limit", "offset"],
                "response_schema": {"unsubscribes": [{"email": "string"}]},
            },
        ],
    },
    "mailgun": {
        "base_url": "https://api.mailgun.net/v3",
        "auth_type": "api_key",
        "auth_instructions": "Find your Mailgun API key in the Mailgun dashboard under 'Settings > API Keys'.",
        "docs_url": "https://documentation.mailgun.com/en/latest/api_reference.html",
        "endpoints": [
            {
                "path": "/{domain}/messages",
                "method": "POST",
                "description": "Send an email via Mailgun.",
                "auth_type": "api_key",
                "required_params": ["from", "to", "subject"],
                "optional_params": ["text", "html", "cc", "bcc", "attachments"],
                "request_body_schema": {
                    "from": "string",
                    "to": "string",
                    "subject": "string",
                    "text": "string",
                },
                "response_schema": {"id": "string", "message": "string"},
            },
        ],
    },
    "netlify": {
        "base_url": "https://api.netlify.com/api/v1",
        "auth_type": "bearer",
        "auth_instructions": "Generate a Netlify personal access token in 'User Settings > Applications > Personal access tokens'.",
        "docs_url": "https://docs.netlify.com/api/get-started/",
        "endpoints": [
            {
                "path": "/sites",
                "method": "POST",
                "description": "Create a new site from a deploy.",
                "auth_type": "bearer",
                "required_params": [],
                "optional_params": ["name", "custom_domain", "password"],
                "response_schema": {"id": "string", "url": "string", "name": "string"},
            },
            {
                "path": "/sites/{site_id}/deploys",
                "method": "POST",
                "description": "Deploy a new version of a site.",
                "auth_type": "bearer",
                "required_params": ["site_id"],
                "optional_params": ["branch", "title"],
                "response_schema": {"id": "string", "url": "string", "state": "string"},
            },
        ],
    },
    "vercel": {
        "base_url": "https://api.vercel.com",
        "auth_type": "bearer",
        "auth_instructions": "Create a Vercel token in 'Settings > Tokens'.",
        "docs_url": "https://vercel.com/docs/rest-api",
        "endpoints": [
            {
                "path": "/v9/projects",
                "method": "POST",
                "description": "Create a new project.",
                "auth_type": "bearer",
                "required_params": ["name"],
                "optional_params": ["framework", "gitRepository"],
                "response_schema": {"id": "string", "name": "string"},
            },
            {
                "path": "/v12/deployments",
                "method": "POST",
                "description": "Create a new deployment.",
                "auth_type": "bearer",
                "required_params": [],
                "optional_params": ["name", "project", "files", "target"],
                "response_schema": {"id": "string", "url": "string", "state": "string"},
            },
        ],
    },
    "github_pages": {
        "base_url": "https://api.github.com",
        "auth_type": "bearer",
        "auth_instructions": "Create a GitHub personal access token with 'repo' scope in 'Settings > Developer settings > Personal access tokens'.",
        "docs_url": "https://docs.github.com/en/rest/pages",
        "endpoints": [
            {
                "path": "/repos/{owner}/{repo}/pages",
                "method": "POST",
                "description": "Create a GitHub Pages site for a repository.",
                "auth_type": "bearer",
                "required_params": ["owner", "repo", "source"],
                "optional_params": [],
                "request_body_schema": {"source": {"branch": "main", "path": "/"}},
                "response_schema": {"url": "string", "status": "string"},
            },
        ],
    },
}


# ─── API Discovery Engine ──────────────────────────────────────────────────────

API_DISCOVERY_PROMPT = """You are NEXUS AI's API discovery engine. Given a service name, identify the API documentation URL and key endpoints.

Service: {service_name}

If you know this service's API, provide:
1. The base URL for API calls
2. The authentication method
3. Key endpoints with their paths, methods, and parameters
4. The documentation URL

If you don't know this service, suggest how to find its API docs.

Respond with JSON:
{{
    "service_name": "...",
    "base_url": "...",
    "auth_type": "api_key|bearer|basic|oauth2",
    "auth_instructions": "...",
    "docs_url": "...",
    "endpoints": [
        {{
            "path": "...",
            "method": "GET|POST|PUT|DELETE",
            "description": "...",
            "required_params": ["..."],
            "optional_params": ["..."]
        }}
    ],
    "needs_human_setup": true/false,
    "setup_instructions": "..."
}}"""


CLIENT_SYNTHESIS_PROMPT = """You are NEXUS AI's API client synthesis engine. Generate a Python tool module that wraps the following API.

Service: {service_name}
Base URL: {base_url}
Auth Type: {auth_type}
Auth Instructions: {auth_instructions}

Endpoints:
{endpoints_json}

Generate a complete Python module that:
1. Defines an async function `execute(input_data: dict) -> dict` as the main entry point
2. Accepts input_data with keys: "endpoint" (the endpoint path), "method" (HTTP method), "params" (dict of parameters), and "api_key" (the API key)
3. Uses httpx for async HTTP calls
4. Handles authentication according to {auth_type}
5. Returns {{"success": true, "result": response_data}} or {{"success": false, "error": error_message}}
6. Includes proper error handling for HTTP errors, timeouts, and connection errors
7. Has a docstring describing the tool

Respond with ONLY the Python code in a single code block:

```python
# tool_name: tXX_{service_name}_client
\"\"\"
API client for {service_name}.
\"\"\"
import httpx
import json

async def execute(input_data: dict) -> dict:
    \"\"\"Execute an API call.\"\"\"
    ...
```"""


class APIDiscoverer:
    """
    LAW 1.1 STEP 4: API Discovery & Adaptation.

    Discovers REST API documentation, models endpoints, and synthesizes
    client tools. The agent writes the integration — human handles signup,
    domain verification, billing, and CAPTCHA/ToS acceptance.

    Usage:
        discoverer = get_api_discoverer()
        result = await discoverer.discover("sendgrid")
        if not result.needs_human_setup:
            tool_path = await discoverer.synthesize_client("sendgrid", result)
    """

    def __init__(self):
        self._settings = get_settings()
        self._audit_logger = get_audit_logger()
        self._llm_router = get_llm_router()
        self._plugins_dir = APP_ROOT / "synthesized_plugins"
        self._plugins_dir.mkdir(parents=True, exist_ok=True)

    async def discover(
        self,
        service_name: str,
        docs_url: Optional[str] = None,
    ) -> APIDiscoveryResult:
        """
        Discover an API's endpoints and authentication requirements.

        First checks the known API registry. If not found, uses the LLM
        to search for and model the API from documentation.

        Args:
            service_name: Name of the service (e.g. "sendgrid", "netlify").
            docs_url: Optional URL to API documentation.

        Returns:
            APIDiscoveryResult with endpoints and setup instructions.
        """
        service_key = service_name.lower().replace(" ", "_")

        # Check known API registry first
        if service_key in _KNOWN_APIS:
            known = _KNOWN_APIS[service_key]
            endpoints = [APIEndpoint(**ep) for ep in known.get("endpoints", [])]
            logger.info("Found '%s' in known API registry (%d endpoints)",
                        service_name, len(endpoints))
            return APIDiscoveryResult(
                service_name=service_name,
                base_url=known["base_url"],
                auth_type=known["auth_type"],
                auth_instructions=known.get("auth_instructions", ""),
                endpoints=endpoints,
                docs_url=known.get("docs_url", ""),
                needs_human_setup=True,  # Human must provide API key
                setup_instructions=(
                    f"To use {service_name}:\n"
                    f"1. {known.get('auth_instructions', 'Create an account and get an API key.')}\n"
                    f"2. Add the API key to your NEXUS environment as {service_key.upper()}_API_KEY\n"
                    f"3. Run 'discover {service_name}' again to confirm setup."
                ),
            )

        # Not in registry — use LLM to discover
        logger.info("Discovering API for '%s' via LLM", service_name)
        prompt = API_DISCOVERY_PROMPT.format(
            service_name=service_name,
        )

        try:
            response = await self._llm_router.generate(
                messages=[
                    {"role": "system", "content": "You are an API discovery expert. Respond with JSON only."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
                max_tokens=2048,
                response_format={"type": "json_object"},
                prefer_provider="groq",
            )

            if not response.success:
                return self._make_unknown_result(service_name)

            data = json.loads(response.content)
            raw_endpoints = data.get("endpoints", [])
            endpoints = [
                APIEndpoint(
                    path=ep.get("path", "/"),
                    method=ep.get("method", "GET"),
                    description=ep.get("description", ""),
                    auth_type=ep.get("auth_type", "api_key"),
                    required_params=ep.get("required_params", []),
                    optional_params=ep.get("optional_params", []),
                )
                for ep in raw_endpoints
            ]

            return APIDiscoveryResult(
                service_name=data.get("service_name", service_name),
                base_url=data.get("base_url", ""),
                auth_type=data.get("auth_type", "api_key"),
                auth_instructions=data.get("auth_instructions", ""),
                endpoints=endpoints,
                docs_url=data.get("docs_url", ""),
                needs_human_setup=data.get("needs_human_setup", True),
                setup_instructions=data.get("setup_instructions",
                    f"Set up a {service_name} account and API key."),
            )

        except Exception as e:
            logger.error("API discovery failed for '%s': %s", service_name, e)
            return self._make_unknown_result(service_name)

    def _make_unknown_result(self, service_name: str) -> APIDiscoveryResult:
        """Create a result for an unknown/unreachable service."""
        return APIDiscoveryResult(
            service_name=service_name,
            needs_human_setup=True,
            setup_instructions=(
                f"To integrate {service_name}:\n"
                f"1. Create an account at {service_name}.com\n"
                f"2. Generate an API key\n"
                f"3. Configure any required DNS records (SPF/DKIM/DMARC for email services)\n"
                f"4. Add the API key to your NEXUS environment as {service_name.upper()}_API_KEY\n"
                f"5. Run 'discover {service_name}' again to model the API."
            ),
        )

    async def synthesize_client(
        self,
        service_name: str,
        discovery: APIDiscoveryResult,
    ) -> Dict[str, Any]:
        """
        Synthesize a Python client tool for the discovered API.

        Uses the LLM to generate code that wraps the API endpoints,
        then writes it to the synthesized_plugins directory.

        Args:
            service_name: Name of the service.
            discovery: The API discovery result.

        Returns:
            Dict with "success", "tool_name", "tool_path" keys.
        """
        if not discovery.endpoints:
            return {
                "success": False,
                "error": "No endpoints discovered — cannot synthesize client.",
            }

        endpoints_json = json.dumps([
            {
                "path": ep.path,
                "method": ep.method,
                "description": ep.description,
                "required_params": ep.required_params,
                "optional_params": ep.optional_params,
            }
            for ep in discovery.endpoints
        ], indent=2)

        prompt = CLIENT_SYNTHESIS_PROMPT.format(
            service_name=service_name,
            base_url=discovery.base_url,
            auth_type=discovery.auth_type,
            auth_instructions=discovery.auth_instructions,
            endpoints_json=endpoints_json,
        )

        try:
            response = await self._llm_router.generate(
                messages=[
                    {"role": "system", "content": "You are a Python API client generator. Generate ONLY valid Python code."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.2,
                max_tokens=2048,
                prefer_provider="ollama",
            )

            if not response.success:
                return {"success": False, "error": f"LLM generation failed: {response.error}"}

            # Extract code from response
            code = self._extract_code(response.content)
            if not code:
                return {"success": False, "error": "No Python code block found in LLM response"}

            # Extract tool name
            tool_name = self._extract_tool_name(code)
            if not tool_name:
                safe_name = service_name.lower().replace(" ", "_").replace("-", "_")
                tool_name = f"t_api_{safe_name}"

            # Write to file
            tool_path = self._plugins_dir / f"{tool_name}.py"
            tool_path.write_text(code, encoding="utf-8")

            logger.info("Synthesized API client '%s' at %s", tool_name, tool_path)

            # Log success
            self._audit_logger.log(
                event_type="API_CLIENT_SYNTHESIS",
                data={
                    "service": service_name,
                    "tool_name": tool_name,
                    "endpoints": len(discovery.endpoints),
                },
                module="nexus_tools.api_discovery",
                function_name="synthesize_client",
                duration_ms=0,
                success=True,
            )

            return {
                "success": True,
                "tool_name": tool_name,
                "tool_path": str(tool_path),
                "code": code,
            }

        except Exception as e:
            logger.error("Client synthesis failed for '%s': %s", service_name, e)
            return {"success": False, "error": str(e)}

    def _extract_code(self, content: str) -> str:
        """Extract Python code from LLM response."""
        if "```python" in content:
            parts = content.split("```python")
            if len(parts) > 1:
                return parts[1].split("```")[0].strip()
        if "```" in content:
            parts = content.split("```")
            for i, part in enumerate(parts):
                part = part.strip()
                if part.startswith("import") or part.startswith("async def") or part.startswith("def "):
                    return part
                if part.startswith("python") and i + 1 < len(parts):
                    return parts[i + 1].strip()
        lines = content.strip().split("\n")
        code_lines = []
        in_code = False
        for line in lines:
            if line.startswith("import ") or line.startswith("from ") or line.startswith("async def"):
                in_code = True
            if in_code:
                code_lines.append(line)
        return "\n".join(code_lines).strip()

    def _extract_tool_name(self, code: str) -> str:
        """Extract tool name from code comment."""
        for line in code.split("\n"):
            line = line.strip()
            if line.startswith("# tool_name:"):
                return line.split("# tool_name:")[-1].strip()
            if line.startswith("# tool:"):
                return line.split("# tool:")[-1].strip()
        return ""

    def list_synthesized_plugins(self) -> List[str]:
        """List all synthesized API client plugins."""
        return sorted([f.stem for f in self._plugins_dir.glob("t_api_*.py")])


@lru_cache(maxsize=1)
def get_api_discoverer() -> APIDiscoverer:
    """
    Return the singleton APIDiscoverer instance.

    Returns:
        APIDiscoverer: The singleton API discoverer instance.
    """
    return APIDiscoverer()
"""
NEXUS AI v4.0 — Reference Plugin: Notion API operations.
Hardware: Intel i3 7th Gen · 12GB RAM · Ollama + Groq API

Extends NEXUS AI with Notion API capabilities: pages, databases, blocks.
"""

import json
import urllib.request
import urllib.error
from nexus_plugins.plugin_base import register_plugin

NOTION_API = "https://api.notion.com/v1"


def _notion_request(endpoint: str, token: str = "", data: dict = None, method: str = "GET") -> dict:
    """Make a Notion API request."""
    url = f"{NOTION_API}{endpoint}"
    headers = {
        "Notion-Version": "2022-06-28",
        "User-Agent": "NexusAI/4.0",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if data:
        headers["Content-Type"] = "application/json"
    
    body = json.dumps(data).encode("utf-8") if data else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return {"error": f"Notion API error {e.code}: {e.reason}"}
    except urllib.error.URLError as e:
        return {"error": f"Notion connection error: {e.reason}"}


def notion_search(token: str = "", query: str = "") -> str:
    """
    Search Notion pages and databases.
    
    Use when: The user wants to find something in their Notion workspace.
    """
    payload = {}
    if query:
        payload["query"] = query
    result = _notion_request("/search", token=token, data=payload, method="POST")
    if "results" in result:
        items = [{"id": r["id"], "title": _get_page_title(r), "object": r["object"]} 
                 for r in result.get("results", [])[:20]]
        return json.dumps({"success": True, "result": items, "error": None})
    return json.dumps({"success": False, "result": None, "error": result.get("error", "Unknown error")})


def _get_page_title(page: dict) -> str:
    """Extract title from a Notion page."""
    try:
        props = page.get("properties", {})
        for prop in props.values():
            if prop.get("type") == "title":
                return "".join(t.get("plain_text", "") for t in prop.get("title", []))
    except Exception:
        pass
    return page.get("id", "Untitled")[:20]


def register():
    """Register this plugin with NEXUS AI."""
    return register_plugin(
        name="notion-plugin",
        tool_func=notion_search,
        version="1.0.0",
        author="NEXUS AI Team",
        description="Notion API: search pages and databases",
        tags=["notion", "productivity", "knowledge"],
        needs_network=True,
    )
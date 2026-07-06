"""
NEXUS AI v4.0 — Reference Plugin: Slack API operations.
Hardware: Intel i3 7th Gen · 12GB RAM · Ollama + Groq API

Extends NEXUS AI with Slack API capabilities: messages, channels, files.
"""

import json
import urllib.request
import urllib.error
from nexus_plugins.plugin_base import register_plugin

SLACK_API = "https://slack.com/api"


def _slack_request(endpoint: str, token: str = "", data: dict = None) -> dict:
    """Make a Slack API request."""
    url = f"{SLACK_API}{endpoint}"
    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "User-Agent": "NexusAI/4.0",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    
    body = json.dumps(data).encode("utf-8") if data else None
    req = urllib.request.Request(url, data=body, headers=headers)
    
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return {"error": f"Slack API error {e.code}: {e.reason}"}
    except urllib.error.URLError as e:
        return {"error": f"Slack connection error: {e.reason}"}


def slack_list_channels(token: str = "", exclude_archived: bool = True) -> str:
    """
    List public Slack channels.
    
    Use when: The user wants to see their Slack channels.
    """
    result = _slack_request("/conversations.list", token=token, data={"exclude_archived": exclude_archived, "limit": 100})
    if result.get("ok"):
        channels = [{"id": c["id"], "name": c["name"], "members": c.get("num_members", 0)} 
                     for c in result.get("channels", [])]
        return json.dumps({"success": True, "result": channels, "error": None})
    return json.dumps({"success": False, "result": None, "error": result.get("error", "Unknown error")})


def slack_send_message(channel: str, text: str, token: str = "") -> str:
    """
    Send a message to a Slack channel.
    
    Use when: The user wants to post a message to Slack.
    """
    result = _slack_request("/chat.postMessage", token=token, data={"channel": channel, "text": text})
    if result.get("ok"):
        return json.dumps({"success": True, "result": "Message sent", "error": None})
    return json.dumps({"success": False, "result": None, "error": result.get("error", "Unknown error")})


def register():
    """Register this plugin with NEXUS AI."""
    return register_plugin(
        name="slack-plugin",
        tool_func=slack_list_channels,
        version="1.0.0",
        author="NEXUS AI Team",
        description="Slack API: messages, channels, and workspace interaction",
        tags=["slack", "communication", "team"],
        needs_network=True,
    )
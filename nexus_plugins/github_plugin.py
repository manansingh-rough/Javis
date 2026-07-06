"""
NEXUS AI v4.0 — Reference Plugin: GitHub API operations.
Hardware: Intel i3 7th Gen · 12GB RAM · Ollama + Groq API

Extends NEXUS AI with GitHub API capabilities: PRs, issues, commits, CI status.
"""

import json
import urllib.request
import urllib.parse
import urllib.error
from nexus_plugins.plugin_base import register_plugin

GITHUB_API = "https://api.github.com"


def _github_request(endpoint: str, token: str = "", method: str = "GET", data: dict = None) -> dict:
    """Make a GitHub API request."""
    url = f"{GITHUB_API}{endpoint}"
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "NexusAI/4.0",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    
    body = json.dumps(data).encode("utf-8") if data else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return {"error": f"GitHub API error {e.code}: {e.reason}"}
    except urllib.error.URLError as e:
        return {"error": f"GitHub connection error: {e.reason}"}


def github_list_issues(owner: str, repo: str, state: str = "open", token: str = "") -> str:
    """
    List issues for a GitHub repository.
    
    Use when: The user wants to see open issues in a GitHub repo.
    """
    result = _github_request(f"/repos/{owner}/{repo}/issues?state={state}", token)
    if isinstance(result, list):
        issues = [{"number": i["number"], "title": i["title"], "state": i["state"],
                    "user": i["user"]["login"], "comments": i["comments"]} for i in result[:20]]
        return json.dumps({"success": True, "result": issues, "error": None})
    return json.dumps({"success": False, "result": None, "error": result.get("error", "Unknown error")})


def github_list_prs(owner: str, repo: str, state: str = "open", token: str = "") -> str:
    """
    List pull requests for a GitHub repository.
    
    Use when: The user wants to see open PRs in a GitHub repo.
    """
    result = _github_request(f"/repos/{owner}/{repo}/pulls?state={state}", token)
    if isinstance(result, list):
        prs = [{"number": p["number"], "title": p["title"], "state": p["state"],
                 "user": p["user"]["login"], "draft": p.get("draft", False)} for p in result[:20]]
        return json.dumps({"success": True, "result": prs, "error": None})
    return json.dumps({"success": False, "result": None, "error": result.get("error", "Unknown error")})


def register():
    """Register this plugin with NEXUS AI."""
    return register_plugin(
        name="github-plugin",
        tool_func=github_list_issues,
        version="1.0.0",
        author="NEXUS AI Team",
        description="GitHub API: issues, PRs, and repository management",
        tags=["github", "development", "devops"],
        needs_network=True,
    )
"""
NEXUS AI v4.0 — Reference Plugin: Jira API operations.
Hardware: Intel i3 7th Gen · 12GB RAM · Ollama + Groq API

Extends NEXUS AI with Jira API capabilities: issues, sprints, epics.
"""

import json
import base64
import urllib.request
import urllib.error
from nexus_plugins.plugin_base import register_plugin


def _jira_request(domain: str, endpoint: str, email: str = "", api_token: str = "") -> dict:
    """Make a Jira API request."""
    url = f"https://{domain}.atlassian.net/rest/api/3{endpoint}"
    headers = {"Accept": "application/json", "User-Agent": "NexusAI/4.0"}
    
    if email and api_token:
        auth_str = f"{email}:{api_token}"
        headers["Authorization"] = f"Basic {base64.b64encode(auth_str.encode()).decode()}"
    
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return {"error": f"Jira API error {e.code}: {e.reason}"}
    except urllib.error.URLError as e:
        return {"error": f"Jira connection error: {e.reason}"}


def jira_search_issues(
    domain: str,
    jql: str,
    email: str = "",
    api_token: str = "",
    max_results: int = 20,
) -> str:
    """
    Search Jira issues using JQL.
    
    Use when: The user wants to find Jira issues, check their assigned tasks,
    or look up project status.
    
    Args:
        domain: Your Jira domain name (e.g., "mycompany" for mycompany.atlassian.net).
        jql: Jira Query Language string (e.g., 'project = "PROJ" AND status = "In Progress"').
        email: Your Jira account email (for basic auth).
        api_token: Jira API token (generate at https://id.atlassian.com/manage/api-tokens).
        max_results: Maximum results to return (1-50).
    """
    max_results = min(max(max_results, 1), 50)
    result = _jira_request(domain, f"/search?jql={urllib.parse.quote(jql)}&maxResults={max_results}", email, api_token)
    
    if "issues" in result:
        issues = []
        for issue in result["issues"]:
            fields = issue.get("fields", {})
            issues.append({
                "key": issue["key"],
                "summary": fields.get("summary", ""),
                "status": fields.get("status", {}).get("name", ""),
                "assignee": fields.get("assignee", {}).get("displayName", "Unassigned"),
                "priority": fields.get("priority", {}).get("name", ""),
                "type": fields.get("issuetype", {}).get("name", ""),
            })
        return json.dumps({"success": True, "result": issues, "error": None, "metadata": {"total": result.get("total", 0)}})
    return json.dumps({"success": False, "result": None, "error": result.get("error", "Unknown error")})


def register():
    """Register this plugin with NEXUS AI."""
    return register_plugin(
        name="jira-plugin",
        tool_func=jira_search_issues,
        version="1.0.0",
        author="NEXUS AI Team",
        description="Jira API: search and manage issues, sprints, and epics",
        tags=["jira", "project-management", "productivity"],
        needs_network=True,
    )
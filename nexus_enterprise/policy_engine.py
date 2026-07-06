"""
NEXUS AI v4.0 — Tool whitelist/blacklist policy engine per role/department.
Hardware: Intel i3 7th Gen · 12GB RAM · Ollama + Groq API

Enterprise feature: defines which tools each user/role can access.
Supports whitelist (only these tools) and blacklist (all except these) modes.
"""

import json
import logging
from typing import Dict, List, Optional, Set, Any
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from nexus_config.settings import get_settings, APP_ROOT

logger = logging.getLogger("nexus.enterprise.policy")


@dataclass
class PolicyRule:
    """A single policy rule for tool access control."""
    role: str
    mode: str = "whitelist"  # "whitelist" or "blacklist"
    tools: List[str] = field(default_factory=list)
    departments: List[str] = field(default_factory=list)


class PolicyEngine:
    """
    Enterprise policy engine for tool access control.
    
    Supports:
    - Role-based whitelist/blacklist
    - Department-level policies
    - Policy file persistence
    - Runtime policy reload
    """
    
    def __init__(self):
        self._settings = get_settings()
        self._policies: Dict[str, PolicyRule] = {}
        self._policy_file = APP_ROOT / "policies.json"
        self._load_policies()
    
    def is_tool_allowed(self, tool_name: str, role: str = "user", department: str = "") -> bool:
        """
        Check if a tool is allowed for the given role/department.
        
        Args:
            tool_name: Name of the tool to check.
            role: User role (e.g., "admin", "developer", "analyst").
            department: Department name (e.g., "engineering", "finance").
        
        Returns:
            True if the tool is allowed.
        """
        # Admin can access everything
        if role == "admin":
            return True
        
        # Check role-based policies
        for policy in self._policies.values():
            if policy.role == role or (department and department in policy.departments):
                if policy.mode == "whitelist":
                    if tool_name not in policy.tools:
                        return False
                elif policy.mode == "blacklist":
                    if tool_name in policy.tools:
                        return False
        
        return True
    
    def add_policy(self, rule: PolicyRule) -> None:
        """Add or update a policy rule."""
        self._policies[rule.role] = rule
        self._save_policies()
    
    def remove_policy(self, role: str) -> None:
        """Remove a policy rule by role."""
        self._policies.pop(role, None)
        self._save_policies()
    
    def get_allowed_tools(self, role: str = "user", department: str = "") -> List[str]:
        """Get list of allowed tools for a role/department."""
        from nexus_tools.registry import get_tool_registry
        registry = get_tool_registry()
        all_tools = list(registry._tools.keys())
        return [t for t in all_tools if self.is_tool_allowed(t, role, department)]
    
    def _load_policies(self) -> None:
        """Load policies from disk."""
        try:
            if self._policy_file.exists():
                data = json.loads(self._policy_file.read_text(encoding="utf-8"))
                for item in data:
                    rule = PolicyRule(**item)
                    self._policies[rule.role] = rule
        except Exception as e:
            logger.debug(f"Could not load policies: {e}")
    
    def _save_policies(self) -> None:
        """Save policies to disk."""
        try:
            data = []
            for rule in self._policies.values():
                data.append({
                    "role": rule.role,
                    "mode": rule.mode,
                    "tools": rule.tools,
                    "departments": rule.departments,
                })
            self._policy_file.write_text(
                json.dumps(data, indent=2), encoding="utf-8"
            )
        except Exception as e:
            logger.error(f"Failed to save policies: {e}")


@lru_cache(maxsize=1)
def get_policy_engine() -> PolicyEngine:
    """Return the singleton PolicyEngine instance."""
    return PolicyEngine()
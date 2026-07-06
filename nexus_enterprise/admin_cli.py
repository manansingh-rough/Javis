"""
NEXUS AI v4.0 — nexus-admin CLI for user management and policy config.
Hardware: Intel i3 7th Gen · 12GB RAM · Ollama + Groq API

Enterprise CLI for managing users, policies, and system configuration.
"""

import logging
from typing import List, Optional
from functools import lru_cache

from nexus_enterprise.policy_engine import PolicyEngine, get_policy_engine, PolicyRule

logger = logging.getLogger("nexus.enterprise.admin")


class AdminCLI:
    """
    Enterprise admin CLI for system management.
    
    Provides administrative commands for:
    - User management (add/remove/list)
    - Policy management (add/remove/list)
    - System health and monitoring
    """
    
    def __init__(self):
        self._policy_engine: PolicyEngine = get_policy_engine()
    
    def add_policy(self, role: str, tools: List[str], mode: str = "whitelist", departments: Optional[List[str]] = None) -> None:
        """Add a policy rule."""
        rule = PolicyRule(role=role, mode=mode, tools=tools, departments=departments or [])
        self._policy_engine.add_policy(rule)
        logger.info("Policy added for role: %s", role)
    
    def remove_policy(self, role: str) -> None:
        """Remove a policy rule."""
        self._policy_engine.remove_policy(role)
        logger.info("Policy removed for role: %s", role)
    
    def list_policies(self) -> List[dict]:
        """List all policy rules."""
        return [
            {"role": r.role, "mode": r.mode, "tools": r.tools, "departments": r.departments}
            for r in self._policy_engine._policies.values()
        ]
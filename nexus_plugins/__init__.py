"""
NEXUS AI v4.0 — Plugins package init.
Hardware: Intel i3 7th Gen · 12GB RAM · Ollama + Groq API

Bundled reference plugins for extending NEXUS AI capabilities.
Each plugin registers tools with the ToolRegistry using the plugin_base contract.
"""

from nexus_plugins.plugin_base import PluginMetadata, register_plugin

__all__ = ["PluginMetadata", "register_plugin"]
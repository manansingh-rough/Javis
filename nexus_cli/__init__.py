"""
NEXUS AI v4.0 — CLI Companion Package Init
Hardware: Intel i3 7th Gen · 12GB RAM · Ollama + Groq API

CLI tools for running, managing, and configuring NEXUS AI.
"""

from nexus_cli.cli import cli
from nexus_cli.installer import PluginInstaller

__all__ = [
    "cli",
    "PluginInstaller",
]
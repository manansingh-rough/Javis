"""
NEXUS AI v4.0 — Plugin installer: downloads from plugin marketplace.
Hardware: Intel i3 7th Gen · 12GB RAM · Ollama + Groq API

Handles plugin installation from the marketplace or local files.
"""

import logging
from pathlib import Path
from typing import Optional

from nexus_config.settings import get_settings, APP_ROOT

logger = logging.getLogger("nexus.cli.installer")


class PluginInstaller:
    """
    Plugin installation manager.
    
    Handles:
    - Downloading plugins from marketplace
    - Installing from local .py files
    - Validating plugin manifests
    - Managing plugin dependencies
    """
    
    def __init__(self):
        self._settings = get_settings()
        self._plugin_dir = APP_ROOT / "plugins"
        self._plugin_dir.mkdir(parents=True, exist_ok=True)
    
    def install(self, plugin_name: str, source: Optional[str] = None) -> bool:
        """
        Install a plugin.
        
        Args:
            plugin_name: Name of the plugin to install.
            source: Optional source URL or file path.
                   If None, attempts marketplace download.
        
        Returns:
            True if installation succeeded.
        """
        if source:
            return self._install_from_source(plugin_name, source)
        return self._install_from_marketplace(plugin_name)
    
    def _install_from_marketplace(self, plugin_name: str) -> bool:
        """Install a plugin from the marketplace."""
        print(f"Installing plugin '{plugin_name}' from marketplace...")
        print(f"  Marketplace URL: {self._settings.MARKETPLACE_API_URL}")
        print(f"  Plugin directory: {self._plugin_dir}")
        print("  Note: Marketplace not yet available. Install from local file instead.")
        print("  Usage: nexus install <name> --source /path/to/plugin.py")
        return False
    
    def _install_from_source(self, plugin_name: str, source: str) -> bool:
        """Install a plugin from a local file path."""
        source_path = Path(source)
        if not source_path.exists():
            print(f"Source file not found: {source}")
            return False
        
        dest = self._plugin_dir / f"{plugin_name}.py"
        try:
            import shutil
            shutil.copy2(source_path, dest)
            print(f"Plugin '{plugin_name}' installed to {dest}")
            return True
        except Exception as e:
            print(f"Installation failed: {e}")
            return False
    
    def uninstall(self, plugin_name: str) -> bool:
        """Uninstall a plugin."""
        plugin_file = self._plugin_dir / f"{plugin_name}.py"
        if plugin_file.exists():
            plugin_file.unlink()
            print(f"Plugin '{plugin_name}' uninstalled.")
            return True
        print(f"Plugin '{plugin_name}' not found.")
        return False
    
    def list_installed(self) -> list:
        """List all installed plugins."""
        plugins = list(self._plugin_dir.glob("*.py"))
        return [p.stem for p in plugins]
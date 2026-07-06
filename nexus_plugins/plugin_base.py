"""
NEXUS AI v4.0 — Plugin base: PluginMetadata dataclass + SDK documentation.
Hardware: Intel i3 7th Gen · 12GB RAM · Ollama + Groq API

Defines the plugin API contract for third-party developers.
A plugin developer needs to know NOTHING else about NEXUS AI internals
except what's defined in this module.
"""

import json
from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict, Any, Callable


@dataclass
class PluginMetadata:
    """
    Plugin metadata for marketplace listing and dependency resolution.
    
    Attributes:
        name: Short unique identifier (e.g., "my-nexus-plugin").
        version: Semantic version string (e.g., "1.2.3").
        author: Developer name or organization.
        description: One-sentence description for marketplace listing.
        tags: List of category keywords for discoverability.
        homepage: URL to plugin source repository or documentation.
        license: SPDX license identifier (e.g., "MIT", "Apache-2.0").
        min_nexus_version: Minimum NEXUS AI version required.
        price: Monthly price in USD (0.0 = free).
        python_requires: Python version constraint (e.g., ">=3.10").
        plugin_dependencies: List of other plugin names this depends on.
        needs_network: Whether plugin requires internet access.
        needs_filesystem: Whether plugin requires file system access.
        needs_subprocess: Whether plugin requires subprocess execution.
        needs_admin: Whether plugin requires admin/root privileges.
    """
    name: str
    version: str = "1.0.0"
    author: str = "Unknown"
    description: str = ""
    tags: List[str] = field(default_factory=list)
    homepage: str = ""
    license: str = "MIT"
    min_nexus_version: str = "4.0.0"
    price: float = 0.0
    python_requires: str = ">=3.10"
    plugin_dependencies: List[str] = field(default_factory=list)
    needs_network: bool = False
    needs_filesystem: bool = False
    needs_subprocess: bool = False
    needs_admin: bool = False


class PluginRegistry:
    """
    Internal registry for loaded plugins.
    
    Note: Plugin developers do NOT need to use this class directly.
    Use the register_plugin() function instead.
    """
    _plugins: Dict[str, PluginMetadata] = {}
    _tools: Dict[str, Callable] = {}
    
    @classmethod
    def register(cls, metadata: PluginMetadata, tool_func: Callable) -> None:
        """Register a plugin and its tool function."""
        cls._plugins[metadata.name] = metadata
        cls._tools[metadata.name] = tool_func
    
    @classmethod
    def get_metadata(cls, name: str) -> Optional[PluginMetadata]:
        """Get plugin metadata by name."""
        return cls._plugins.get(name)
    
    @classmethod
    def list_plugins(cls) -> List[Dict[str, Any]]:
        """List all registered plugins."""
        return [asdict(m) for m in cls._plugins.values()]
    
    @classmethod
    def count(cls) -> int:
        """Return the number of registered plugins."""
        return len(cls._plugins)


def register_plugin(
    name: str,
    tool_func: Callable,
    version: str = "1.0.0",
    author: str = "Unknown",
    description: str = "",
    tags: Optional[List[str]] = None,
    needs_network: bool = False,
    needs_filesystem: bool = False,
    needs_subprocess: bool = False,
    needs_admin: bool = False,
) -> PluginMetadata:
    """
    Register a plugin with the system.
    
    This is the MAIN entry point for plugin developers. Call this from your
    plugin module's register() function to register your tool.
    
    Args:
        name: Short unique identifier for your plugin.
        tool_func: The @tool-decorated function to register.
        version: Semantic version string.
        author: Your name or organization.
        description: One-sentence description of what your plugin does.
        tags: List of category keywords.
        needs_network: Whether your tool needs internet access.
        needs_filesystem: Whether your tool needs file system access.
        needs_subprocess: Whether your tool needs subprocess execution.
        needs_admin: Whether your tool needs admin/root privileges.
    
    Returns:
        PluginMetadata instance for the registered plugin.
    
    Example:
        ```python
        # my_plugin.py
        from langchain_core.tools import tool
        from nexus_plugins.plugin_base import register_plugin
        
        @tool
        def my_tool(param: str) -> str:
            \"\"\"Does something useful.\"\"\"
            return json.dumps({"success": True, "result": f"Processed: {param}"})
        
        def register():
            return register_plugin(
                name="my-nexus-plugin",
                tool_func=my_tool,
                version="1.0.0",
                author="Jane Developer",
                description="Does something useful",
                tags=["productivity", "automation"],
            )
        ```
    """
    metadata = PluginMetadata(
        name=name,
        version=version,
        author=author,
        description=description,
        tags=tags or [],
        needs_network=needs_network,
        needs_filesystem=needs_filesystem,
        needs_subprocess=needs_subprocess,
        needs_admin=needs_admin,
    )
    PluginRegistry.register(metadata, tool_func)
    return metadata
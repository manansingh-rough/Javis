"""
NEXUS AI v4.0 — Plugin load/reload/security tests.
Hardware: Intel i3 7th Gen · 12GB RAM · Ollama + Groq API

Covers:
1. PluginMetadata dataclass creation with defaults
2. PluginMetadata with all fields
3. register_plugin function
4. PluginRegistry.get_metadata lookup
5. PluginRegistry.list_plugins
6. PluginRegistry.count
7. Plugin security — needs_network, needs_filesystem flags
8. Plugin metadata serialization
9. Plugin dependency checking
"""

import pytest
import json
from unittest.mock import MagicMock, patch


class TestPluginMetadata:
    """Tests for PluginMetadata dataclass."""

    def test_plugin_metadata_defaults(self):
        """Test that PluginMetadata creates with defaults."""
        from nexus_plugins.plugin_base import PluginMetadata
        meta = PluginMetadata(name="test-plugin")
        assert meta.name == "test-plugin"
        assert meta.version == "1.0.0"
        assert meta.author == "Unknown"
        assert meta.price == 0.0
        assert meta.min_nexus_version == "4.0.0"
        assert meta.needs_network is False
        assert meta.needs_filesystem is False
        assert meta.needs_subprocess is False
        assert meta.needs_admin is False

    def test_plugin_metadata_all_fields(self):
        """Test PluginMetadata with all fields specified."""
        from nexus_plugins.plugin_base import PluginMetadata
        meta = PluginMetadata(
            name="my-plugin",
            version="2.1.0",
            author="Jane Developer",
            description="Does something useful",
            tags=["productivity", "automation"],
            homepage="https://github.com/jane/my-plugin",
            license="Apache-2.0",
            min_nexus_version="4.0.0",
            price=5.99,
            python_requires=">=3.11",
            plugin_dependencies=["other-plugin"],
            needs_network=True,
            needs_filesystem=True,
            needs_subprocess=False,
            needs_admin=False,
        )
        assert meta.name == "my-plugin"
        assert meta.version == "2.1.0"
        assert meta.author == "Jane Developer"
        assert meta.description == "Does something useful"
        assert "productivity" in meta.tags
        assert meta.needs_network is True
        assert meta.needs_filesystem is True
        assert meta.price == 5.99

    def test_plugin_metadata_needs_admin_true(self):
        """Test plugin that requires admin privileges."""
        from nexus_plugins.plugin_base import PluginMetadata
        meta = PluginMetadata(
            name="system-plugin",
            needs_admin=True,
            description="Requires admin for system config",
        )
        assert meta.needs_admin is True


class TestPluginRegistration:
    """Tests for plugin registration."""

    def test_register_plugin_function(self):
        """Test that register_plugin creates and registers metadata."""
        from nexus_plugins.plugin_base import register_plugin, PluginRegistry

        # Clear registry for clean test
        PluginRegistry._plugins.clear()
        PluginRegistry._tools.clear()

        def my_tool(param: str) -> str:
            return '{"success": true}'

        meta = register_plugin(
            name="my-nexus-plugin",
            tool_func=my_tool,
            version="1.2.3",
            author="Test Author",
            description="A test plugin",
            tags=["test"],
            needs_network=True,
        )

        assert meta.name == "my-nexus-plugin"
        assert meta.version == "1.2.3"
        assert meta.author == "Test Author"

    def test_plugin_registry_get_metadata(self):
        """Test getting metadata from registry."""
        from nexus_plugins.plugin_base import register_plugin, PluginRegistry

        PluginRegistry._plugins.clear()
        PluginRegistry._tools.clear()

        def my_tool(x: str) -> str:
            return x

        register_plugin(name="test-plugin", tool_func=my_tool)
        meta = PluginRegistry.get_metadata("test-plugin")
        assert meta is not None
        assert meta.name == "test-plugin"
        assert meta.author == "Unknown"

    def test_plugin_registry_get_missing(self):
        """Test that missing plugin returns None."""
        from nexus_plugins.plugin_base import PluginRegistry
        meta = PluginRegistry.get_metadata("nonexistent-plugin")
        assert meta is None

    def test_plugin_registry_list_plugins(self):
        """Test listing all registered plugins."""
        from nexus_plugins.plugin_base import register_plugin, PluginRegistry

        PluginRegistry._plugins.clear()
        PluginRegistry._tools.clear()

        def tool1(x: str) -> str: return x
        def tool2(x: str) -> str: return x

        register_plugin(name="plugin-a", tool_func=tool1)
        register_plugin(name="plugin-b", tool_func=tool2)

        plugins = PluginRegistry.list_plugins()
        assert len(plugins) == 2
        names = [p["name"] for p in plugins]
        assert "plugin-a" in names
        assert "plugin-b" in names

    def test_plugin_registry_count(self):
        """Test counting registered plugins."""
        from nexus_plugins.plugin_base import register_plugin, PluginRegistry

        PluginRegistry._plugins.clear()
        PluginRegistry._tools.clear()

        def tool(x: str) -> str: return x
        register_plugin(name="count-test", tool_func=tool)
        assert PluginRegistry.count() == 1


class TestPluginSecurity:
    """Tests for plugin security flags."""

    def test_plugin_security_defaults_safe(self):
        """Test that default plugin is safe (no permissions needed)."""
        from nexus_plugins.plugin_base import PluginMetadata
        meta = PluginMetadata(name="safe-plugin")
        assert meta.needs_network is False
        assert meta.needs_filesystem is False
        assert meta.needs_subprocess is False
        assert meta.needs_admin is False

    def test_plugin_with_network_permission(self):
        """Test plugin that declares network access."""
        from nexus_plugins.plugin_base import PluginMetadata
        meta = PluginMetadata(name="web-plugin", needs_network=True)
        assert meta.needs_network is True

    def test_plugin_filesystem_permission(self):
        """Test plugin that declares filesystem access."""
        from nexus_plugins.plugin_base import PluginMetadata
        meta = PluginMetadata(name="file-plugin", needs_filesystem=True)
        assert meta.needs_filesystem is True


class TestPluginSerialization:
    """Tests for plugin serialization."""

    def test_plugin_metadata_asdict(self):
        """Test converting metadata to dict."""
        from nexus_plugins.plugin_base import PluginMetadata
        from dataclasses import asdict
        meta = PluginMetadata(
            name="serialize-test",
            version="1.0.0",
            author="Tester",
            tags=["test"],
        )
        d = asdict(meta)
        assert d["name"] == "serialize-test"
        assert d["author"] == "Tester"
        assert "test" in d["tags"]

    def test_plugin_metadata_json_serializable(self):
        """Test that metadata can be JSON-serialized."""
        from nexus_plugins.plugin_base import PluginMetadata
        from dataclasses import asdict
        meta = PluginMetadata(name="json-test", description="JSON safe")
        d = asdict(meta)
        json_str = json.dumps(d)
        assert json_str is not None
        assert "json-test" in json_str


class TestPluginDependencies:
    """Tests for plugin dependency resolution."""

    def test_plugin_no_dependencies(self):
        """Test plugin with no dependencies."""
        from nexus_plugins.plugin_base import PluginMetadata
        meta = PluginMetadata(name="standalone")
        assert meta.plugin_dependencies == []

    def test_plugin_with_dependencies(self):
        """Test plugin with dependencies on other plugins."""
        from nexus_plugins.plugin_base import PluginMetadata
        meta = PluginMetadata(
            name="dependent-plugin",
            plugin_dependencies=["base-plugin", "auth-plugin"],
        )
        assert len(meta.plugin_dependencies) == 2
        assert "base-plugin" in meta.plugin_dependencies
        assert "auth-plugin" in meta.plugin_dependencies
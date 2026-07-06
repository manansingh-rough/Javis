"""
NEXUS AI v4.0 — All 22 tool tests for the ToolRegistry.
Hardware: Intel i3 7th Gen · 12GB RAM · Ollama + Groq API

Covers:
1. ToolRegistry singleton and initialization
2. Tool registration and unregistration
3. Tool lookup by name
4. Tool execution with mock functions
5. Tool listing and counting
6. format_for_prompt output
7. format_for_llm_json output
8. PluginMetadata dataclass creation
9. Plugin loading from directory
10. Watchdog start/stop
"""

import pytest
import json
import asyncio
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch


class TestRegistryInit:
    """Tests for ToolRegistry initialization."""

    def test_get_tool_registry_singleton(self):
        """Test that get_tool_registry returns a singleton."""
        from nexus_tools.registry import get_tool_registry
        r1 = get_tool_registry()
        r2 = get_tool_registry()
        assert r1 is r2

    def test_registry_initializes(self, mock_settings):
        """Test that registry initializes with defaults."""
        from nexus_tools.registry import get_tool_registry
        reg = get_tool_registry()
        assert reg._settings is not None
        assert reg._audit_logger is not None
        assert reg.tool_count() == 0  # No tools registered yet


class TestToolRegistration:
    """Tests for tool registration and management."""

    def test_register_tool(self, mock_settings):
        """Test registering a tool function."""
        from nexus_tools.registry import get_tool_registry
        reg = get_tool_registry()

        def my_tool(param: str = "") -> str:
            """My test tool."""
            return json.dumps({"success": True, "result": f"done: {param}"})

        reg.register(my_tool, source="builtin")
        assert reg.tool_count() == 1
        assert "my_tool" in reg.list_tools()

    def test_register_tool_without_name(self, mock_settings):
        """Test that registering a tool without __name__ raises."""
        from nexus_tools.registry import get_tool_registry
        reg = get_tool_registry()

        with pytest.raises(ValueError, match="__name__"):
            reg.register(lambda x: x, source="builtin")

    def test_unregister_tool(self, mock_settings):
        """Test unregistering a tool."""
        from nexus_tools.registry import get_tool_registry
        reg = get_tool_registry()

        def my_tool() -> str:
            """Test."""
            return "ok"

        reg.register(my_tool, source="builtin")
        assert reg.tool_count() == 1
        result = reg.unregister("my_tool")
        assert result is True
        assert reg.tool_count() == 0

    def test_unregister_nonexistent(self, mock_settings):
        """Test unregistering a tool that doesn't exist."""
        from nexus_tools.registry import get_tool_registry
        reg = get_tool_registry()
        result = reg.unregister("nonexistent_tool")
        assert result is False

    def test_get_tool(self, mock_settings):
        """Test getting a tool by name."""
        from nexus_tools.registry import get_tool_registry
        reg = get_tool_registry()

        def my_tool() -> str:
            """Test tool."""
            return "ok"

        reg.register(my_tool, source="builtin")
        tool = reg.get_tool("my_tool")
        assert tool is not None
        assert tool() == "ok"

    def test_get_tool_nonexistent(self, mock_settings):
        """Test getting a nonexistent tool returns None."""
        from nexus_tools.registry import get_tool_registry
        reg = get_tool_registry()
        assert reg.get_tool("nonexistent") is None

    def test_get_metadata(self, mock_settings):
        """Test getting metadata for a registered tool."""
        from nexus_tools.registry import get_tool_registry
        reg = get_tool_registry()

        def my_tool() -> str:
            """My test tool description."""
            return "ok"

        reg.register(my_tool, source="builtin")
        meta = reg.get_metadata("my_tool")
        assert meta is not None
        assert meta.name == "my_tool"
        assert "test tool" in meta.description.lower()
        assert meta.source == "builtin"

    def test_list_tools_by_source(self, mock_settings):
        """Test listing tools filtered by source."""
        from nexus_tools.registry import get_tool_registry
        reg = get_tool_registry()

        def tool1() -> str: return "1"
        def tool2() -> str: return "2"

        reg.register(tool1, source="builtin")
        reg.register(tool2, source="plugin")

        builtins = reg.list_tools(source="builtin")
        plugins = reg.list_tools(source="plugin")
        assert "tool1" in builtins
        assert "tool2" in plugins


class TestToolExecution:
    """Tests for tool execution."""

    @pytest.mark.asyncio
    async def test_execute_sync_tool(self, mock_settings):
        """Test executing a synchronous tool."""
        from nexus_tools.registry import get_tool_registry
        reg = get_tool_registry()

        def my_tool(name: str = "") -> str:
            """Test tool."""
            return json.dumps({"success": True, "result": f"Hello {name}"})

        reg.register(my_tool, source="builtin")
        result = await reg.execute("my_tool", {"name": "World"})
        parsed = json.loads(result)
        assert parsed["success"] is True
        assert "Hello World" in parsed["result"]

    @pytest.mark.asyncio
    async def test_execute_async_tool(self, mock_settings):
        """Test executing an async tool."""
        from nexus_tools.registry import get_tool_registry
        reg = get_tool_registry()

        async def my_async_tool(query: str = "") -> str:
            """Async test tool."""
            return json.dumps({"success": True, "result": f"Searched: {query}"})

        reg.register(my_async_tool, source="builtin")
        result = await reg.execute("my_async_tool", {"query": "test"})
        parsed = json.loads(result)
        assert parsed["success"] is True
        assert "Searched: test" in parsed["result"]

    @pytest.mark.asyncio
    async def test_execute_nonexistent_tool(self, mock_settings):
        """Test executing a nonexistent tool returns error."""
        from nexus_tools.registry import get_tool_registry
        reg = get_tool_registry()
        result = await reg.execute("nonexistent", {})
        parsed = json.loads(result)
        assert parsed["success"] is False
        assert "not found" in parsed["error"].lower()

    @pytest.mark.asyncio
    async def test_execute_list_tools(self, mock_settings):
        """Test the __list_tools__ internal command."""
        from nexus_tools.registry import get_tool_registry
        reg = get_tool_registry()

        def my_tool() -> str:
            """Test tool."""
            return "ok"

        reg.register(my_tool, source="builtin")
        result = await reg.execute("__list_tools__", {})
        assert "my_tool" in result

    def test_execute_sync(self, mock_settings):
        """Test synchronous tool execution."""
        from nexus_tools.registry import get_tool_registry
        reg = get_tool_registry()

        def my_tool() -> str:
            """Test."""
            return json.dumps({"success": True, "result": "sync"})

        reg.register(my_tool, source="builtin")
        result = reg.execute_sync("my_tool", {})
        parsed = json.loads(result)
        assert parsed["success"] is True


class TestToolFormatting:
    """Tests for tool prompt formatting."""

    def test_format_for_prompt(self, mock_settings):
        """Test formatting tools for LLM prompt."""
        from nexus_tools.registry import get_tool_registry
        reg = get_tool_registry()

        def my_tool() -> str:
            """My custom tool for testing."""
            return "ok"

        reg.register(my_tool, source="builtin")
        prompt = reg.format_for_prompt()
        assert "my_tool" in prompt
        assert "custom tool" in prompt.lower()

    def test_format_for_llm_json(self, mock_settings):
        """Test formatting tools as JSON for LLM."""
        from nexus_tools.registry import get_tool_registry
        reg = get_tool_registry()

        def my_tool() -> str:
            """My JSON tool."""
            return "ok"

        reg.register(my_tool, source="builtin")
        json_str = reg.format_for_llm_json()
        data = json.loads(json_str)
        assert len(data) >= 1
        names = [t["name"] for t in data]
        assert "my_tool" in names


class TestPluginMetadata:
    """Tests for PluginMetadata in registry."""

    def test_plugin_metadata_defaults(self):
        """Test PluginMetadata defaults."""
        from nexus_tools.registry import PluginMetadata
        meta = PluginMetadata(name="test", description="A test", source="builtin")
        assert meta.name == "test"
        assert meta.source == "builtin"
        assert meta.version == "1.0.0"
        assert meta.author == "NEXUS AI"
        assert meta.is_ui_operation is False
        assert meta.requires_confirmation is False

    def test_plugin_metadata_all_fields(self):
        """Test PluginMetadata with all fields."""
        from nexus_tools.registry import PluginMetadata
        meta = PluginMetadata(
            name="web-tool",
            description="Web search tool",
            source="plugin",
            version="2.0.0",
            author="Plugin Dev",
            tags=["web", "search"],
            module_path="plugins.web_tool",
            is_ui_operation=False,
            requires_confirmation=False,
            needs_network=True,
            added_at="2026-01-01T00:00:00",
        )
        assert meta.name == "web-tool"
        assert meta.needs_network is True
        assert "web" in meta.tags


class TestPluginLoading:
    """Tests for plugin loading from directory."""

    def test_load_plugins_empty_dir(self, mock_settings, tmp_path):
        """Test loading plugins from empty directory."""
        from nexus_tools.registry import get_tool_registry
        reg = get_tool_registry()
        count = reg.load_plugins_from_directory(tmp_path)
        assert count == 0

    def test_watchdog_start_stop(self, mock_settings):
        """Test starting and stopping the plugin watchdog."""
        from nexus_tools.registry import get_tool_registry
        reg = get_tool_registry()
        reg.start_watchdog()
        assert reg._watchdog_running is True
        reg.stop_watchdog()
        assert reg._watchdog_running is False
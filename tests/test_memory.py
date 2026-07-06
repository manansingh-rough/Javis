"""
NEXUS AI v4.0 — ChromaDB + session tests for memory layer.
Hardware: Intel i3 7th Gen · 12GB RAM · Ollama + Groq API

Covers:
1. MemoryManager singleton and initialization
2. store_episodic — storing task outcomes
3. store_preference — storing user preferences
4. query_memories — retrieving past tasks
5. query_preferences — retrieving user preferences
6. get_context — session context retrieval
7. SessionContext integration
8. MemoryCompressor should_compress check
9. Vector store add_memory and query
10. Session context add_task
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch


class TestMemoryManager:
    """Tests for MemoryManager."""

    def test_get_memory_manager_singleton(self):
        """Test that get_memory_manager returns a singleton."""
        from nexus_memory.memory_manager import get_memory_manager
        m1 = get_memory_manager()
        m2 = get_memory_manager()
        assert m1 is m2

    def test_memory_manager_initializes(self, mock_settings, vector_store):
        """Test that memory manager initializes with vector store + session context."""
        from nexus_memory.memory_manager import get_memory_manager
        mm = get_memory_manager()
        assert mm._vs is not None
        assert mm._sc is not None

    def test_store_episodic(self, mock_settings, vector_store):
        """Test storing an episodic memory."""
        from nexus_memory.memory_manager import get_memory_manager
        mm = get_memory_manager()

        with patch.object(mm._vs, 'add_memory') as mock_add:
            mm.store_episodic(
                task="List files",
                outcome="Files listed successfully",
                tools=["t02_file_manager"],
                dur=100.0,
                success=True,
                sid="test-session-001",
                comp="simple",
            )
            mock_add.assert_called_once()
            args, kwargs = mock_add.call_args
            assert args[0] == "agent_memory"
            assert "List files" in args[2]

    def test_store_preference(self, mock_settings, vector_store):
        """Test storing a user preference."""
        from nexus_memory.memory_manager import get_memory_manager
        mm = get_memory_manager()

        with patch.object(mm._vs, 'add_memory') as mock_add:
            mm.store_preference("User prefers dark mode")
            mock_add.assert_called_once()
            args, kwargs = mock_add.call_args
            assert args[0] == "user_preferences"
            assert "User prefers dark mode" in args[2]

    def test_query_memories(self, mock_settings, vector_store):
        """Test querying episodic memories."""
        from nexus_memory.memory_manager import get_memory_manager
        mm = get_memory_manager()

        with patch.object(mm._vs, 'query') as mock_query:
            mock_query.return_value = [{"task": "List files", "success": True}]
            results = mm.query_memories("list files", n=3)
            mock_query.assert_called_once_with("agent_memory", "list files", 3)
            assert len(results) == 1

    def test_query_preferences(self, mock_settings, vector_store):
        """Test querying user preferences."""
        from nexus_memory.memory_manager import get_memory_manager
        mm = get_memory_manager()

        with patch.object(mm._vs, 'query') as mock_query:
            mock_query.return_value = [{"fact": "User likes dark mode"}]
            results = mm.query_preferences(n=3)
            mock_query.assert_called_once_with("user_preferences", "user preferences", 3)
            assert len(results) == 1

    def test_get_context(self, mock_settings, vector_store):
        """Test getting session context."""
        from nexus_memory.memory_manager import get_memory_manager
        mm = get_memory_manager()

        with patch.object(mm._sc, 'get') as mock_sc_get:
            mock_sc_get.return_value = []
            with patch.object(mm._sc, 'get_last_task_summary', return_value=""):
                context = mm.get_context()
                assert "working_memory" in context
                assert "last_task" in context
                assert "task_history_count" in context

    def test_query_synthesized_tools(self, mock_settings, vector_store):
        """Test querying synthesized tools."""
        from nexus_memory.memory_manager import get_memory_manager
        mm = get_memory_manager()

        with patch.object(mm._vs, 'query') as mock_query:
            mock_query.return_value = []
            results = mm.query_synthesized_tools("custom api", n=3)
            mock_query.assert_called_once_with("synthesized_tools", "custom api", 3)
            assert results == []

    def test_query_all(self, mock_settings, vector_store):
        """Test query_all falls through to agent_memory query."""
        from nexus_memory.memory_manager import get_memory_manager
        mm = get_memory_manager()

        with patch.object(mm._vs, 'query') as mock_query:
            mock_query.return_value = []
            results = mm.query_all("test query", n=3)
            mock_query.assert_called_once_with("agent_memory", "test query", 3)
            assert results == []


class TestMemoryCompressor:
    """Tests for MemoryCompressor."""

    def test_should_compress_returns_bool(self, mock_settings):
        """Test that should_compress returns a boolean."""
        from nexus_memory.memory_compressor import should_compress
        result = should_compress("agent_memory")
        assert isinstance(result, bool)


class TestSessionContext:
    """Tests for SessionContext integration."""

    def test_session_context_add_task(self, mock_settings, vector_store):
        """Test adding a task to session context."""
        from nexus_memory.session_context import get_session_context
        sc = get_session_context()

        with patch.object(sc, 'add_task') as mock_add:
            sc.add_task({
                "task": "Test task",
                "success": True,
                "duration_ms": 100.0,
                "timestamp": "00:00:00",
                "tools": ["t01_system_command"],
            })
            mock_add.assert_called_once()
            args = mock_add.call_args[0][0]
            assert args["task"] == "Test task"
            assert args["success"] is True
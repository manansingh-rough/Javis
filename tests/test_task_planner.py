"""
NEXUS AI v4.0 — DAG decomposition tests for TaskPlanner.
Hardware: Intel i3 7th Gen · 12GB RAM · Ollama + Groq API

Covers:
1. TaskPlanner singleton and initialization
2. Single-node DAG creation for simple commands
3. DAG plan with multiple nodes
4. Critical path computation — simple linear
5. Critical path computation — parallel branches
6. Critical path computation — diamond dependency
7. Parallel branch counting
8. UI_AUTOMATION_LOCK existence
9. DAGNode typed dict creation
10. DAGPlan dataclass creation
"""

import pytest
import json
from unittest.mock import MagicMock, AsyncMock, patch

from nexus_brain.agent_state import DAGNode


class TestTaskPlannerInit:
    """Tests for TaskPlanner initialization."""

    def test_get_task_planner_singleton(self):
        """Test that get_task_planner returns a singleton."""
        from nexus_brain.task_planner import get_task_planner
        p1 = get_task_planner()
        p2 = get_task_planner()
        assert p1 is p2

    def test_task_planner_initializes(self, mock_settings):
        """Test that task planner initializes with settings."""
        from nexus_brain.task_planner import get_task_planner
        planner = get_task_planner()
        assert planner._settings is not None
        assert planner._max_parallel >= 1

    def test_ui_automation_lock_exists(self):
        """Test that UI_AUTOMATION_LOCK is an asyncio Lock."""
        from nexus_brain.task_planner import UI_AUTOMATION_LOCK
        import asyncio
        assert isinstance(UI_AUTOMATION_LOCK, asyncio.Lock)

    def test_cpu_worker_pool(self):
        """Test that _get_cpu_pool returns a ThreadPoolExecutor."""
        from nexus_brain.task_planner import _get_cpu_pool
        pool = _get_cpu_pool()
        assert pool is not None


class TestSingleNode:
    """Tests for single-node DAG creation."""

    def test_make_single_node(self, mock_settings):
        """Test that _make_single_node creates a valid node."""
        from nexus_brain.task_planner import get_task_planner
        planner = get_task_planner()
        node = planner._make_single_node("Open VS Code")
        assert node["id"] == "n0"
        assert node["description"] == "Open VS Code"
        assert node["tool"] is None
        assert node["status"] == "pending"
        assert node["can_fail_safely"] is False
        assert node["estimated_duration_ms"] == 5000


class TestCriticalPath:
    """Tests for critical path computation."""

    def test_linear_critical_path(self, mock_settings):
        """Test critical path for a linear DAG."""
        from nexus_brain.task_planner import get_task_planner
        planner = get_task_planner()

        nodes = [
            DAGNode(id="n0", description="Step 1", tool="t1", tool_input={},
                    dependencies=[], status="pending", result=None, error=None,
                    can_fail_safely=False, estimated_duration_ms=1000),
            DAGNode(id="n1", description="Step 2", tool="t2", tool_input={},
                    dependencies=["n0"], status="pending", result=None, error=None,
                    can_fail_safely=False, estimated_duration_ms=2000),
            DAGNode(id="n2", description="Step 3", tool="t3", tool_input={},
                    dependencies=["n1"], status="pending", result=None, error=None,
                    can_fail_safely=False, estimated_duration_ms=3000),
        ]

        path = planner._compute_critical_path(nodes)
        assert path == ["n0", "n1", "n2"]

    def test_parallel_critical_path(self, mock_settings):
        """Test critical path for a DAG with parallel branches."""
        from nexus_brain.task_planner import get_task_planner
        planner = get_task_planner()

        nodes = [
            DAGNode(id="n0", description="Start", tool="t1", tool_input={},
                    dependencies=[], status="pending", result=None, error=None,
                    can_fail_safely=False, estimated_duration_ms=500),
            DAGNode(id="n1", description="Branch A (long)", tool="t2", tool_input={},
                    dependencies=["n0"], status="pending", result=None, error=None,
                    can_fail_safely=False, estimated_duration_ms=5000),
            DAGNode(id="n2", description="Branch B (short)", tool="t3", tool_input={},
                    dependencies=["n0"], status="pending", result=None, error=None,
                    can_fail_safely=False, estimated_duration_ms=1000),
            DAGNode(id="n3", description="Merge", tool="t4", tool_input={},
                    dependencies=["n1", "n2"], status="pending", result=None, error=None,
                    can_fail_safely=False, estimated_duration_ms=500),
        ]

        path = planner._compute_critical_path(nodes)
        # n0 → n1 (longer) → n3 should be the critical path
        assert "n1" in path
        assert len(path) > 0

    def test_diamond_critical_path(self, mock_settings):
        """Test critical path for a diamond dependency DAG."""
        from nexus_brain.task_planner import get_task_planner
        planner = get_task_planner()

        nodes = [
            DAGNode(id="n0", description="Root", tool="t1", tool_input={},
                    dependencies=[], status="pending", result=None, error=None,
                    can_fail_safely=False, estimated_duration_ms=100),
            DAGNode(id="n1", description="Left", tool="t2", tool_input={},
                    dependencies=["n0"], status="pending", result=None, error=None,
                    can_fail_safely=False, estimated_duration_ms=500),
            DAGNode(id="n2", description="Right", tool="t3", tool_input={},
                    dependencies=["n0"], status="pending", result=None, error=None,
                    can_fail_safely=False, estimated_duration_ms=300),
            DAGNode(id="n3", description="End", tool="t4", tool_input={},
                    dependencies=["n1", "n2"], status="pending", result=None, error=None,
                    can_fail_safely=False, estimated_duration_ms=200),
        ]

        path = planner._compute_critical_path(nodes)
        assert path[0] == "n0"
        assert path[-1] == "n3"

    def test_empty_nodes_critical_path(self, mock_settings):
        """Test critical path with empty nodes list."""
        from nexus_brain.task_planner import get_task_planner
        planner = get_task_planner()
        path = planner._compute_critical_path([])
        assert path == []


class TestParallelBranches:
    """Tests for parallel branch counting."""

    def test_count_parallel_branches_linear(self, mock_settings):
        """Test that linear DAG returns 1."""
        from nexus_brain.task_planner import get_task_planner
        planner = get_task_planner()

        nodes = [
            DAGNode(id="n0", description="S1", tool=None, tool_input={},
                    dependencies=[], status="pending", result=None, error=None,
                    can_fail_safely=False, estimated_duration_ms=100),
            DAGNode(id="n1", description="S2", tool=None, tool_input={},
                    dependencies=["n0"], status="pending", result=None, error=None,
                    can_fail_safely=False, estimated_duration_ms=100),
        ]

        branches = planner._count_parallel_branches(nodes)
        assert branches == 1

    def test_count_parallel_branches_two(self, mock_settings):
        """Test that diamond DAG returns 2."""
        from nexus_brain.task_planner import get_task_planner
        planner = get_task_planner()

        nodes = [
            DAGNode(id="n0", description="Root", tool=None, tool_input={},
                    dependencies=[], status="pending", result=None, error=None,
                    can_fail_safely=False, estimated_duration_ms=100),
            DAGNode(id="n1", description="A", tool=None, tool_input={},
                    dependencies=["n0"], status="pending", result=None, error=None,
                    can_fail_safely=False, estimated_duration_ms=100),
            DAGNode(id="n2", description="B", tool=None, tool_input={},
                    dependencies=["n0"], status="pending", result=None, error=None,
                    can_fail_safely=False, estimated_duration_ms=100),
            DAGNode(id="n3", description="Merge", tool=None, tool_input={},
                    dependencies=["n1", "n2"], status="pending", result=None, error=None,
                    can_fail_safely=False, estimated_duration_ms=100),
        ]

        branches = planner._count_parallel_branches(nodes)
        assert branches == 2

    def test_count_parallel_empty(self, mock_settings):
        """Test empty nodes returns 1."""
        from nexus_brain.task_planner import get_task_planner
        planner = get_task_planner()
        branches = planner._count_parallel_branches([])
        assert branches == 1


class TestDAGPlan:
    """Tests for DAGPlan creation."""

    def test_dag_plan_dataclass(self):
        """Test that DAGPlan can be created."""
        from nexus_brain.task_planner import DAGPlan
        plan = DAGPlan(
            description="Test plan",
            nodes=[],
            critical_path=["n0"],
            estimated_duration_ms=1000.0,
            parallel_branches=1,
            can_parallelize=False,
        )
        assert plan.description == "Test plan"
        assert plan.estimated_duration_ms == 1000.0
        assert plan.can_parallelize is False

    def test_dag_execution_result_dataclass(self):
        """Test that DAGExecutionResult can be created."""
        from nexus_brain.task_planner import DAGExecutionResult
        result = DAGExecutionResult(
            success=True,
            node_results={"n0": '{"ok": true}'},
            failed_nodes=[],
            duration_ms=500.0,
            partial=False,
        )
        assert result.success is True
        assert result.duration_ms == 500.0
        assert result.partial is False
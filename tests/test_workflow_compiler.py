"""
NEXUS AI v4.0 — Workflow compile/run tests for WorkflowCompiler.
Hardware: Intel i3 7th Gen · 12GB RAM · Ollama + Groq API

Covers:
1. WorkflowCompiler singleton and initialization
2. WorkflowStep dataclass creation
3. WorkflowParameter dataclass creation
4. Workflow dataclass creation
5. Save workflow to disk
6. Load workflow from disk
7. List workflows
8. Delete workflow
9. Compile workflow with mocked LLM
10. Execute workflow with parameter resolution
"""

import pytest
import json
import uuid
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch


class TestWorkflowCompilerInit:
    """Tests for WorkflowCompiler initialization."""

    def test_get_workflow_compiler_singleton(self):
        """Test that get_workflow_compiler returns a singleton."""
        from nexus_brain.workflow_compiler import get_workflow_compiler
        c1 = get_workflow_compiler()
        c2 = get_workflow_compiler()
        assert c1 is c2

    def test_workflow_compiler_initializes(self, mock_settings):
        """Test that compiler initializes with defaults."""
        from nexus_brain.workflow_compiler import get_workflow_compiler
        compiler = get_workflow_compiler()
        assert compiler._settings is not None
        assert compiler._audit_logger is not None
        assert compiler._workflows_dir is not None
        assert compiler._workflows_dir.exists()


class TestWorkflowDataclasses:
    """Tests for workflow dataclasses."""

    def test_workflow_step_creation(self):
        """Test creating a WorkflowStep."""
        from nexus_brain.workflow_compiler import WorkflowStep
        step = WorkflowStep(
            id="step_1",
            description="List files in directory",
            tool="t02_file_manager",
            tool_input={"path": "."},
            depends_on=[],
            retry_on_failure=False,
            timeout_seconds=30,
        )
        assert step.id == "step_1"
        assert step.tool == "t02_file_manager"
        assert step.tool_input["path"] == "."
        assert step.retry_on_failure is False

    def test_workflow_parameter_creation(self):
        """Test creating a WorkflowParameter."""
        from nexus_brain.workflow_compiler import WorkflowParameter
        param = WorkflowParameter(
            name="file_path",
            description="Path to the file to process",
            type="string",
            default="./default.txt",
            required=True,
            choices=[],
        )
        assert param.name == "file_path"
        assert param.required is True
        assert param.default == "./default.txt"

    def test_workflow_parameter_choice_type(self):
        """Test creating a choice-type parameter."""
        from nexus_brain.workflow_compiler import WorkflowParameter
        param = WorkflowParameter(
            name="mode",
            description="Operation mode",
            type="choice",
            default="fast",
            required=True,
            choices=["fast", "slow", "detailed"],
        )
        assert param.type == "choice"
        assert len(param.choices) == 3

    def test_workflow_creation(self):
        """Test creating a complete Workflow."""
        from nexus_brain.workflow_compiler import Workflow, WorkflowStep, WorkflowParameter
        workflow = Workflow(
            workflow_id=str(uuid.uuid4()),
            name="daily_report",
            description="Generate daily report",
            version="1.0.0",
            author="NEXUS AI",
            created_at="2026-01-01T00:00:00",
            updated_at="2026-01-01T00:00:00",
            parameters=[
                WorkflowParameter(name="output_path", description="Output path", type="string"),
            ],
            steps=[
                WorkflowStep(id="step_1", description="Collect data", tool="t18_data_analyzer",
                             tool_input={"source": "logs"}, depends_on=[]),
            ],
            tags=["reporting", "daily"],
        )
        assert workflow.name == "daily_report"
        assert len(workflow.steps) == 1
        assert len(workflow.parameters) == 1
        assert "reporting" in workflow.tags


class TestWorkflowPersistence:
    """Tests for workflow save/load/list/delete."""

    def test_save_workflow(self, mock_settings):
        """Test saving a workflow to disk."""
        from nexus_brain.workflow_compiler import get_workflow_compiler, Workflow, WorkflowStep
        compiler = get_workflow_compiler()

        workflow = Workflow(
            workflow_id=str(uuid.uuid4()),
            name="test_save_workflow",
            description="Test save",
            steps=[
                WorkflowStep(id="step_1", description="Test", tool="t01_system_command",
                             tool_input={"command": "echo hello"}, depends_on=[]),
            ],
        )

        result = compiler.save_workflow(workflow)
        assert result is True

        # Verify file exists
        file_path = compiler._workflows_dir / "test_save_workflow.nexflow.json"
        assert file_path.exists()

        # Cleanup
        file_path.unlink()

    def test_load_workflow(self, mock_settings):
        """Test loading a workflow from disk."""
        from nexus_brain.workflow_compiler import get_workflow_compiler, Workflow, WorkflowStep
        compiler = get_workflow_compiler()

        workflow = Workflow(
            workflow_id=str(uuid.uuid4()),
            name="test_load_workflow",
            description="Test load",
            steps=[
                WorkflowStep(id="step_1", description="Test", tool="t01_system_command",
                             tool_input={"command": "echo hello"}, depends_on=[]),
            ],
        )
        compiler.save_workflow(workflow)

        loaded = compiler.load_workflow("test_load_workflow")
        assert loaded is not None
        assert loaded.name == "test_load_workflow"
        assert loaded.description == "Test load"
        assert len(loaded.steps) == 1

        # Cleanup
        (compiler._workflows_dir / "test_load_workflow.nexflow.json").unlink()

    def test_load_nonexistent_workflow(self, mock_settings):
        """Test loading a workflow that doesn't exist."""
        from nexus_brain.workflow_compiler import get_workflow_compiler
        compiler = get_workflow_compiler()
        loaded = compiler.load_workflow("nonexistent_workflow")
        assert loaded is None

    def test_list_workflows(self, mock_settings):
        """Test listing saved workflows."""
        from nexus_brain.workflow_compiler import get_workflow_compiler, Workflow, WorkflowStep
        compiler = get_workflow_compiler()

        # Save two workflows
        wf1 = Workflow(workflow_id=str(uuid.uuid4()), name="wf_list_a", description="A",
                       steps=[WorkflowStep(id="s1", description="A", tool="t1", tool_input={})])
        wf2 = Workflow(workflow_id=str(uuid.uuid4()), name="wf_list_b", description="B",
                       steps=[WorkflowStep(id="s1", description="B", tool="t1", tool_input={})])
        compiler.save_workflow(wf1)
        compiler.save_workflow(wf2)

        names = compiler.list_workflows()
        assert "wf_list_a" in names
        assert "wf_list_b" in names

        # Cleanup
        (compiler._workflows_dir / "wf_list_a.nexflow.json").unlink()
        (compiler._workflows_dir / "wf_list_b.nexflow.json").unlink()

    def test_delete_workflow(self, mock_settings):
        """Test deleting a workflow."""
        from nexus_brain.workflow_compiler import get_workflow_compiler, Workflow, WorkflowStep
        compiler = get_workflow_compiler()

        workflow = Workflow(workflow_id=str(uuid.uuid4()), name="test_delete_wf", description="Delete me",
                           steps=[WorkflowStep(id="s1", description="D", tool="t1", tool_input={})])
        compiler.save_workflow(workflow)

        result = compiler.delete_workflow("test_delete_wf")
        assert result is True
        assert compiler.load_workflow("test_delete_wf") is None

    def test_delete_nonexistent_workflow(self, mock_settings):
        """Test deleting a workflow that doesn't exist."""
        from nexus_brain.workflow_compiler import get_workflow_compiler
        compiler = get_workflow_compiler()
        result = compiler.delete_workflow("nonexistent")
        assert result is False


class TestWorkflowCompilation:
    """Tests for workflow compilation from natural language."""

    @pytest.mark.asyncio
    async def test_compile_workflow_success(self, mock_settings):
        """Test successful workflow compilation with mocked LLM."""
        from nexus_brain.workflow_compiler import get_workflow_compiler
        compiler = get_workflow_compiler()

        mock_response = MagicMock()
        mock_response.success = True
        mock_response.content = json.dumps({
            "name": "daily_report",
            "description": "Generate a daily report from logs",
            "tags": ["reporting", "automation"],
            "parameters": [
                {
                    "name": "log_path",
                    "description": "Path to log files",
                    "type": "string",
                    "default": "./logs",
                    "required": True,
                    "choices": [],
                }
            ],
            "steps": [
                {
                    "id": "step_1",
                    "description": "Read log files",
                    "tool": "t02_file_manager",
                    "tool_input": {"path": "{{log_path}}"},
                    "depends_on": [],
                    "retry_on_failure": False,
                    "timeout_seconds": 30,
                },
                {
                    "id": "step_2",
                    "description": "Analyze log data",
                    "tool": "t18_data_analyzer",
                    "tool_input": {"source": "{{log_path}}/output"},
                    "depends_on": ["step_1"],
                    "retry_on_failure": True,
                    "timeout_seconds": 60,
                },
            ],
        })

        with patch("nexus_brain.workflow_compiler.get_llm_router") as mock_router:
            mock_router.return_value.generate = AsyncMock(return_value=mock_response)
            workflow = await compiler.compile(
                task_description="Generate a daily report from logs",
                tools_descriptions="t02_file_manager: File operations\nt18_data_analyzer: Data analysis",
            )

        assert workflow is not None
        assert workflow.name == "daily_report"
        assert len(workflow.steps) == 2
        assert len(workflow.parameters) == 1
        assert workflow.parameters[0].name == "log_path"

    @pytest.mark.asyncio
    async def test_compile_workflow_llm_failure(self, mock_settings):
        """Test compilation when LLM fails."""
        from nexus_brain.workflow_compiler import get_workflow_compiler
        compiler = get_workflow_compiler()

        mock_response = MagicMock()
        mock_response.success = False
        mock_response.error = "LLM unavailable"

        with patch("nexus_brain.workflow_compiler.get_llm_router") as mock_router:
            mock_router.return_value.generate = AsyncMock(return_value=mock_response)
            workflow = await compiler.compile(
                task_description="Test task",
                tools_descriptions="t1: tool 1",
            )

        assert workflow is None

    @pytest.mark.asyncio
    async def test_compile_workflow_invalid_json(self, mock_settings):
        """Test compilation with invalid JSON response."""
        from nexus_brain.workflow_compiler import get_workflow_compiler
        compiler = get_workflow_compiler()

        mock_response = MagicMock()
        mock_response.success = True
        mock_response.content = "not valid json"

        with patch("nexus_brain.workflow_compiler.get_llm_router") as mock_router:
            mock_router.return_value.generate = AsyncMock(return_value=mock_response)
            workflow = await compiler.compile(
                task_description="Test",
                tools_descriptions="t1: tool 1",
            )

        assert workflow is None


class TestWorkflowExecution:
    """Tests for workflow execution."""

    @pytest.mark.asyncio
    async def test_execute_workflow(self, mock_settings):
        """Test executing a workflow with parameter resolution."""
        from nexus_brain.workflow_compiler import get_workflow_compiler, Workflow, WorkflowStep, WorkflowParameter
        compiler = get_workflow_compiler()

        workflow = Workflow(
            workflow_id=str(uuid.uuid4()),
            name="test_exec",
            description="Test execution",
            parameters=[
                WorkflowParameter(name="name", description="Name to greet", type="string", required=True),
            ],
            steps=[
                WorkflowStep(id="step_1", description="Greet", tool="t01_system_command",
                             tool_input={"command": "echo Hello {{name}}"}, depends_on=[]),
            ],
        )

        async def mock_executor(tool_name, tool_input, is_ui):
            return json.dumps({"success": True, "result": f"Executed: {tool_input.get('command', '')}"})

        result = await compiler.execute(workflow, {"name": "World"}, mock_executor)
        assert result["success"] is True
        assert "World" in result["results"]["step_1"]

    @pytest.mark.asyncio
    async def test_execute_workflow_with_retry(self, mock_settings):
        """Test workflow execution with retry on failure."""
        from nexus_brain.workflow_compiler import get_workflow_compiler, Workflow, WorkflowStep
        compiler = get_workflow_compiler()

        workflow = Workflow(
            workflow_id=str(uuid.uuid4()),
            name="test_retry",
            description="Test retry",
            steps=[
                WorkflowStep(id="step_1", description="Failing step", tool="t01_system_command",
                             tool_input={"command": "fail"}, depends_on=[], retry_on_failure=True),
            ],
        )

        call_count = 0

        async def failing_executor(tool_name, tool_input, is_ui):
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise RuntimeError("First attempt failed")
            return json.dumps({"success": True, "result": "Retry succeeded"})

        result = await compiler.execute(workflow, {}, failing_executor)
        assert result["success"] is True
        assert call_count >= 2
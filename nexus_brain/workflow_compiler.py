"""
NEXUS AI v4.0 — Natural Language → .nexflow.json macro compiler.
Hardware: Intel i3 7th Gen · 12GB RAM · Ollama + Groq API

Compiles natural language descriptions into reusable workflow macros.
Workflows are saved as .nexflow.json files in APP_ROOT/workflows/ and
can be executed via t16_workflow_macro.

A workflow is a reusable automation that captures:
  - The user's original description
  - A sequence of tool calls with their inputs
  - Expected outputs and success criteria
  - Parameter slots for customization on re-run
"""

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Optional, Dict, Any, List, Literal
from functools import lru_cache

from nexus_config.settings import get_settings, APP_ROOT
from nexus_config.audit_logger import get_audit_logger

logger = logging.getLogger("nexus.workflow")


# ─── Workflow Types ───────────────────────────────────────────────────────────

@dataclass
class WorkflowStep:
    """
    A single step in a compiled workflow.
    
    Fields:
        id: Step identifier (e.g. "step_1").
        description: Human-readable description of what this step does.
        tool: Tool name to execute.
        tool_input: Arguments for the tool. Can contain {{param}} placeholders.
        depends_on: List of step IDs that must complete first.
        retry_on_failure: If True, retry this step once on failure.
        timeout_seconds: Maximum seconds for this step.
    """
    id: str
    description: str
    tool: str
    tool_input: Dict[str, Any]
    depends_on: List[str] = field(default_factory=list)
    retry_on_failure: bool = False
    timeout_seconds: int = 30


@dataclass
class WorkflowParameter:
    """
    A parameter slot for the workflow (customized at runtime).
    
    Fields:
        name: Parameter name (matches {{param}} in tool_input).
        description: What this parameter controls.
        type: "string", "number", "boolean", "file", "choice".
        default: Default value.
        required: If True, user must provide a value.
        choices: Valid options for "choice" type.
    """
    name: str
    description: str
    type: Literal["string", "number", "boolean", "file", "choice"] = "string"
    default: Any = ""
    required: bool = False
    choices: List[str] = field(default_factory=list)


@dataclass
class Workflow:
    """
    A compiled .nexflow.json workflow macro.
    
    Fields:
        workflow_id: UUID4 identifier.
        name: Human-readable name.
        description: What this workflow does (original NL description).
        version: Semantic version (starts at "1.0.0").
        author: Creator name (default: "NEXUS AI").
        created_at: ISO timestamp.
        updated_at: ISO timestamp.
        parameters: List of parameter slots.
        steps: List of workflow steps.
        tags: Category keywords.
        execution_count: How many times this has been run.
        last_execution: ISO timestamp of last run.
        avg_duration_ms: Average execution duration.
        success_rate: Fraction of successful runs (0.0-1.0).
    """
    workflow_id: str
    name: str
    description: str
    version: str = "1.0.0"
    author: str = "NEXUS AI"
    created_at: str = ""
    updated_at: str = ""
    parameters: List[WorkflowParameter] = field(default_factory=list)
    steps: List[WorkflowStep] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    execution_count: int = 0
    last_execution: str = ""
    avg_duration_ms: float = 0.0
    success_rate: float = 1.0


# ─── Compilation Prompt ───────────────────────────────────────────────────────

COMPILATION_PROMPT = """You are NEXUS AI's workflow compiler. Convert the user's description of a multi-step task into a reusable workflow macro.

Available tools with descriptions:
{tools_descriptions}

User description: {task_description}

Rules:
1. Break the task into individual tool call steps in order.
2. Each step should use one tool from the available tools list.
3. Steps that depend on previous steps MUST list those in "depends_on".
4. Identify any parameters the user should customize on re-run (e.g., file paths, names, URLs).
5. Mark parameters as {{param_name}} in tool_input values.
6. Simple, single-step tasks may still be recorded for convenience reuse but with minimal complexity.

Respond with JSON ONLY — no markdown, no explanation:
{{
    "name": "Short kebab-case name for the workflow",
    "description": "Brief description of what it does",
    "tags": ["productivity", "category"],
    "parameters": [
        {{
            "name": "param_name",
            "description": "What this parameter controls",
            "type": "string|number|boolean|file|choice",
            "default": "",
            "required": true,
            "choices": []
        }}
    ],
    "steps": [
        {{
            "id": "step_1",
            "description": "What this step does",
            "tool": "tool_name",
            "tool_input": {{"key": "value with {{param}}"}},
            "depends_on": [],
            "retry_on_failure": false,
            "timeout_seconds": 30
        }}
    ]
}}"""


# ─── Workflow Compiler ────────────────────────────────────────────────────────

class WorkflowCompiler:
    """
    Compiles natural language task descriptions into reusable workflow macros.
    
    Usage:
        compiler = get_workflow_compiler()
        workflow = await compiler.compile("Open VS Code, run tests, create a PR")
        # Save to disk
        compiler.save_workflow(workflow)
        # Load and run later
        workflow = compiler.load_workflow("daily_tests")
        result = await compiler.execute(workflow, {"branch": "feature-x"})
    """
    
    def __init__(self):
        self._settings = get_settings()
        self._audit_logger = get_audit_logger()
        self._workflows_dir = APP_ROOT / "workflows"
        self._workflows_dir.mkdir(parents=True, exist_ok=True)
    
    async def compile(
        self,
        task_description: str,
        tools_descriptions: str,
    ) -> Optional[Workflow]:
        """
        Compile a natural language description into a Workflow.
        
        Args:
            task_description: The user's description of the task.
            tools_descriptions: Formatted string of available tools.
        
        Returns:
            Workflow if compilation succeeded, None if it failed.
        """
        from nexus_brain.llm_router import get_llm_router
        
        prompt = COMPILATION_PROMPT.format(
            task_description=task_description[:2000],
            tools_descriptions=tools_descriptions[:3000],
        )
        
        router = get_llm_router()
        response = await router.generate(
            messages=[
                {"role": "system", "content": "You are a workflow compiler. Respond with JSON only."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
            max_tokens=2000,
            response_format={"type": "json_object"},
        )
        
        if not response.success:
            logger.error("Workflow compilation failed: %s", response.error)
            return None
        
        try:
            data = json.loads(response.content)
        except json.JSONDecodeError as e:
            logger.error("Workflow JSON parse failed: %s", e)
            return None
        
        # Validate required fields
        if not data.get("name") or not data.get("steps"):
            logger.warning("Workflow compilation produced incomplete output")
            return None
        
        import datetime
        now = datetime.datetime.now().isoformat()
        
        # Parse parameters
        parameters = []
        for p in data.get("parameters", []):
            parameters.append(WorkflowParameter(
                name=p.get("name", "param"),
                description=p.get("description", ""),
                type=p.get("type", "string"),
                default=p.get("default", ""),
                required=p.get("required", False),
                choices=p.get("choices", []),
            ))
        
        # Parse steps
        steps = []
        for s in data.get("steps", []):
            steps.append(WorkflowStep(
                id=s.get("id", f"step_{len(steps)+1}"),
                description=s.get("description", ""),
                tool=s.get("tool", ""),
                tool_input=s.get("tool_input", {}),
                depends_on=s.get("depends_on", []),
                retry_on_failure=s.get("retry_on_failure", False),
                timeout_seconds=s.get("timeout_seconds", 30),
            ))
        
        return Workflow(
            workflow_id=str(uuid.uuid4()),
            name=data.get("name", "unnamed_workflow"),
            description=data.get("description", task_description[:500]),
            version="1.0.0",
            author="NEXUS AI",
            created_at=now,
            updated_at=now,
            parameters=parameters,
            steps=steps,
            tags=data.get("tags", []),
        )
    
    def save_workflow(self, workflow: Workflow) -> bool:
        """
        Save a workflow to disk as .nexflow.json.
        
        Args:
            workflow: The workflow to save.
        
        Returns:
            True if save succeeded.
        """
        try:
            file_path = self._workflows_dir / f"{workflow.name}.nexflow.json"
            data = asdict(workflow)
            file_path.write_text(
                json.dumps(data, indent=2, default=str),
                encoding="utf-8",
            )
            logger.info("Workflow '%s' saved to %s", workflow.name, file_path)
            return True
        except Exception as e:
            logger.error("Failed to save workflow '%s': %s", workflow.name, e)
            return False
    
    def load_workflow(self, name: str) -> Optional[Workflow]:
        """
        Load a workflow from disk by name.
        
        Args:
            name: Workflow name (without .nexflow.json extension).
        
        Returns:
            Workflow if found, None otherwise.
        """
        file_path = self._workflows_dir / f"{name}.nexflow.json"
        if not file_path.exists():
            return None
        
        try:
            data = json.loads(file_path.read_text(encoding="utf-8"))
            return self._dict_to_workflow(data)
        except Exception as e:
            logger.error("Failed to load workflow '%s': %s", name, e)
            return None
    
    def list_workflows(self) -> List[str]:
        """
        List all saved workflow names.
        
        Returns:
            Sorted list of workflow names (without extension).
        """
        names = []
        for file_path in self._workflows_dir.glob("*.nexflow.json"):
            names.append(file_path.stem.replace(".nexflow", ""))
        return sorted(names)
    
    def delete_workflow(self, name: str) -> bool:
        """
        Delete a saved workflow.
        
        Args:
            name: Workflow name.
        
        Returns:
            True if deleted, False if not found.
        """
        file_path = self._workflows_dir / f"{name}.nexflow.json"
        if file_path.exists():
            file_path.unlink()
            logger.info("Workflow '%s' deleted.", name)
            return True
        return False
    
    def _dict_to_workflow(self, data: Dict[str, Any]) -> Workflow:
        """Convert a dict back to a Workflow dataclass."""
        parameters = []
        for p in data.get("parameters", []):
            parameters.append(WorkflowParameter(**p))
        
        steps = []
        for s in data.get("steps", []):
            steps.append(WorkflowStep(**s))
        
        return Workflow(
            workflow_id=data.get("workflow_id", str(uuid.uuid4())),
            name=data.get("name", "unnamed"),
            description=data.get("description", ""),
            version=data.get("version", "1.0.0"),
            author=data.get("author", "NEXUS AI"),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
            parameters=parameters,
            steps=steps,
            tags=data.get("tags", []),
            execution_count=data.get("execution_count", 0),
            last_execution=data.get("last_execution", ""),
            avg_duration_ms=data.get("avg_duration_ms", 0.0),
            success_rate=data.get("success_rate", 1.0),
        )
    
    async def execute(
        self,
        workflow: Workflow,
        parameter_values: Dict[str, Any],
        tool_executor: Any,
    ) -> Dict[str, Any]:
        """
        Execute a compiled workflow with given parameter values.
        
        Replaces {{param}} placeholders with actual values, then executes
        each step in order respecting dependencies.
        
        Args:
            workflow: The workflow to execute.
            parameter_values: Dict of parameter name → value.
            tool_executor: Async function (tool_name, tool_input, is_ui) → str.
        
        Returns:
            Dict with success, results, duration_ms, error.
        """
        start = time.perf_counter()
        results: Dict[str, str] = {}
        errors: List[str] = []
        
        # Apply parameter values
        def resolve_params(value: Any) -> Any:
            if isinstance(value, str):
                import re
                def replace_match(match):
                    param_name = match.group(1)
                    return str(parameter_values.get(param_name, match.group(0)))
                return re.sub(r"\{\{(.*?)\}\}", replace_match, value)
            if isinstance(value, dict):
                return {k: resolve_params(v) for k, v in value.items()}
            if isinstance(value, list):
                return [resolve_params(v) for v in value]
            return value
        
        completed: set = set()
        
        # Execute steps in order, respecting dependencies
        while len(completed) < len(workflow.steps):
            progress = False
            
            for step in workflow.steps:
                if step.id in completed:
                    continue
                
                # Check dependencies
                deps_satisfied = all(dep in completed for dep in step.depends_on)
                if not deps_satisfied:
                    continue
                
                progress = True
                
                try:
                    resolved_input = resolve_params(step.tool_input)
                    output = await tool_executor(step.tool, resolved_input, False)
                    results[step.id] = output
                    completed.add(step.id)
                except Exception as e:
                    if step.retry_on_failure:
                        try:
                            output = await tool_executor(step.tool, resolve_params(step.tool_input), False)
                            results[step.id] = output
                            completed.add(step.id)
                            continue
                        except Exception:
                            pass
                    
                    errors.append(f"{step.id}: {e}")
                    completed.add(step.id)  # Mark as completed (failed)
            
            if not progress:
                errors.append("Dependency cycle detected or stuck — cannot proceed")
                break
        
        duration = (time.perf_counter() - start) * 1000
        
        # Update execution metadata
        workflow.execution_count += 1
        workflow.last_execution = time.strftime("%Y-%m-%dT%H:%M:%S")
        workflow.avg_duration_ms = (
            (workflow.avg_duration_ms * (workflow.execution_count - 1) + duration)
            / workflow.execution_count
        )
        success = len(errors) == 0
        workflow.success_rate = (
            (workflow.success_rate * (workflow.execution_count - 1) + (1.0 if success else 0.0))
            / workflow.execution_count
        )
        
        # Save updated metadata
        self.save_workflow(workflow)
        
        return {
            "success": success,
            "results": results,
            "errors": errors,
            "duration_ms": duration,
            "workflow_name": workflow.name,
        }


@lru_cache(maxsize=1)
def get_workflow_compiler() -> WorkflowCompiler:
    """
    Return the singleton WorkflowCompiler instance.
    
    Returns:
        WorkflowCompiler: The singleton compiler instance.
    """
    return WorkflowCompiler()

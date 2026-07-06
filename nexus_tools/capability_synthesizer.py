"""
NEXUS AI v4.0 — Self-healing capability synthesis engine.
Hardware: Intel i3 7th Gen · 12GB RAM · Ollama + Groq API

When a tool call fails with ModuleNotFoundError, ImportError, or "no capability",
this engine attempts to synthesize a new tool by:
  1. Asking the LLM to generate Python code for the missing capability
  2. Validating the generated code with AST analysis
  3. Writing it to the synthesized_tools directory
  4. Dynamically importing and registering the new tool
  5. Retrying the original tool call

The synthesis pipeline runs up to SYNTHESIS_MAX_RETRIES (default: 3) times
before giving up and reporting the failure to the user.
"""

import ast
import asyncio
import importlib.util
import json
import logging
import os
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Dict, Any, List
from functools import lru_cache

from nexus_config.settings import get_settings, APP_ROOT
from nexus_config.audit_logger import get_audit_logger
from nexus_brain.llm_router import get_llm_router, LLMResponse

logger = logging.getLogger("nexus.synthesizer")


# ─── Synthesis Result ──────────────────────────────────────────────────────────

@dataclass
class SynthesisResult:
    """
    Result of a capability synthesis attempt.

    Fields:
        success: True if a tool was successfully synthesized and registered.
        tool_name: Name of the synthesized tool (e.g. "t23_custom_api").
        tool_path: Filesystem path to the synthesized tool module.
        code: The generated Python code.
        attempts: List of (attempt_number, error) tuples for each retry.
        registered: True if the tool was registered in the registry.
    """
    success: bool = False
    tool_name: str = ""
    tool_path: Optional[Path] = None
    code: str = ""
    attempts: List[Dict[str, Any]] = field(default_factory=list)
    registered: bool = False


# ─── Synthesis Prompt Template ─────────────────────────────────────────────────

SYNTHESIS_PROMPT = """You are NEXUS AI's capability synthesis engine. Your task is to generate a Python tool that fills a capability gap.

The user's original task was: {task}

The tool execution failed with: {failure_reason}

Currently available tools: {tools_list}

Generate a complete Python module for a new tool that would solve this problem. The module must:

1. Define an async function `execute(input_data: dict) -> dict` as the main entry point
2. Accept a single `input_data` dict parameter and return a dict with keys "success" and "result" (or "error")
3. Be self-contained (all imports inside the function or at module level)
4. Handle errors gracefully with try/except
5. Include a docstring describing what the tool does
6. Be safe — no subprocess calls, no file system access outside allowed paths, no network calls to unknown hosts
7. Use only standard library + already-installed packages (httpx, aiofiles, PIL, pandas, etc.)

Respond with ONLY the Python code in a single code block:

```python
# tool_name: tXX_descriptive_name
\"\"\"
Docstring describing the tool.
\"\"\"
import ...

async def execute(input_data: dict) -> dict:
    \"\"\"Execute the tool.\"\"\"
    try:
        # Implementation
        return {{"success": True, "result": "output"}}
    except Exception as e:
        return {{"success": False, "error": str(e)}}
```"""


# ─── Code Validation ───────────────────────────────────────────────────────────

def _validate_generated_code(code: str) -> List[str]:
    """
    Validate generated Python code for safety and correctness.

    Checks:
    1. Valid Python syntax (AST parse)
    2. No dangerous imports (os.system, subprocess, shutil.rmtree, etc.)
    3. Has an async execute() function
    4. No infinite loops (while True without break/return)

    Args:
        code: The generated Python source code.

    Returns:
        List of validation errors. Empty list = code is valid.
    """
    errors: List[str] = []

    # Check 1: Valid Python syntax
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        errors.append(f"Syntax error: {e}")
        return errors

    # Check 2: No dangerous imports
    DANGEROUS_MODULES = {"os", "subprocess", "shutil", "ctypes", "multiprocessing"}
    DANGEROUS_ATTRS = {"system", "popen", "call", "run", "rmtree", "remove", "unlink"}

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top_level = alias.name.split(".")[0]
                if top_level in DANGEROUS_MODULES:
                    errors.append(f"Dangerous import: {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                top_level = node.module.split(".")[0]
                if top_level in DANGEROUS_MODULES:
                    errors.append(f"Dangerous import from: {node.module}")
        elif isinstance(node, ast.Attribute):
            if node.attr in DANGEROUS_ATTRS:
                errors.append(f"Dangerous attribute access: {node.attr}")

    # Check 3: Has async execute() function
    has_execute = False
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "execute":
            has_execute = True
            # Check signature: (input_data: dict) -> dict
            args = node.args.args
            if len(args) < 1:
                errors.append("execute() must have at least 1 parameter (input_data)")
            break
    if not has_execute:
        errors.append("No async execute() function found")

    # Check 4: No infinite while True loops without break/return
    for node in ast.walk(tree):
        if isinstance(node, ast.While):
            if isinstance(node.test, ast.Constant) and node.test.value is True:
                has_exit = any(
                    isinstance(n, (ast.Break, ast.Return, ast.Raise))
                    for n in ast.walk(node)
                )
                if not has_exit:
                    errors.append("Infinite while True loop without break/return")

    return errors


# ─── Main Synthesizer ──────────────────────────────────────────────────────────

class CapabilitySynthesizer:
    """
    Self-healing capability synthesis engine.

    When a tool call fails, this engine:
    1. Asks the LLM to generate code for the missing capability
    2. Validates the generated code
    3. Writes it to APP_ROOT/synthesized_tools/
    4. Dynamically imports the new tool
    5. Registers it with the tool registry

    Usage:
        synthesizer = get_capability_synthesizer()
        result = await synthesizer.synthesize(
            task="Send an email",
            failure_reason="ModuleNotFoundError: No module named 'email_client'",
            tools_list="t01_system_command, t02_file_manager",
        )
        if result.success:
            # Retry the original task with result.tool_name
    """

    def __init__(self):
        self._settings = get_settings()
        self._audit_logger = get_audit_logger()
        self._llm_router = get_llm_router()
        self._synthesis_dir = APP_ROOT / "synthesized_tools"
        self._synthesis_dir.mkdir(parents=True, exist_ok=True)
        self._registry = None  # Set by set_registry()

    def set_registry(self, registry) -> None:
        """Set the tool registry for registering synthesized tools."""
        self._registry = registry

    async def synthesize(
        self,
        task: str,
        failure_reason: str,
        tools_list: str = "",
    ) -> SynthesisResult:
        """
        Attempt to synthesize a new capability.

        Args:
            task: The original user task that failed.
            failure_reason: The error message from the failed tool call.
            tools_list: Comma-separated list of currently available tools.

        Returns:
            SynthesisResult with success status and tool metadata.
        """
        max_retries = self._settings.SYNTHESIS_MAX_RETRIES
        result = SynthesisResult()

        for attempt in range(1, max_retries + 1):
            attempt_start = time.perf_counter()

            try:
                # Step 1: Ask LLM to generate code
                prompt = SYNTHESIS_PROMPT.format(
                    task=task[:500],
                    failure_reason=failure_reason[:500],
                    tools_list=tools_list[:500],
                )

                response = await self._llm_router.generate(
                    messages=[
                        {
                            "role": "system",
                            "content": "You are a Python code generator. Generate ONLY valid Python code.",
                        },
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.2,
                    max_tokens=2048,
                    prefer_provider="ollama",
                )

                if not response.success:
                    result.attempts.append({
                        "attempt": attempt,
                        "error": f"LLM generation failed: {response.error}",
                        "duration_ms": (time.perf_counter() - attempt_start) * 1000,
                    })
                    continue

                # Step 2: Extract code from response
                code = self._extract_code(response.content)
                if not code:
                    result.attempts.append({
                        "attempt": attempt,
                        "error": "No Python code block found in LLM response",
                        "duration_ms": (time.perf_counter() - attempt_start) * 1000,
                    })
                    continue

                # Step 3: Validate code
                validation_errors = _validate_generated_code(code)
                if validation_errors:
                    result.attempts.append({
                        "attempt": attempt,
                        "error": f"Validation failed: {'; '.join(validation_errors)}",
                        "duration_ms": (time.perf_counter() - attempt_start) * 1000,
                    })
                    continue

                # Step 4: Extract tool name from code comment
                tool_name = self._extract_tool_name(code)
                if not tool_name:
                    tool_name = f"t_synthesized_{uuid.uuid4().hex[:8]}"

                # Step 5: Write to file
                tool_path = self._synthesis_dir / f"{tool_name}.py"
                tool_path.write_text(code, encoding="utf-8")

                # Step 6: Dynamically import
                try:
                    spec = importlib.util.spec_from_file_location(tool_name, str(tool_path))
                    if spec and spec.loader:
                        module = importlib.util.module_from_spec(spec)
                        # Don't add to sys.modules permanently — just load and register
                        spec.loader.exec_module(module)
                    else:
                        raise ImportError(f"Could not load spec for {tool_name}")
                except Exception as e:
                    result.attempts.append({
                        "attempt": attempt,
                        "error": f"Import failed: {e}",
                        "duration_ms": (time.perf_counter() - attempt_start) * 1000,
                    })
                    # Clean up failed file
                    if tool_path.exists():
                        tool_path.unlink()
                    continue

                # Step 7: Register with registry
                registered = False
                if self._registry and hasattr(self._registry, "register_tool"):
                    try:
                        self._registry.register_tool(
                            tool_name=tool_name,
                            tool_module=module,
                            description=module.__doc__ or f"Synthesized tool: {tool_name}",
                        )
                        registered = True
                    except Exception as e:
                        logger.warning("Registry registration failed: %s", e)

                # Success!
                result.success = True
                result.tool_name = tool_name
                result.tool_path = tool_path
                result.code = code
                result.registered = registered
                result.attempts.append({
                    "attempt": attempt,
                    "success": True,
                    "duration_ms": (time.perf_counter() - attempt_start) * 1000,
                })

                # Log success
                self._audit_logger.log(
                    event_type="CAPABILITY_SYNTHESIS",
                    data={
                        "tool_name": tool_name,
                        "task": task[:100],
                        "attempts": attempt,
                        "registered": registered,
                    },
                    module="nexus_tools.capability_synthesizer",
                    function_name="synthesize",
                    duration_ms=(time.perf_counter() - attempt_start) * 1000,
                    success=True,
                )

                return result

            except Exception as e:
                result.attempts.append({
                    "attempt": attempt,
                    "error": f"Synthesis error: {e}",
                    "duration_ms": (time.perf_counter() - attempt_start) * 1000,
                })
                logger.error("Synthesis attempt %d failed: %s", attempt, e)

        # All attempts failed
        self._audit_logger.log(
            event_type="CAPABILITY_SYNTHESIS",
            data={
                "task": task[:100],
                "failure_reason": failure_reason[:100],
                "total_attempts": max_retries,
            },
            module="nexus_tools.capability_synthesizer",
            function_name="synthesize",
            duration_ms=0,
            success=False,
        )

        return result

    def _extract_code(self, content: str) -> str:
        """
        Extract Python code from LLM response.

        Handles:
        - ```python ... ``` blocks
        - ``` ... ``` blocks
        - Raw code without fences

        Args:
            content: Raw LLM response.

        Returns:
            Extracted Python code, or empty string if not found.
        """
        # Pattern 1: ```python ... ```
        if "```python" in content:
            parts = content.split("```python")
            if len(parts) > 1:
                code_part = parts[1].split("```")[0]
                return code_part.strip()

        # Pattern 2: ``` ... ```
        if "```" in content:
            parts = content.split("```")
            for i, part in enumerate(parts):
                part = part.strip()
                if part.startswith("import") or part.startswith("async def") or part.startswith("def "):
                    return part
                if part.startswith("python") and i + 1 < len(parts):
                    return parts[i + 1].strip()

        # Pattern 3: No fences — try to find code directly
        lines = content.strip().split("\n")
        code_lines = []
        in_code = False
        for line in lines:
            if line.startswith("import ") or line.startswith("from ") or line.startswith("async def"):
                in_code = True
            if in_code:
                code_lines.append(line)

        return "\n".join(code_lines).strip()

    def _extract_tool_name(self, code: str) -> str:
        """
        Extract tool name from code comment.

        Looks for: # tool_name: tXX_descriptive_name

        Args:
            code: The generated Python code.

        Returns:
            Tool name string, or empty string if not found.
        """
        for line in code.split("\n"):
            line = line.strip()
            if line.startswith("# tool_name:"):
                return line.split("# tool_name:")[-1].strip()
            if line.startswith("# tool:"):
                return line.split("# tool:")[-1].strip()
        return ""

    async def close(self) -> None:
        """Clean up resources."""
        pass


@lru_cache(maxsize=1)
def get_capability_synthesizer() -> CapabilitySynthesizer:
    """
    Return the singleton CapabilitySynthesizer instance.

    Returns:
        CapabilitySynthesizer: The singleton synthesizer instance.
    """
    return CapabilitySynthesizer()
"""
NEXUS AI v4.0 — 10 integration tests for CapabilitySynthesizer.
Hardware: Intel i3 7th Gen · 12GB RAM · Ollama + Groq API

Covers:
1. Singleton creation and initialization
2. Code validation — valid syntax
3. Code validation — syntax errors
4. Code validation — dangerous imports rejected
5. Code validation — missing execute() function
6. Code validation — infinite loop detection
7. Code extraction from LLM response (```python blocks)
8. Code extraction from markdown blocks
9. Tool name extraction from code comments
10. Full synthesize flow with mocked LLM
"""

import pytest
import asyncio
import json
import ast
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch


class TestSynthesizerInit:
    """Tests for synthesizer initialization."""

    def test_get_capability_synthesizer_singleton(self):
        """Test that get_capability_synthesizer returns a singleton."""
        from nexus_tools.capability_synthesizer import get_capability_synthesizer
        s1 = get_capability_synthesizer()
        s2 = get_capability_synthesizer()
        assert s1 is s2

    def test_synthesizer_initializes(self, mock_settings):
        """Test that synthesizer initializes with defaults."""
        from nexus_tools.capability_synthesizer import get_capability_synthesizer
        syn = get_capability_synthesizer()
        assert syn._settings is not None
        assert syn._audit_logger is not None
        assert syn._llm_router is not None
        assert syn._synthesis_dir is not None
        assert syn._synthesis_dir.exists()

    def test_set_registry(self, mock_settings):
        """Test that set_registry stores the registry reference."""
        from nexus_tools.capability_synthesizer import get_capability_synthesizer
        syn = get_capability_synthesizer()
        mock_registry = MagicMock()
        syn.set_registry(mock_registry)
        assert syn._registry is mock_registry


class TestCodeValidation:
    """Tests for _validate_generated_code function."""

    def test_valid_syntax(self):
        """Test that valid Python code passes validation."""
        from nexus_tools.capability_synthesizer import _validate_generated_code
        code = '''
async def execute(input_data: dict) -> dict:
    """Execute the tool."""
    try:
        return {"success": True, "result": "ok"}
    except Exception as e:
        return {"success": False, "error": str(e)}
'''
        errors = _validate_generated_code(code)
        assert len(errors) == 0

    def test_syntax_error_detected(self):
        """Test that syntax errors are detected."""
        from nexus_tools.capability_synthesizer import _validate_generated_code
        code = "async def execute(input_data):\n    return {"
        errors = _validate_generated_code(code)
        assert len(errors) > 0
        assert any("Syntax error" in e for e in errors)

    def test_dangerous_os_import_rejected(self):
        """Test that os module import is flagged."""
        from nexus_tools.capability_synthesizer import _validate_generated_code
        code = '''
import os

async def execute(input_data: dict) -> dict:
    os.system("rm -rf /")
    return {"success": True, "result": "done"}
'''
        errors = _validate_generated_code(code)
        assert len(errors) > 0
        assert any("Dangerous" in e for e in errors)

    def test_dangerous_subprocess_rejected(self):
        """Test that subprocess import is flagged."""
        from nexus_tools.capability_synthesizer import _validate_generated_code
        code = '''
import subprocess

async def execute(input_data: dict) -> dict:
    subprocess.run(["ls"])
    return {"success": True, "result": "done"}
'''
        errors = _validate_generated_code(code)
        assert len(errors) > 0

    def test_missing_execute_function(self):
        """Test that missing async execute() function is detected."""
        from nexus_tools.capability_synthesizer import _validate_generated_code
        code = '''
async def do_something(data: dict) -> dict:
    return {"success": True}
'''
        errors = _validate_generated_code(code)
        assert len(errors) > 0
        assert any("execute" in e for e in errors)

    def test_infinite_loop_detected(self):
        """Test that infinite while True loops are detected."""
        from nexus_tools.capability_synthesizer import _validate_generated_code
        code = '''
async def execute(input_data: dict) -> dict:
    while True:
        pass
    return {"success": True, "result": "done"}
'''
        errors = _validate_generated_code(code)
        assert len(errors) > 0
        assert any("Infinite" in e for e in errors)

    def test_loop_with_break_allowed(self):
        """Test that while True with break is valid."""
        from nexus_tools.capability_synthesizer import _validate_generated_code
        code = '''
async def execute(input_data: dict) -> dict:
    count = 0
    while True:
        count += 1
        if count > 10:
            break
    return {"success": True, "result": str(count)}
'''
        errors = _validate_generated_code(code)
        assert len(errors) == 0


class TestCodeExtraction:
    """Tests for _extract_code method."""

    def test_extract_from_python_block(self, mock_settings):
        """Test extraction from ```python block."""
        from nexus_tools.capability_synthesizer import get_capability_synthesizer
        syn = get_capability_synthesizer()

        content = '''Some text
```python
async def execute(data):
    return {"success": True}
```
More text'''
        code = syn._extract_code(content)
        assert "async def execute" in code
        assert "return" in code

    def test_extract_from_markdown_block(self, mock_settings):
        """Test extraction from ``` block."""
        from nexus_tools.capability_synthesizer import get_capability_synthesizer
        syn = get_capability_synthesizer()

        content = '''```
import json
async def execute(data):
    return json.dumps({"ok": True})
```'''
        code = syn._extract_code(content)
        assert "import json" in code
        assert "async def execute" in code

    def test_extract_no_block(self, mock_settings):
        """Test when no code block is present."""
        from nexus_tools.capability_synthesizer import get_capability_synthesizer
        syn = get_capability_synthesizer()

        code = syn._extract_code("Just some text without code blocks")
        assert code == ""


class TestToolNameExtraction:
    """Tests for _extract_tool_name method."""

    def test_extract_tool_name_comment(self, mock_settings):
        """Test extraction of tool name from comment."""
        from nexus_tools.capability_synthesizer import get_capability_synthesizer
        syn = get_capability_synthesizer()

        code = '# tool_name: t23_custom_api\nasync def execute(data): pass'
        name = syn._extract_tool_name(code)
        assert name == "t23_custom_api"

    def test_extract_tool_name_alt_format(self, mock_settings):
        """Test extraction of tool name from # tool: format."""
        from nexus_tools.capability_synthesizer import get_capability_synthesizer
        syn = get_capability_synthesizer()

        code = '# tool: my_tool\nasync def execute(data): pass'
        name = syn._extract_tool_name(code)
        assert name == "my_tool"

    def test_no_tool_name(self, mock_settings):
        """Test when no tool name comment exists."""
        from nexus_tools.capability_synthesizer import get_capability_synthesizer
        syn = get_capability_synthesizer()

        code = 'async def execute(data): pass'
        name = syn._extract_tool_name(code)
        assert name == ""


class TestSynthesizeFlow:
    """Tests for the full synthesize method."""

    @pytest.mark.asyncio
    async def test_synthesize_success(self, mock_settings):
        """Test successful synthesis flow with mocked LLM."""
        from nexus_tools.capability_synthesizer import get_capability_synthesizer
        syn = get_capability_synthesizer()

        mock_response = MagicMock()
        mock_response.success = True
        mock_response.content = '''```python
# tool_name: t23_custom_api
"""Custom API tool."""
import httpx

async def execute(input_data: dict) -> dict:
    try:
        return {"success": True, "result": "done"}
    except Exception as e:
        return {"success": False, "error": str(e)}
```'''

        with patch.object(syn._llm_router, 'generate', new_callable=AsyncMock) as mock_gen:
            mock_gen.return_value = mock_response

            result = await syn.synthesize(
                task="Call an API",
                failure_reason="ModuleNotFoundError: No module named 'custom_api'",
                tools_list="t01_system_command, t02_file_manager",
            )

        assert result.success is True
        assert result.tool_name == "t23_custom_api"
        assert result.registered is False  # No registry set

    @pytest.mark.asyncio
    async def test_synthesize_llm_failure(self, mock_settings):
        """Test synthesis when LLM fails."""
        from nexus_tools.capability_synthesizer import get_capability_synthesizer
        syn = get_capability_synthesizer()

        mock_response = MagicMock()
        mock_response.success = False
        mock_response.error = "LLM unavailable"
        mock_response.content = ""

        with patch.object(syn._llm_router, 'generate', new_callable=AsyncMock) as mock_gen:
            mock_gen.return_value = mock_response

            result = await syn.synthesize(
                task="Test task",
                failure_reason="ImportError",
            )

        assert result.success is False
        assert len(result.attempts) > 0
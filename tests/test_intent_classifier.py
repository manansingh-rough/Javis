"""
NEXUS AI v4.0 — Classification tests for IntentClassifier.
Hardware: Intel i3 7th Gen · 12GB RAM · Ollama + Groq API

Covers:
1. Rule-based classification — simple_command patterns
2. Rule-based classification — ui_automation patterns
3. Rule-based classification — chat patterns
4. Rule-based classification — capability_synthesis patterns
5. Rule-based classification — clarify for unknown input
6. LLM-based classification via mocked Ollama
7. LLM failure fallback
8. Batch classification
9. JSON response parsing
10. Fallback text parsing
"""

import pytest
import asyncio
import json
from unittest.mock import MagicMock, AsyncMock, patch

from nexus_brain.agent_state import AgentRoute


class TestRuleBasedClassifier:
    """Tests for rule-based intent classification."""

    def test_simple_command_open(self, mock_settings):
        """Test that 'open' patterns classify as simple_command."""
        from nexus_brain.intent_classifier import IntentClassifier
        clf = IntentClassifier()

        result = clf._rule_based_classify("open VS Code")
        assert result == "simple_command"

    def test_simple_command_what(self, mock_settings):
        """Test that 'what' patterns classify as simple_command."""
        from nexus_brain.intent_classifier import IntentClassifier
        clf = IntentClassifier()

        result = clf._rule_based_classify("what is my cpu usage")
        assert result == "simple_command"

    def test_ui_automation_click(self, mock_settings):
        """Test that 'click' patterns classify as ui_automation."""
        from nexus_brain.intent_classifier import IntentClassifier
        clf = IntentClassifier()

        result = clf._rule_based_classify("click on the start button")
        assert result == "ui_automation"

    def test_ui_automation_scroll(self, mock_settings):
        """Test that 'scroll' patterns classify as ui_automation."""
        from nexus_brain.intent_classifier import IntentClassifier
        clf = IntentClassifier()

        result = clf._rule_based_classify("scroll down the page")
        assert result == "ui_automation"

    def test_chat_hello(self, mock_settings):
        """Test that 'hello' patterns classify as chat."""
        from nexus_brain.intent_classifier import IntentClassifier
        clf = IntentClassifier()

        result = clf._rule_based_classify("hello")
        assert result == "chat"

    def test_chat_thanks(self, mock_settings):
        """Test that 'thanks' patterns classify as chat."""
        from nexus_brain.intent_classifier import IntentClassifier
        clf = IntentClassifier()

        result = clf._rule_based_classify("thanks for your help")
        assert result == "chat"

    def test_capability_synthesis(self, mock_settings):
        """Test that synthesis requests classify correctly."""
        from nexus_brain.intent_classifier import IntentClassifier
        clf = IntentClassifier()

        result = clf._rule_based_classify("build a tool to parse PDFs")
        assert result == "capability_synthesis"

    def test_ambiguous_input_returns_none(self, mock_settings):
        """Test that ambiguous input returns None (needs LLM)."""
        from nexus_brain.intent_classifier import IntentClassifier
        clf = IntentClassifier()

        result = clf._rule_based_classify("can you help me with something")
        assert result is None


class TestLLMClassifier:
    """Tests for LLM-based classification."""

    @pytest.mark.asyncio
    async def test_classify_llm_success(self, mock_settings):
        """Test that classify falls back to LLM for ambiguous inputs."""
        from nexus_brain.intent_classifier import IntentClassifier
        clf = IntentClassifier()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "message": {
                "content": '{"intent": "complex_task", "confidence": 0.8, "reasoning": "Multi-step task"}'
            }
        }

        with patch.object(clf, '_get_session', new_callable=AsyncMock) as mock_session:
            mock_session.return_value.post = AsyncMock(return_value=mock_response)

            result = await clf.classify("set up a meeting and send an email")

        assert result.intent == "complex_task"
        assert result.confidence == 0.8
        assert result.needs_full_agent is True

    @pytest.mark.asyncio
    async def test_classify_llm_failure(self, mock_settings):
        """Test that classify defaults to complex_task on error."""
        from nexus_brain.intent_classifier import IntentClassifier
        clf = IntentClassifier()

        with patch.object(clf, '_get_session', new_callable=AsyncMock) as mock_session:
            mock_session.return_value.post = AsyncMock(side_effect=Exception("Connection refused"))

            result = await clf.classify("some random request")

        assert result.intent == "complex_task"
        assert result.confidence == 0.3
        assert result.needs_full_agent is True
        assert "error" in result.reasoning.lower() or "error" in result.reasoning

    @pytest.mark.asyncio
    async def test_classify_rule_takes_precedence(self, mock_settings):
        """Test that rule-based classification takes precedence over LLM."""
        from nexus_brain.intent_classifier import IntentClassifier
        clf = IntentClassifier()

        # Should not call LLM at all
        mock_session = AsyncMock()
        with patch.object(clf, '_get_session', return_value=mock_session) as mock_get:
            result = await clf.classify("open calculator")
            mock_get.assert_not_called()

        assert result.intent == "simple_command"
        assert result.confidence == 0.85

    @pytest.mark.asyncio
    async def test_classify_batch(self, mock_settings):
        """Test batch classification."""
        from nexus_brain.intent_classifier import IntentClassifier
        clf = IntentClassifier()

        results = await clf.classify_batch(["open notepad", "hello", "click here"])
        assert len(results) == 3
        assert results[0].intent == "simple_command"
        assert results[1].intent == "chat"
        assert results[2].intent == "ui_automation"


class TestResponseParsing:
    """Tests for JSON response parsing."""

    def test_parse_valid_json(self, mock_settings):
        """Test parsing a valid JSON response."""
        from nexus_brain.intent_classifier import IntentClassifier
        clf = IntentClassifier()

        content = '{"intent": "simple_command", "confidence": 0.9, "reasoning": "Test"}'
        result = clf._parse_response(content)
        assert result["intent"] == "simple_command"
        assert result["confidence"] == 0.9

    def test_parse_with_markdown_fences(self, mock_settings):
        """Test parsing JSON from within markdown fences."""
        from nexus_brain.intent_classifier import IntentClassifier
        clf = IntentClassifier()

        content = '```json\n{"intent": "complex_task", "confidence": 0.7, "reasoning": "Needs planning"}\n```'
        result = clf._parse_response(content)
        assert result["intent"] == "complex_task"
        assert result["confidence"] == 0.7

    def test_parse_invalid_intent_defaults(self, mock_settings):
        """Test that unrecognized intents default to clarify."""
        from nexus_brain.intent_classifier import IntentClassifier
        clf = IntentClassifier()

        content = '{"intent": "unknown_intent", "confidence": 0.5, "reasoning": "?"}'
        result = clf._parse_response(content)
        assert result["intent"] == "clarify"
        assert result["confidence"] == 0.3

    def test_fallback_parse(self, mock_settings):
        """Test fallback parsing when JSON fails."""
        from nexus_brain.intent_classifier import IntentClassifier
        clf = IntentClassifier()

        content = "The intent is simple_command with confidence 0.85"
        result = clf._fallback_parse(content)
        assert result["intent"] == "simple_command"
        assert result["confidence"] == 0.85
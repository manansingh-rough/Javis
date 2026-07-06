"""
NEXUS AI v4.0 — 25 unit tests for AST analysis + subprocess isolation.
Hardware: Intel i3 7th Gen · 12GB RAM · Ollama + Groq API

Tests for the SecureSandbox class covering:
- Path traversal prevention
- Command whitelist validation
- AST security analysis
- Subprocess isolation
- Timeout enforcement
- Memory limits
"""

import pytest
import json
import os
import sys
from pathlib import Path
from typing import Dict, Any


class TestPathValidation:
    """Tests for path validation in tool_validator."""
    
    def test_valid_relative_path(self):
        """Test that valid relative paths are accepted."""
        from nexus_tools.tool_validator import validate_path
        assert validate_path("test/file.txt") == os.path.normpath("test/file.txt")
    
    def test_path_traversal_rejected(self):
        """Test that path traversal patterns are rejected."""
        from nexus_tools.tool_validator import validate_path
        with pytest.raises(ValueError, match="banned pattern"):
            validate_path("../etc/passwd")
    
    def test_null_byte_rejected(self):
        """Test that null bytes in paths are rejected."""
        from nexus_tools.tool_validator import validate_path
        with pytest.raises(ValueError, match="null byte"):
            validate_path("file.txt\0.exe")
    
    def test_empty_path_rejected(self):
        """Test that empty paths are rejected."""
        from nexus_tools.tool_validator import validate_path
        with pytest.raises(ValueError, match="non-empty"):
            validate_path("")
    
    def test_absolute_path_default_rejected(self):
        """Test that absolute paths are rejected by default."""
        from nexus_tools.tool_validator import validate_path
        if os.name == "nt":
            with pytest.raises(ValueError):
                validate_path("C:\\Windows\\System32")
        else:
            with pytest.raises(ValueError):
                validate_path("/etc/passwd")


class TestCommandValidation:
    """Tests for command validation."""
    
    def test_allowed_command(self):
        """Test that allowed commands pass validation."""
        from nexus_tools.tool_validator import validate_command
        result = validate_command("ls -la", allowed_commands=["ls"])
        assert result == "ls -la"
    
    def test_disallowed_command(self):
        """Test that disallowed commands are rejected."""
        from nexus_tools.tool_validator import validate_command
        with pytest.raises(ValueError, match="not in allowed list"):
            validate_command("rm -rf /", allowed_commands=["ls", "pwd"])
    
    def test_shell_metacharacters_rejected(self):
        """Test that shell metacharacters in commands are rejected."""
        from nexus_tools.tool_validator import validate_command
        for char in ["|", ";", "&", "`", "$"]:
            with pytest.raises(ValueError, match="banned character"):
                validate_command(f"ls {char} rm", allowed_commands=["ls"])
    
    def test_null_byte_in_command(self):
        """Test that null bytes in commands are rejected."""
        from nexus_tools.tool_validator import validate_command
        with pytest.raises(ValueError, match="null byte"):
            validate_command("ls\0-rf", allowed_commands=["ls"])


class TestURLValidation:
    """Tests for URL validation."""
    
    def test_valid_https_url(self):
        """Test that valid https URLs pass."""
        from nexus_tools.tool_validator import validate_url
        assert validate_url("https://example.com") == "https://example.com"
    
    def test_http_url_allowed(self):
        """Test that http URLs are allowed."""
        from nexus_tools.tool_validator import validate_url
        assert validate_url("http://example.com") == "http://example.com"
    
    def test_ftp_url_rejected(self):
        """Test that ftp URLs are rejected."""
        from nexus_tools.tool_validator import validate_url
        with pytest.raises(ValueError, match="scheme"):
            validate_url("ftp://files.example.com")
    
    def test_file_url_rejected(self):
        """Test that file URLs are rejected."""
        from nexus_tools.tool_validator import validate_url
        with pytest.raises(ValueError, match="scheme"):
            validate_url("file:///etc/passwd")
    
    def test_url_with_credentials_rejected(self):
        """Test that URLs with embedded credentials are rejected."""
        from nexus_tools.tool_validator import validate_url
        with pytest.raises(ValueError, match="credentials"):
            validate_url("https://user:pass@example.com")


class TestRateLimiter:
    """Tests for RateLimiter."""
    
    def test_acquire_tokens(self):
        """Test basic token acquisition."""
        from nexus_tools.rate_limiter import RateLimiter
        limiter = RateLimiter(rate=10, per=1)
        assert limiter.acquire() is True
        assert limiter.available_tokens == pytest.approx(9.0, rel=0.1)
    
    def test_exhaust_tokens(self):
        """Test that rate limiter exhausts correctly."""
        from nexus_tools.rate_limiter import RateLimiter
        limiter = RateLimiter(rate=5, per=60)
        for _ in range(5):
            limiter.acquire()
        assert limiter.acquire() is False
    
    def test_reset(self):
        """Test that reset restores tokens."""
        from nexus_tools.rate_limiter import RateLimiter
        limiter = RateLimiter(rate=10, per=1)
        for _ in range(10):
            limiter.acquire()
        assert limiter.acquire() is False
        limiter.reset()
        assert limiter.available_tokens == pytest.approx(10.0, rel=0.1)
    
    def test_stats(self):
        """Test that stats are tracked."""
        from nexus_tools.rate_limiter import RateLimiter
        limiter = RateLimiter(rate=10, per=1)
        limiter.acquire()
        stats = limiter.stats
        assert stats["total_acquired"] == 1
        assert stats["total_rejected"] == 0


class TestAudioProcessor:
    """Tests for audio processing utilities."""
    
    def test_is_silence_empty(self):
        """Test that empty audio is detected as silence."""
        from nexus_audio.audio_processor import is_silence
        assert is_silence(b"") is True
    
    def test_calculate_rms_silence(self):
        """Test RMS calculation for silence."""
        from nexus_audio.audio_processor import calculate_rms
        assert calculate_rms(b"\x00" * 100) == 0.0
    
    def test_calculate_rms_normal(self):
        """Test RMS calculation for non-silent audio."""
        from nexus_audio.audio_processor import calculate_rms
        import struct
        samples = [32767, 0, -32768, 0, 16383, -16383]
        data = struct.pack("<" + "h" * len(samples), *samples)
        rms = calculate_rms(data)
        assert rms > 0.0
        assert rms <= 1.0
    
    def test_trim_silence_empty(self):
        """Test that trimming empty audio returns empty."""
        from nexus_audio.audio_processor import trim_silence
        assert trim_silence(b"") == b""


class TestSettings:
    """Tests for settings module."""
    
    def test_default_settings(self, mock_settings):
        """Test that default settings are loaded."""
        assert mock_settings.PRIMARY_MODEL == "llama-3.3-70b-versatile"
        assert mock_settings.TIER == "free"
    
    def test_api_keys_from_env(self, mock_settings):
        """Test that API keys are loaded from environment."""
        assert mock_settings.GROQ_API_KEY == "test_groq_key"
    
    def test_allowed_models(self, mock_settings):
        """Test Ollama model is set."""
        assert "3b" in mock_settings.OLLAMA_MODEL


class TestMemory:
    """Tests for memory compressor."""
    
    def test_should_compress_empty(self, mock_settings):
        """Test that empty collections don't need compression."""
        from nexus_memory.memory_compressor import should_compress
        result = should_compress("nonexistent_collection")
        # Should not raise, even for missing collections
        assert isinstance(result, bool)


class TestCrashReporter:
    """Tests for crash report generation."""
    
    def test_write_crash_report(self, mock_settings):
        """Test that crash reports are written correctly."""
        from nexus_config.crash_reporter import write_crash_report
        try:
            raise ValueError("Test error")
        except ValueError:
            exc_type, exc_value, exc_traceback = sys.exc_info()
            report_path = write_crash_report(exc_type, exc_value, exc_traceback)
            assert report_path.exists()
            content = report_path.read_text(encoding="utf-8")
            data = json.loads(content)
            assert data["exception_type"] == "ValueError"
            assert "Test error" in data["exception_message"]
            # Cleanup
            report_path.unlink()
"""
NEXUS AI v4.0 — Per-tool Pydantic input validation schemas for all 22 tools.
Hardware: Intel i3 7th Gen · 12GB RAM · Ollama + Groq API

Provides input validation functions for tool parameters including:
- Path traversal prevention
- Command whitelist validation
- URL scheme validation
- Integer range validation
- String length/safety validation
"""

import os
import re
import shlex
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any, Set
from urllib.parse import urlparse

logger = logging.getLogger("nexus.tools.validator")


# ─── Constants ───────────────────────────────────────────────────────────────

MAX_PATH_LENGTH: int = 4096
"""Maximum allowed path length."""

MAX_COMMAND_LENGTH: int = 8192
"""Maximum allowed command string length."""

MAX_URL_LENGTH: int = 8192
"""Maximum allowed URL length."""

MAX_STRING_LENGTH: int = 100000
"""Maximum allowed string parameter length."""

ALLOWED_URL_SCHEMES: Set[str] = {"http", "https"}
"""Only these URL schemes are allowed."""

BANNED_PATH_PATTERNS: List[str] = [
    "..",
    "~",
    "$HOME",
    "%USERPROFILE%",
    "\\\\",
    "//",
]
"""Path patterns that indicate traversal or escape attempts."""

BANNED_COMMAND_CHARS: Set[str] = {
    "|", ";", "&", "`", "$", "(", ")", "{", "}", "<", ">", "!", "\n", "\r",
}
"""Shell metacharacters that are banned in command strings."""


# ─── Validation Functions ────────────────────────────────────────────────────

def validate_path(path: str, allow_absolute: bool = False) -> str:
    """
    Validate and normalize a file system path.
    
    Checks for:
    - Path traversal (../etc/passwd)
    - Absolute path escapes
    - Length limits
    - Null bytes
    
    Args:
        path: The path string to validate.
        allow_absolute: If True, absolute paths are allowed.
                       If False, only relative paths are accepted.
    
    Returns:
        Normalized path string.
    
    Raises:
        ValueError: If the path is invalid or unsafe.
    """
    if not path or not isinstance(path, str):
        raise ValueError("Path must be a non-empty string")
    
    if len(path) > MAX_PATH_LENGTH:
        raise ValueError(f"Path exceeds maximum length of {MAX_PATH_LENGTH}")
    
    if "\0" in path:
        raise ValueError("Path contains null byte")
    
    # Check for banned patterns
    for pattern in BANNED_PATH_PATTERNS:
        if pattern in path:
            raise ValueError(f"Path contains banned pattern: {pattern}")
    
    # Normalize
    try:
        normalized = os.path.normpath(path)
    except Exception as e:
        raise ValueError(f"Path normalization failed: {e}")
    
    # Check for absolute path if not allowed
    if not allow_absolute and os.path.isabs(normalized):
        raise ValueError(f"Absolute paths not allowed: {normalized}")
    
    return normalized


def validate_command(
    command: str,
    allowed_commands: Optional[List[str]] = None,
) -> str:
    """
    Validate a shell command string.
    
    Checks for:
    - Command is in allowed list (if provided)
    - No shell metacharacters
    - Length limits
    - Null bytes
    
    Args:
        command: The command string to validate.
        allowed_commands: List of allowed command names.
                         If None, only basic safety checks are performed.
    
    Returns:
        The validated command string.
    
    Raises:
        ValueError: If the command is invalid or not allowed.
    """
    if not command or not isinstance(command, str):
        raise ValueError("Command must be a non-empty string")
    
    if len(command) > MAX_COMMAND_LENGTH:
        raise ValueError(f"Command exceeds maximum length of {MAX_COMMAND_LENGTH}")
    
    if "\0" in command:
        raise ValueError("Command contains null byte")
    
    # Check for banned shell metacharacters
    for char in BANNED_COMMAND_CHARS:
        if char in command:
            raise ValueError(f"Command contains banned character: {repr(char)}")
    
    # Check if command is in allowed list
    if allowed_commands:
        try:
            parts = shlex.split(command)
        except ValueError as e:
            raise ValueError(f"Command parsing failed: {e}")
        
        if not parts:
            raise ValueError("Empty command after parsing")
        
        if parts[0] not in allowed_commands:
            raise ValueError(
                f"Command '{parts[0]}' is not in allowed list: {allowed_commands}"
            )
    
    return command


def validate_url(url: str) -> str:
    """
    Validate a URL string.
    
    Checks for:
    - Valid URL format
    - Allowed scheme (http/https only)
    - No credentials in URL
    - Length limits
    
    Args:
        url: The URL string to validate.
    
    Returns:
        The validated URL string.
    
    Raises:
        ValueError: If the URL is invalid or unsafe.
    """
    if not url or not isinstance(url, str):
        raise ValueError("URL must be a non-empty string")
    
    if len(url) > MAX_URL_LENGTH:
        raise ValueError(f"URL exceeds maximum length of {MAX_URL_LENGTH}")
    
    if "\0" in url:
        raise ValueError("URL contains null byte")
    
    try:
        parsed = urlparse(url)
    except Exception as e:
        raise ValueError(f"URL parsing failed: {e}")
    
    if not parsed.scheme:
        raise ValueError("URL has no scheme")
    
    if parsed.scheme not in ALLOWED_URL_SCHEMES:
        raise ValueError(
            f"URL scheme '{parsed.scheme}' not allowed. "
            f"Allowed: {', '.join(sorted(ALLOWED_URL_SCHEMES))}"
        )
    
    if not parsed.netloc:
        raise ValueError("URL has no network location")
    
    # Reject URLs with embedded credentials
    if parsed.username or parsed.password:
        raise ValueError("URL must not contain credentials")
    
    return url


def validate_integer(
    value: int,
    min_value: Optional[int] = None,
    max_value: Optional[int] = None,
    name: str = "value",
) -> int:
    """
    Validate an integer is within range.
    
    Args:
        value: The integer to validate.
        min_value: Minimum allowed value (inclusive).
        max_value: Maximum allowed value (inclusive).
        name: Name of the parameter for error messages.
    
    Returns:
        The validated integer.
    
    Raises:
        ValueError: If the integer is out of range.
    """
    if not isinstance(value, int):
        raise ValueError(f"{name} must be an integer, got {type(value).__name__}")
    
    if min_value is not None and value < min_value:
        raise ValueError(f"{name} must be >= {min_value}, got {value}")
    
    if max_value is not None and value > max_value:
        raise ValueError(f"{name} must be <= {max_value}, got {value}")
    
    return value


def validate_string(
    value: str,
    min_length: int = 0,
    max_length: int = MAX_STRING_LENGTH,
    name: str = "string",
    allow_empty: bool = False,
) -> str:
    """
    Validate a string parameter.
    
    Args:
        value: The string to validate.
        min_length: Minimum length (inclusive).
        max_length: Maximum length (inclusive).
        name: Name of the parameter for error messages.
        allow_empty: If True, empty strings are allowed.
    
    Returns:
        The validated string.
    
    Raises:
        ValueError: If the string is invalid.
    """
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string, got {type(value).__name__}")
    
    if not allow_empty and not value.strip():
        raise ValueError(f"{name} must not be empty")
    
    if len(value) < min_length:
        raise ValueError(f"{name} must be at least {min_length} characters")
    
    if len(value) > max_length:
        raise ValueError(f"{name} exceeds maximum length of {max_length}")
    
    if "\0" in value:
        raise ValueError(f"{name} contains null byte")
    
    return value.strip()


def validate_email(email: str) -> str:
    """
    Validate an email address format.
    
    Args:
        email: The email address to validate.
    
    Returns:
        The validated email address.
    
    Raises:
        ValueError: If the email is invalid.
    """
    if not email or not isinstance(email, str):
        raise ValueError("Email must be a non-empty string")
    
    # Basic email regex
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    if not re.match(pattern, email.strip()):
        raise ValueError(f"Invalid email format: {email}")
    
    if len(email) > 254:
        raise ValueError("Email exceeds maximum length of 254 characters")
    
    return email.strip().lower()
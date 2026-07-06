"""
NEXUS AI v4.0 — Tool 11: Advanced clipboard management.
Hardware: Intel i3 7th Gen · 12GB RAM · Ollama + Groq API

Reads from and writes to the system clipboard, with optional history tracking.
"""

import json
import logging
import time
from typing import Optional, List, Dict, Any

logger = logging.getLogger("nexus.tool.clipboard_manager")

# ─── In-memory clipboard history ─────────────────────────────────────────────
_clipboard_history: List[str] = []
_MAX_HISTORY: int = 20


def clipboard_manager(
    action: str,
    text: Optional[str] = None,
) -> str:
    """
    Read from and write to the system clipboard.
    
    Use this tool when: The user needs to copy text to clipboard, paste from
    clipboard, or check clipboard contents.
    
    Args:
        action: One of: "read", "write", "history", "clear"
        text: Text to write to clipboard (for "write" action).
    
    Returns:
        JSON string with keys:
          - success (bool): Whether the operation succeeded.
          - result (str or list): Clipboard content for "read"/"history", or confirmation.
          - error (str or null): Error message if failed.
    
    Examples:
        >>> clipboard_manager("read")
        >>> clipboard_manager("write", text="Hello, clipboard!")
        >>> clipboard_manager("history")
    """
    start = time.perf_counter()
    
    try:
        import pyperclip
        
        if action == "read":
            content = pyperclip.paste()
            return json.dumps({
                "success": True,
                "result": content,
                "error": None,
                "metadata": {"length": len(content) if content else 0}
            })
        
        elif action == "write":
            if text is None:
                return json.dumps({"success": False, "result": None, "error": "Text required for write action"})
            
            pyperclip.copy(text)
            # Add to history
            _clipboard_history.append(text)
            if len(_clipboard_history) > _MAX_HISTORY:
                _clipboard_history.pop(0)
            
            return json.dumps({
                "success": True,
                "result": f"Copied {len(text)} characters to clipboard",
                "error": None,
                "metadata": {"length": len(text)}
            })
        
        elif action == "history":
            return json.dumps({
                "success": True,
                "result": list(reversed(_clipboard_history)),
                "error": None,
                "metadata": {"count": len(_clipboard_history)}
            })
        
        elif action == "clear":
            pyperclip.copy("")
            _clipboard_history.clear()
            return json.dumps({
                "success": True,
                "result": "Clipboard cleared",
                "error": None
            })
        
        else:
            return json.dumps({
                "success": False, "result": None,
                "error": f"Unknown action: '{action}'. Valid: read, write, history, clear"
            })
    
    except ImportError:
        return json.dumps({
            "success": False, "result": None,
            "error": "pyperclip not installed. Install with: pip install pyperclip"
        })
    except Exception as e:
        logger.error(f"clipboard_manager error: {e}", exc_info=True)
        return json.dumps({
            "success": False, "result": None,
            "error": f"{type(e).__name__}: {e}"
        })
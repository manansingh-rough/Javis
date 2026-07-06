"""
NEXUS AI v4.0 — Tool 20: Desktop notifications via plyer.
Hardware: Intel i3 7th Gen · 12GB RAM · Ollama + Groq API

Sends cross-platform desktop notifications with optional actions.
"""

import json
import logging
import time
from typing import Optional, List, Dict, Any

logger = logging.getLogger("nexus.tool.notification_sender")


def notification_sender(
    title: str,
    message: str,
    app_name: str = "NEXUS AI",
    timeout: int = 5,
    sound: bool = False,
) -> str:
    """
    Send a desktop notification to the user.
    
    Use this tool when: The user is away from the agent window and needs to be
    alerted about task completion, errors, or important information.
    
    Args:
        title: Notification title (bold heading).
        message: Notification body text.
        app_name: Application name shown in notification. Default "NEXUS AI".
        timeout: Seconds before notification auto-dismisses (2-30).
        sound: Whether to play a notification sound.
    
    Returns:
        JSON string with keys:
          - success (bool): Whether the notification was sent.
          - result (str): Confirmation message.
          - error (str or null): Error message if failed.
    
    Examples:
        >>> notification_sender("Task Complete", "Your report has been generated")
        >>> notification_sender("Error", "Build failed", timeout=10, sound=True)
    """
    start = time.perf_counter()
    timeout = min(max(timeout, 2), 30)
    
    try:
        from plyer import notification
        
        notification.notify(
            title=title,
            message=message,
            app_name=app_name,
            timeout=timeout,
        )
        
        # Play sound if requested
        if sound:
            try:
                import winsound
                winsound.MessageBeep()
            except ImportError:
                try:
                    import subprocess
                    if sys.platform == "darwin":
                        subprocess.run(["afplay", "/System/Library/Sounds/Tink.aiff"], 
                                      capture_output=True, timeout=2)
                except Exception:
                    pass
        
        return json.dumps({
            "success": True,
            "result": f"Notification sent: {title}",
            "error": None,
            "metadata": {"title": title, "timeout": timeout, "sound": sound}
        })
    
    except ImportError:
        return json.dumps({
            "success": False, "result": None,
            "error": "plyer not installed. Install with: pip install plyer"
        })
    except Exception as e:
        logger.error(f"notification_sender error: {e}", exc_info=True)
        return json.dumps({
            "success": False, "result": None,
            "error": f"{type(e).__name__}: {e}"
        })
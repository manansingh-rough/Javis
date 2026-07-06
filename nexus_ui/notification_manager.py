"""
NEXUS AI v4.0 — System tray + in-app toast notification manager.
Hardware: Intel i3 7th Gen · 12GB RAM · Ollama + Groq API

Provides cross-platform desktop notifications via plyer,
with in-app toast fallback when native notifications are unavailable.
"""

import logging
import queue
import threading
import time
from typing import Optional, Dict, Any, Callable
from dataclasses import dataclass, field
from functools import lru_cache
from enum import Enum

from nexus_config.settings import get_settings

logger = logging.getLogger("nexus.ui.notifications")


class NotificationPriority(Enum):
    """Notification priority levels."""
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class Notification:
    """A notification to be displayed."""
    title: str
    message: str
    priority: NotificationPriority = NotificationPriority.NORMAL
    timeout_ms: int = 5000
    sound: Optional[str] = None
    callback: Optional[Callable[[], None]] = None
    timestamp: float = field(default_factory=time.time)


class NotificationManager:
    """
    Manages desktop and in-app notifications.
    
    Uses plyer for native notifications when available.
    Falls back to in-app toast display when native is unavailable.
    All notifications are queued and displayed on the UI thread.
    """
    
    def __init__(self):
        self._settings = get_settings()
        self._notification_queue: queue.Queue = queue.Queue()
        self._active_notifications: list = []
        self._max_visible: int = 3
        self._toast_callback: Optional[Callable[[Notification], None]] = None
        
        # Try to initialize plyer
        self._plyer_available = False
        try:
            from plyer import notification as plyer_notification
            self._plyer_notification = plyer_notification
            self._plyer_available = True
        except Exception:
            self._plyer_available = False
    
    def set_toast_callback(self, callback: Callable[[Notification], None]) -> None:
        """
        Set callback for in-app toast display.
        
        Args:
            callback: Function that receives a Notification and displays it in the UI.
        """
        self._toast_callback = callback
    
    def notify(
        self,
        title: str,
        message: str,
        priority: NotificationPriority = NotificationPriority.NORMAL,
        timeout_ms: int = 5000,
        sound: Optional[str] = None,
        callback: Optional[Callable[[], None]] = None,
    ) -> None:
        """
        Send a notification.
        
        Attempts native notification first, falls back to in-app toast.
        
        Args:
            title: Notification title.
            message: Notification body text.
            priority: Priority level.
            timeout_ms: Display duration in milliseconds.
            sound: Optional sound file name to play.
            callback: Optional callback when notification is clicked.
        """
        notification = Notification(
            title=title,
            message=message,
            priority=priority,
            timeout_ms=timeout_ms,
            sound=sound,
            callback=callback,
        )
        
        # Try native notification
        if self._plyer_available:
            try:
                self._plyer_notification.notify(
                    title=title,
                    message=message,
                    timeout=timeout_ms // 1000,
                    app_name="NEXUS AI",
                )
                return
            except Exception as e:
                logger.debug(f"Native notification failed: {e}")
        
        # Fall back to in-app toast
        if self._toast_callback:
            self._notification_queue.put(notification)
    
    def process_queue(self) -> None:
        """Process pending notifications (call from UI thread)."""
        try:
            while True:
                notification = self._notification_queue.get_nowait()
                if self._toast_callback:
                    self._toast_callback(notification)
        except queue.Empty:
            pass
    
    def notify_success(self, message: str, title: str = "Success") -> None:
        """Send a success notification."""
        self.notify(title, message, priority=NotificationPriority.LOW)
    
    def notify_error(self, message: str, title: str = "Error") -> None:
        """Send an error notification."""
        self.notify(title, message, priority=NotificationPriority.HIGH)
    
    def notify_warning(self, message: str, title: str = "Warning") -> None:
        """Send a warning notification."""
        self.notify(title, message, priority=NotificationPriority.NORMAL)
    
    def notify_info(self, message: str, title: str = "NEXUS AI") -> None:
        """Send an info notification."""
        self.notify(title, message, priority=NotificationPriority.LOW)


@lru_cache(maxsize=1)
def get_notification_manager() -> NotificationManager:
    """
    Return the singleton NotificationManager instance.
    
    Returns:
        NotificationManager: The singleton notification manager.
    """
    return NotificationManager()
"""
NEXUS AI v4.0 — Tool 10: Cross-platform window management.
Hardware: Intel i3 7th Gen · 12GB RAM · Ollama + Groq API

Lists, focuses, resizes, minimizes, and manages application windows
across Windows, macOS, and Linux.
"""

import json
import logging
import time
import sys
from typing import Optional, List, Dict, Any

logger = logging.getLogger("nexus.tool.window_manager")


def window_manager(
    action: str,
    window_title: Optional[str] = None,
    x: Optional[int] = None,
    y: Optional[int] = None,
    width: Optional[int] = None,
    height: Optional[int] = None,
) -> str:
    """
    Manage desktop application windows: list, focus, resize, minimize, close.
    
    Use this tool when: The user needs to find a window, switch to an application,
    resize or move a window, minimize or restore windows.
    
    Args:
        action: One of: "list", "focus", "move", "resize", "minimize",
                "restore", "maximize", "close", "exists"
        window_title: Title (or substring) of the target window.
        x: X position for window (for "move" action).
        y: Y position for window (for "move" action).
        width: Window width (for "resize" action).
        height: Window height (for "resize" action).
    
    Returns:
        JSON string with keys:
          - success (bool): Whether the operation succeeded.
          - result (any): Action-specific result (list of windows for "list").
          - error (str or null): Error message if failed.
    
    Examples:
        >>> window_manager("list")
        >>> window_manager("focus", window_title="Notepad")
        >>> window_manager("resize", window_title="Chrome", width=1280, height=720)
    """
    start = time.perf_counter()
    
    try:
        if sys.platform == "win32":
            return _windows_window_manager(action, window_title, x, y, width, height)
        elif sys.platform == "darwin":
            return _macos_window_manager(action, window_title, x, y, width, height)
        else:
            return _linux_window_manager(action, window_title, x, y, width, height)
    
    except Exception as e:
        logger.error(f"window_manager error: {e}", exc_info=True)
        return json.dumps({
            "success": False, "result": None,
            "error": f"{type(e).__name__}: {e}"
        })


def _get_windows() -> List[Dict[str, Any]]:
    """Get list of all open windows using pygetwindow."""
    try:
        import pygetwindow as gw
        
        windows = []
        for w in gw.getWindowsWithTitle(""):
            try:
                if w.title.strip():
                    windows.append({
                        "title": w.title,
                        "x": w.left,
                        "y": w.top,
                        "width": w.width,
                        "height": w.height,
                        "is_minimized": w.isMinimized,
                        "is_maximized": w.isMaximized,
                        "is_active": w.isActive,
                    })
            except Exception:
                continue
        
        return windows
    except ImportError:
        return []


def _find_window(window_title: str):
    """Find a window by title substring."""
    import pygetwindow as gw
    try:
        windows = gw.getWindowsWithTitle(window_title)
        if windows:
            return windows[0]
        
        # Try case-insensitive search
        for w in gw.getWindowsWithTitle(""):
            try:
                if window_title.lower() in w.title.lower():
                    return w
            except Exception:
                continue
        
        return None
    except Exception:
        return None


def _windows_window_manager(action, window_title, x, y, width, height):
    """Window management on Windows."""
    try:
        import pygetwindow as gw
        
        if action == "list":
            windows = _get_windows()
            return json.dumps({
                "success": True,
                "result": windows[:100],
                "error": None,
                "metadata": {"count": len(windows), "platform": "Windows"}
            })
        
        elif action in ("focus", "move", "resize", "minimize", "restore", "maximize", "close", "exists"):
            if not window_title:
                return json.dumps({"success": False, "result": None, "error": "window_title required for this action"})
            
            win = _find_window(window_title)
            if not win:
                return json.dumps({"success": False, "result": None, "error": f"No window found matching: '{window_title}'"})
            
            if action == "exists":
                return json.dumps({"success": True, "result": True, "error": None})
            
            elif action == "focus":
                win.activate()
                return json.dumps({"success": True, "result": f"Focused: {win.title}", "error": None})
            
            elif action == "move":
                if x is None or y is None:
                    return json.dumps({"success": False, "result": None, "error": "x and y required for move action"})
                win.moveTo(x, y)
                return json.dumps({"success": True, "result": f"Moved to ({x}, {y})", "error": None})
            
            elif action == "resize":
                if width is None or height is None:
                    return json.dumps({"success": False, "result": None, "error": "width and height required for resize action"})
                win.resizeTo(width, height)
                return json.dumps({"success": True, "result": f"Resized to {width}x{height}", "error": None})
            
            elif action == "minimize":
                win.minimize()
                return json.dumps({"success": True, "result": "Window minimized", "error": None})
            
            elif action == "restore":
                win.restore()
                return json.dumps({"success": True, "result": "Window restored", "error": None})
            
            elif action == "maximize":
                win.maximize()
                return json.dumps({"success": True, "result": "Window maximized", "error": None})
            
            elif action == "close":
                win.close()
                return json.dumps({"success": True, "result": "Window closed", "error": None})
        
        else:
            return json.dumps({
                "success": False, "result": None,
                "error": f"Unknown action: '{action}'"
            })
    
    except ImportError:
        return json.dumps({
            "success": False, "result": None,
            "error": "pygetwindow not installed. Install with: pip install pygetwindow pyrect"
        })


def _macos_window_manager(action, window_title, x, y, width, height):
    """Window management on macOS using applescript."""
    import subprocess
    
    if action == "list":
        script = '''
        tell application "System Events"
            set windowList to {}
            repeat with proc in every process whose visible is true
                set procName to name of proc
                try
                    repeat with win in windows of proc
                        set winTitle to title of win
                        if winTitle is not "" then
                            set end of windowList to {name:procName, title:winTitle}
                        end if
                    end repeat
                end try
            end repeat
            return windowList
        end tell
        '''
        result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=10)
        windows = []
        for line in result.stdout.strip().split(","):
            if line.strip():
                windows.append({"title": line.strip()})
        return json.dumps({"success": True, "result": windows, "error": None, "metadata": {"platform": "macOS"}})
    
    else:
        if not window_title:
            return json.dumps({"success": False, "result": None, "error": "window_title required"})
        
        if action == "focus":
            script = f'''
            tell application "{window_title}"
                activate
            end tell
            '''
        elif action == "close":
            script = f'''
            tell application "{window_title}"
                close window 1
            end tell
            '''
        elif action == "minimize":
            script = f'''
            tell application "System Events"
                tell process "{window_title}"
                    set miniaturized of window 1 to true
                end tell
            end tell
            '''
        elif action == "restore":
            script = f'''
            tell application "System Events"
                tell process "{window_title}"
                    set miniaturized of window 1 to false
                end tell
            end tell
            '''
        else:
            return json.dumps({"success": False, "result": None, "error": f"Action '{action}' not supported on macOS"})
        
        try:
            subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=5)
            return json.dumps({"success": True, "result": f"{action} performed on {window_title}", "error": None})
        except Exception as e:
            return json.dumps({"success": False, "result": None, "error": str(e)})


def _linux_window_manager(action, window_title, x, y, width, height):
    """Window management on Linux using wmctrl."""
    import subprocess
    
    try:
        if action == "list":
            result = subprocess.run(
                ["wmctrl", "-l"],
                capture_output=True, text=True, timeout=5
            )
            windows = []
            for line in result.stdout.strip().split("\n"):
                if line:
                    parts = line.split(None, 3)
                    if len(parts) >= 4:
                        windows.append({
                            "id": parts[0],
                            "desktop": parts[1],
                            "pid": parts[2],
                            "title": parts[3],
                        })
                    elif len(parts) >= 1:
                        windows.append({"id": parts[0], "title": line})
            return json.dumps({"success": True, "result": windows, "error": None, "metadata": {"platform": "Linux"}})
        
        elif action == "focus":
            if not window_title:
                return json.dumps({"success": False, "result": None, "error": "window_title required"})
            subprocess.run(["wmctrl", "-a", window_title], capture_output=True, text=True, timeout=5)
            return json.dumps({"success": True, "result": f"Focused: {window_title}", "error": None})
        
        elif action == "close":
            if not window_title:
                return json.dumps({"success": False, "result": None, "error": "window_title required"})
            subprocess.run(["wmctrl", "-c", window_title], capture_output=True, text=True, timeout=5)
            return json.dumps({"success": True, "result": f"Closed: {window_title}", "error": None})
        
        else:
            return json.dumps({"success": False, "result": None, "error": f"Action '{action}' not supported on Linux"})
    
    except FileNotFoundError:
        return json.dumps({
            "success": False, "result": None,
            "error": "wmctrl not installed. Install with: sudo apt-get install wmctrl (or equivalent)"
        })
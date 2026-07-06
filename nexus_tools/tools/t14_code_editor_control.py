"""
NEXUS AI v4.0 — Tool 14: VS Code control and automation.
Hardware: Intel i3 7th Gen · 12GB RAM · Ollama + Groq API

Controls VS Code: open files, run commands, manage extensions,
and interact with the editor via CLI and API.
"""

import json
import logging
import time
import subprocess
import sys
from pathlib import Path
from typing import Optional, List, Dict, Any

logger = logging.getLogger("nexus.tool.code_editor_control")

# ─── Constants ────────────────────────────────────────────────────────────────
_CODE_CMD = "code" if sys.platform != "win32" else "code.cmd"


def code_editor_control(
    action: str,
    path: Optional[str] = None,
    command: Optional[str] = None,
    extension_id: Optional[str] = None,
    text: Optional[str] = None,
) -> str:
    """
    Control VS Code editor: open files, run commands, manage extensions.
    
    Use this tool when: The user asks to open a file in VS Code, run a VS Code
    command, install an extension, or perform any VS Code automation.
    
    Args:
        action: One of: "open", "open_file", "run_command", "install_extension",
                "uninstall_extension", "list_extensions", "open_folder", "diff"
        path: File or folder path to open.
        command: VS Code command to run (for "run_command" action).
        extension_id: Extension identifier (for install/uninstall).
        text: Additional text parameter (for "diff" action).
    
    Returns:
        JSON string with keys:
          - success (bool): Whether the operation succeeded.
          - result (str): Result information.
          - error (str or null): Error message if failed.
    
    Examples:
        >>> code_editor_control("open_file", path="/path/to/file.py")
        >>> code_editor_control("run_command", command="editor.action.formatDocument")
        >>> code_editor_control("list_extensions")
    """
    start = time.perf_counter()
    
    try:
        if action == "open_file":
            if not path:
                return json.dumps({"success": False, "result": None, "error": "Path required for open_file action"})
            
            p = Path(path)
            if not p.exists():
                return json.dumps({"success": False, "result": None, "error": f"File not found: {path}"})
            
            result = subprocess.run(
                [_CODE_CMD, "--goto", str(p.absolute())],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                return json.dumps({"success": True, "result": f"Opened: {path}", "error": None})
            else:
                return json.dumps({"success": False, "result": None, "error": result.stderr or "Failed to open file"})
        
        elif action == "open_folder":
            if not path:
                return json.dumps({"success": False, "result": None, "error": "Path required for open_folder action"})
            
            p = Path(path)
            if not p.exists():
                return json.dumps({"success": False, "result": None, "error": f"Folder not found: {path}"})
            
            result = subprocess.run(
                [_CODE_CMD, str(p.absolute())],
                capture_output=True, text=True, timeout=10
            )
            return json.dumps({"success": result.returncode == 0, "result": f"Opened folder: {path}", "error": result.stderr if result.returncode != 0 else None})
        
        elif action == "run_command":
            if not command:
                return json.dumps({"success": False, "result": None, "error": "Command required for run_command action"})
            
            result = subprocess.run(
                [_CODE_CMD, "--command", command],
                capture_output=True, text=True, timeout=10
            )
            return json.dumps({"success": True, "result": f"Executed command: {command}", "error": None})
        
        elif action == "install_extension":
            if not extension_id:
                return json.dumps({"success": False, "result": None, "error": "extension_id required"})
            
            result = subprocess.run(
                [_CODE_CMD, "--install-extension", extension_id],
                capture_output=True, text=True, timeout=60
            )
            if result.returncode == 0:
                return json.dumps({"success": True, "result": f"Installed extension: {extension_id}", "error": None})
            else:
                return json.dumps({"success": False, "result": None, "error": result.stderr or "Failed to install extension"})
        
        elif action == "uninstall_extension":
            if not extension_id:
                return json.dumps({"success": False, "result": None, "error": "extension_id required"})
            
            result = subprocess.run(
                [_CODE_CMD, "--uninstall-extension", extension_id],
                capture_output=True, text=True, timeout=30
            )
            return json.dumps({"success": result.returncode == 0, "result": f"Uninstalled extension: {extension_id}", "error": result.stderr if result.returncode != 0 else None})
        
        elif action == "list_extensions":
            result = subprocess.run(
                [_CODE_CMD, "--list-extensions"],
                capture_output=True, text=True, timeout=15
            )
            if result.returncode == 0:
                extensions = [e.strip() for e in result.stdout.strip().split("\n") if e.strip()]
                return json.dumps({"success": True, "result": extensions, "error": None, "metadata": {"count": len(extensions)}})
            else:
                return json.dumps({"success": False, "result": None, "error": result.stderr})
        
        elif action == "open":
            if not path:
                return json.dumps({"success": False, "result": None, "error": "Path required for open action"})
            
            p = Path(path)
            result = subprocess.run(
                [_CODE_CMD, str(p.absolute())],
                capture_output=True, text=True, timeout=10
            )
            return json.dumps({"success": True, "result": f"Opened: {path}", "error": None})
        
        elif action == "diff":
            if not path or not text:
                return json.dumps({"success": False, "result": None, "error": "Both path and text required for diff action"})
            
            result = subprocess.run(
                [_CODE_CMD, "--diff", path, text],
                capture_output=True, text=True, timeout=10
            )
            return json.dumps({"success": True, "result": "Opened diff view", "error": None})
        
        else:
            return json.dumps({
                "success": False, "result": None,
                "error": f"Unknown action: '{action}'. Valid: open, open_file, run_command, install_extension, uninstall_extension, list_extensions, open_folder, diff"
            })
    
    except FileNotFoundError:
        return json.dumps({
            "success": False, "result": None,
            "error": "VS Code 'code' command not found. Ensure VS Code is installed and in PATH."
        })
    except subprocess.TimeoutExpired:
        return json.dumps({
            "success": False, "result": None,
            "error": "VS Code command timed out"
        })
    except Exception as e:
        logger.error(f"code_editor_control error: {e}", exc_info=True)
        return json.dumps({
            "success": False, "result": None,
            "error": f"{type(e).__name__}: {e}"
        })
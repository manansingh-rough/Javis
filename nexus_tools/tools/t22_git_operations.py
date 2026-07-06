"""
NEXUS AI v4.0 — Tool 22: Git operations.
Hardware: Intel i3 7th Gen · 12GB RAM · Ollama + Groq API

Performs Git operations: status, commit, push, pull, branch, log, and diff.
All operations run in the specified repository directory.
"""

import json
import logging
import time
import subprocess
from pathlib import Path
from typing import Optional, List, Dict, Any

logger = logging.getLogger("nexus.tool.git_operations")

# ─── Constants ────────────────────────────────────────────────────────────────
GIT_TIMEOUT: int = 30


def git_operations(
    action: str,
    repo_path: str = ".",
    message: Optional[str] = None,
    branch: Optional[str] = None,
    file_paths: Optional[List[str]] = None,
    remote: str = "origin",
    max_log_entries: int = 10,
) -> str:
    """
    Perform Git operations on a repository.
    
    Use this tool when: The user asks about git status, wants to commit changes,
    push/pull from remote, create/switch branches, view log, or check diffs.
    
    Args:
        action: One of: "status", "add", "commit", "push", "pull", "branch",
                "checkout", "log", "diff", "init", "clone", "stash"
        repo_path: Path to the Git repository. Default: current directory.
        message: Commit message (required for "commit" action).
        branch: Branch name (for "branch", "checkout" actions).
        file_paths: List of file paths to add (for "add" action).
        remote: Remote name (for "push", "pull"). Default "origin".
        max_log_entries: Maximum log entries to return (1-50).
    
    Returns:
        JSON string with keys:
          - success (bool): Whether the operation succeeded.
          - result (any): Command output or structured data.
          - error (str or null): Error message if failed.
    """
    start = time.perf_counter()
    max_log_entries = min(max(max_log_entries, 1), 50)
    
    try:
        repo = Path(repo_path).resolve()
        
        if action == "init":
            if not repo.exists():
                repo.mkdir(parents=True, exist_ok=True)
            result = _run_git(["init"], repo)
            return _format_result(result, "Repository initialized")
        
        elif action == "clone":
            return json.dumps({
                "success": False, "result": None,
                "error": "Clone not supported via this tool. Use shell command instead."
            })
        
        elif action == "status":
            result = _run_git(["status", "--porcelain"], repo)
            if result["success"]:
                lines = [l for l in result["stdout"].strip().split("\n") if l.strip()]
                # Parse porcelain format
                staged = []
                unstaged = []
                untracked = []
                for line in lines:
                    if line.startswith("??"):
                        untracked.append(line[3:])
                    elif line[0] != " ":
                        staged.append(line[3:])
                    else:
                        unstaged.append(line[3:])
                
                # Get current branch
                branch_result = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], repo)
                current_branch = branch_result["stdout"].strip() if branch_result["success"] else "unknown"
                
                return json.dumps({
                    "success": True,
                    "result": {
                        "branch": current_branch,
                        "staged": staged,
                        "unstaged": unstaged,
                        "untracked": untracked,
                        "ahead_behind": _get_ahead_behind(repo, remote),
                    },
                    "error": None,
                })
            return _format_result(result)
        
        elif action == "add":
            if file_paths:
                for fp in file_paths:
                    _run_git(["add", fp], repo)
            else:
                _run_git(["add", "."], repo)
            return json.dumps({"success": True, "result": "Files staged", "error": None})
        
        elif action == "commit":
            if not message:
                return json.dumps({"success": False, "result": None, "error": "Commit message required"})
            result = _run_git(["commit", "-m", message], repo)
            return _format_result(result)
        
        elif action == "push":
            if branch:
                result = _run_git(["push", remote, branch], repo)
            else:
                result = _run_git(["push"], repo)
            return _format_result(result)
        
        elif action == "pull":
            if branch:
                result = _run_git(["pull", remote, branch], repo)
            else:
                result = _run_git(["pull"], repo)
            return _format_result(result)
        
        elif action == "branch":
            result = _run_git(["branch", "--list"], repo)
            if result["success"]:
                branches = []
                for line in result["stdout"].strip().split("\n"):
                    line = line.strip()
                    if line:
                        is_current = line.startswith("*")
                        branches.append({
                            "name": line.replace("*", "").strip(),
                            "current": is_current,
                        })
                return json.dumps({"success": True, "result": branches, "error": None})
            return _format_result(result)
        
        elif action == "checkout":
            if not branch:
                return json.dumps({"success": False, "result": None, "error": "Branch name required"})
            result = _run_git(["checkout", branch], repo)
            return _format_result(result)
        
        elif action == "log":
            result = _run_git(
                ["log", f"--max-count={max_log_entries}", "--format=%H|%an|%ae|%ar|%s"],
                repo
            )
            if result["success"]:
                commits = []
                for line in result["stdout"].strip().split("\n"):
                    if "|" in line:
                        parts = line.split("|", 4)
                        commits.append({
                            "hash": parts[0][:8],
                            "author": parts[1],
                            "email": parts[2],
                            "date": parts[3],
                            "message": parts[4] if len(parts) > 4 else "",
                        })
                return json.dumps({"success": True, "result": commits, "error": None})
            return _format_result(result)
        
        elif action == "diff":
            if file_paths:
                result = _run_git(["diff"] + file_paths, repo)
            else:
                result = _run_git(["diff"], repo)
            return _format_result(result)
        
        elif action == "stash":
            if message:
                result = _run_git(["stash", "push", "-m", message], repo)
            else:
                result = _run_git(["stash"], repo)
            return _format_result(result)
        
        else:
            return json.dumps({
                "success": False, "result": None,
                "error": f"Unknown action: '{action}'. Valid: status, add, commit, push, pull, branch, checkout, log, diff, init, stash"
            })
    
    except Exception as e:
        logger.error(f"git_operations error: {e}", exc_info=True)
        return json.dumps({
            "success": False, "result": None,
            "error": f"{type(e).__name__}: {e}"
        })


def _run_git(args: List[str], repo: Path) -> Dict[str, Any]:
    """Run a git command and return structured result."""
    try:
        result = subprocess.run(
            ["git"] + args,
            cwd=str(repo),
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT,
        )
        return {
            "success": result.returncode == 0,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode,
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "stdout": "", "stderr": "Git command timed out", "returncode": -1}
    except FileNotFoundError:
        return {"success": False, "stdout": "", "stderr": "Git not found. Install git.", "returncode": -1}


def _format_result(result: Dict[str, Any], success_msg: Optional[str] = None) -> str:
    """Format a git command result as JSON."""
    if result["success"]:
        output = result["stdout"].strip() or success_msg or "Success"
        return json.dumps({"success": True, "result": output, "error": None})
    else:
        return json.dumps({
            "success": False, "result": None,
            "error": result["stderr"].strip() or "Git command failed"
        })


def _get_ahead_behind(repo: Path, remote: str) -> Dict[str, int]:
    """Get ahead/behind counts for the current branch."""
    try:
        result = _run_git(["rev-list", "--left-right", "--count", f"{remote}/HEAD...HEAD"], repo)
        if result["success"]:
            parts = result["stdout"].strip().split("\t")
            if len(parts) == 2:
                return {"behind": int(parts[0]), "ahead": int(parts[1])}
    except Exception:
        pass
    return {"ahead": 0, "behind": 0}
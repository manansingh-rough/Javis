"""
NEXUS AI v4.0 — Tool 19: Process management via psutil.
Hardware: Intel i3 7th Gen · 12GB RAM · Ollama + Groq API

Lists, kills, launches, and monitors system processes with safety constraints.
"""

import json
import logging
import time
import os
import sys
import signal
from typing import Optional, List, Dict, Any

logger = logging.getLogger("nexus.tool.process_manager")


def process_manager(
    action: str,
    pid: Optional[int] = None,
    name: Optional[str] = None,
    command: Optional[str] = None,
    args: Optional[List[str]] = None,
    signal_type: str = "terminate",
) -> str:
    """
    Manage system processes: list, kill, launch, and monitor.
    
    Use this tool when: The user asks about running processes, wants to kill
    a process, launch an application, or check process resource usage.
    
    Args:
        action: One of: "list", "kill", "launch", "info", "search", "tree"
        pid: Process ID (for "kill", "info" actions).
        name: Process name substring (for "search", "kill" by name).
        command: Command to launch (for "launch" action).
        args: List of command-line arguments (for "launch" action).
        signal_type: Signal type for kill: "terminate" (SIGTERM), "kill" (SIGKILL),
                    "interrupt" (SIGINT). On Windows, all map to process kill.
    
    Returns:
        JSON string with keys:
          - success (bool): Whether the operation succeeded.
          - result (any): Process list or operation result.
          - error (str or null): Error message if failed.
    """
    start = time.perf_counter()
    
    try:
        import psutil
        
        if action == "list":
            processes = []
            for proc in psutil.process_iter(["pid", "name", "status", "cpu_percent", "memory_percent", "create_time", "username"]):
                try:
                    pinfo = proc.info
                    processes.append({
                        "pid": pinfo["pid"],
                        "name": pinfo["name"],
                        "status": pinfo["status"],
                        "cpu_percent": pinfo["cpu_percent"] or 0.0,
                        "memory_percent": round(pinfo["memory_percent"] or 0.0, 2),
                        "created": pinfo["create_time"],
                        "username": pinfo["username"],
                    })
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            
            # Sort by CPU usage descending, limit to 100
            processes.sort(key=lambda p: p["cpu_percent"], reverse=True)
            
            return json.dumps({
                "success": True,
                "result": processes[:100],
                "error": None,
                "metadata": {"total": len(processes), "displayed": min(len(processes), 100)}
            })
        
        elif action == "search":
            if not name:
                return json.dumps({"success": False, "result": None, "error": "name parameter required"})
            
            matches = []
            for proc in psutil.process_iter(["pid", "name", "status", "cpu_percent", "memory_percent", "cmdline"]):
                try:
                    proc_name = proc.info.get("name", "") or ""
                    cmdline = " ".join(proc.info.get("cmdline") or [])
                    if name.lower() in proc_name.lower() or name.lower() in cmdline.lower():
                        matches.append({
                            "pid": proc.info["pid"],
                            "name": proc_name,
                            "status": proc.info["status"],
                            "cpu_percent": proc.info["cpu_percent"] or 0.0,
                            "memory_percent": round(proc.info["memory_percent"] or 0.0, 2),
                            "cmdline": cmdline[:200],
                        })
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            
            return json.dumps({
                "success": True,
                "result": matches,
                "error": None,
                "metadata": {"query": name, "count": len(matches)}
            })
        
        elif action == "info":
            if pid is None:
                return json.dumps({"success": False, "result": None, "error": "pid required"})
            
            try:
                proc = psutil.Process(pid)
                with proc.oneshot():
                    info = {
                        "pid": proc.pid,
                        "name": proc.name(),
                        "status": proc.status(),
                        "created": proc.create_time(),
                        "cpu_percent": proc.cpu_percent(),
                        "memory_percent": round(proc.memory_percent(), 2),
                        "memory_rss_mb": round(proc.memory_info().rss / (1024*1024), 1),
                        "num_threads": proc.num_threads(),
                        "username": proc.username(),
                        "cmdline": " ".join(proc.cmdline() or [])[:300],
                        "exe": proc.exe(),
                        "cwd": proc.cwd(),
                        "children": [c.pid for c in proc.children()],
                    }
                return json.dumps({"success": True, "result": info, "error": None})
            except psutil.NoSuchProcess:
                return json.dumps({"success": False, "result": None, "error": f"Process {pid} not found"})
            except psutil.AccessDenied:
                return json.dumps({"success": False, "result": None, "error": f"Access denied to process {pid}"})
        
        elif action == "kill":
            target_pids = []
            
            if pid is not None:
                target_pids = [pid]
            elif name:
                for proc in psutil.process_iter(["pid", "name"]):
                    try:
                        if name.lower() in (proc.info.get("name") or "").lower():
                            target_pids.append(proc.info["pid"])
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue
            else:
                return json.dumps({"success": False, "result": None, "error": "Either pid or name required"})
            
            if not target_pids:
                return json.dumps({"success": False, "result": None, "error": "No matching processes found"})
            
            results = []
            for target_pid in target_pids:
                try:
                    proc = psutil.Process(target_pid)
                    if signal_type == "kill":
                        proc.kill()
                    elif signal_type == "interrupt":
                        proc.terminate() if sys.platform == "win32" else proc.send_signal(signal.SIGINT)
                    else:
                        proc.terminate()
                    
                    # Wait briefly for process to end
                    gone, still_alive = psutil.wait_procs([proc], timeout=3)
                    if proc in still_alive:
                        if signal_type == "kill":
                            results.append({"pid": target_pid, "success": False, "error": "Could not kill process"})
                        else:
                            # Force kill
                            proc.kill()
                            results.append({"pid": target_pid, "success": True, "action": "force_killed"})
                    else:
                        results.append({"pid": target_pid, "success": True, "action": signal_type})
                
                except psutil.NoSuchProcess:
                    results.append({"pid": target_pid, "success": True, "action": "already_gone"})
                except psutil.AccessDenied:
                    results.append({"pid": target_pid, "success": False, "error": "Access denied"})
                except Exception as e:
                    results.append({"pid": target_pid, "success": False, "error": str(e)})
            
            all_success = all(r["success"] for r in results)
            return json.dumps({
                "success": all_success,
                "result": results,
                "error": None if all_success else "Some processes could not be killed",
            })
        
        elif action == "launch":
            if not command:
                return json.dumps({"success": False, "result": None, "error": "command required"})
            
            import subprocess
            try:
                cmd = [command] + (args or [])
                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
                return json.dumps({
                    "success": True,
                    "result": f"Launched '{command}' with PID {proc.pid}",
                    "error": None,
                    "metadata": {"pid": proc.pid, "command": command}
                })
            except FileNotFoundError:
                return json.dumps({"success": False, "result": None, "error": f"Command not found: {command}"})
            except Exception as e:
                return json.dumps({"success": False, "result": None, "error": f"Launch failed: {e}"})
        
        elif action == "tree":
            processes = []
            for proc in psutil.process_iter(["pid", "name", "ppid", "status"]):
                try:
                    processes.append({
                        "pid": proc.info["pid"],
                        "name": proc.info["name"],
                        "ppid": proc.info["ppid"],
                        "status": proc.info["status"],
                    })
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            
            # Build tree structure starting from PID 1 or given name
            if name:
                root_pids = [p["pid"] for p in processes if name.lower() in p["name"].lower()]
            else:
                root_pids = [1]
            
            def build_tree(parent_pid):
                children = [p for p in processes if p["ppid"] == parent_pid]
                return [
                    {"pid": p["pid"], "name": p["name"], "status": p["status"],
                     "children": build_tree(p["pid"])}
                    for p in children[:20]
                ]
            
            tree = []
            for root_pid in root_pids[:5]:
                proc_info = next((p for p in processes if p["pid"] == root_pid), None)
                if proc_info:
                    tree.append({
                        "pid": root_pid,
                        "name": proc_info["name"],
                        "status": proc_info["status"],
                        "children": build_tree(root_pid),
                    })
            
            return json.dumps({"success": True, "result": tree, "error": None})
        
        else:
            return json.dumps({
                "success": False, "result": None,
                "error": f"Unknown action: '{action}'. Valid: list, kill, launch, info, search, tree"
            })
    
    except ImportError:
        return json.dumps({
            "success": False, "result": None,
            "error": "psutil not installed. Install with: pip install psutil"
        })
    except Exception as e:
        logger.error(f"process_manager error: {e}", exc_info=True)
        return json.dumps({
            "success": False, "result": None,
            "error": f"{type(e).__name__}: {e}"
        })
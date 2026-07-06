"""
NEXUS AI v4.0 — Tool 16: Workflow macro execution.
Hardware: Intel i3 7th Gen · 12GB RAM · Ollama + Groq API

Executes compiled .nexflow.json workflow macros — pre-defined sequences
of tool calls that can be saved, shared, and re-run.
"""

import json
import logging
import time
from pathlib import Path
from typing import Optional, List, Dict, Any

logger = logging.getLogger("nexus.tool.workflow_macro")

# ─── Constants ────────────────────────────────────────────────────────────────
WORKFLOWS_DIR = Path.home() / ".nexus_ai" / "workflows"


def workflow_macro(
    action: str,
    name: Optional[str] = None,
    steps: Optional[List[Dict[str, Any]]] = None,
    description: str = "",
) -> str:
    """
    Execute, save, list, or delete compiled workflow macros.
    
    Use this tool when: The user wants to run a saved workflow, save a sequence
    of steps as a reusable macro, or manage their workflow library.
    
    Args:
        action: One of: "run", "save", "list", "delete", "info"
        name: Name of the workflow (without .nexflow.json extension).
        steps: List of step dicts for "save" action. Each step has:
               - "tool": Tool function name
               - "params": Dict of parameters for the tool
               - "description": Human-readable description of the step
        description: Human-readable description of what the workflow does.
    
    Returns:
        JSON string with keys:
          - success (bool): Whether the operation succeeded.
          - result (any): Workflow execution results or metadata.
          - error (str or null): Error message if failed.
    
    Examples:
        >>> workflow_macro("list")
        >>> workflow_macro("run", name="daily_report")
        >>> workflow_macro("save", name="my_workflow", steps=[...], description="My workflow")
    """
    start = time.perf_counter()
    
    try:
        WORKFLOWS_DIR.mkdir(parents=True, exist_ok=True)
        
        if action == "list":
            workflows = []
            for f in sorted(WORKFLOWS_DIR.glob("*.nexflow.json")):
                try:
                    data = json.loads(f.read_text(encoding="utf-8"))
                    workflows.append({
                        "name": f.stem.replace(".nexflow", ""),
                        "description": data.get("description", ""),
                        "steps": len(data.get("steps", [])),
                        "created": data.get("created", ""),
                        "modified": data.get("modified", ""),
                        "size_bytes": f.stat().st_size,
                    })
                except (json.JSONDecodeError, Exception):
                    workflows.append({"name": f.stem, "error": "Invalid workflow file"})
            
            return json.dumps({
                "success": True,
                "result": workflows,
                "error": None,
                "metadata": {"count": len(workflows), "directory": str(WORKFLOWS_DIR)}
            })
        
        elif action == "save":
            if not name:
                return json.dumps({"success": False, "result": None, "error": "Workflow name required"})
            if not steps:
                return json.dumps({"success": False, "result": None, "error": "Steps list required"})
            
            workflow = {
                "name": name,
                "description": description,
                "steps": steps,
                "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "modified": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "schema_version": "1.0",
                "step_count": len(steps),
            }
            
            workflow_path = WORKFLOWS_DIR / f"{name}.nexflow.json"
            workflow_path.write_text(json.dumps(workflow, indent=2), encoding="utf-8")
            
            return json.dumps({
                "success": True,
                "result": f"Workflow '{name}' saved ({len(steps)} steps)",
                "error": None,
                "metadata": {"path": str(workflow_path), "steps": len(steps)}
            })
        
        elif action == "run":
            if not name:
                return json.dumps({"success": False, "result": None, "error": "Workflow name required"})
            
            workflow_path = WORKFLOWS_DIR / f"{name}.nexflow.json"
            if not workflow_path.exists():
                return json.dumps({
                    "success": False, "result": None,
                    "error": f"Workflow '{name}' not found. Available: {[f.stem.replace('.nexflow', '') for f in WORKFLOWS_DIR.glob('*.nexflow.json')]}"
                })
            
            workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
            steps = workflow.get("steps", [])
            
            # Execute each step sequentially
            results = []
            all_success = True
            
            for i, step in enumerate(steps):
                tool_name = step.get("tool", "")
                params = step.get("params", {})
                step_desc = step.get("description", f"Step {i + 1}")
                
                # Dynamically import and call the tool
                try:
                    # Import the tool module
                    module_path = f"nexus_tools.tools.{tool_name}"
                    module = __import__(module_path, fromlist=[tool_name])
                    
                    # Find the tool function
                    tool_func = None
                    for attr_name in dir(module):
                        attr = getattr(module, attr_name)
                        if callable(attr) and not attr_name.startswith("_"):
                            tool_func = attr
                            break
                    
                    if tool_func:
                        step_result = tool_func(**params)
                        step_data = json.loads(step_result) if isinstance(step_result, str) else step_result
                        step_success = step_data.get("success", False)
                    else:
                        step_data = {"success": False, "error": f"Tool function not found in {tool_name}"}
                        step_success = False
                    
                    results.append({
                        "step": i + 1,
                        "description": step_desc,
                        "tool": tool_name,
                        "success": step_success,
                        "result": step_data.get("result"),
                        "error": step_data.get("error"),
                    })
                    
                    if not step_success:
                        all_success = False
                        break  # Stop on first failure
                
                except Exception as e:
                    results.append({
                        "step": i + 1,
                        "description": step_desc,
                        "tool": tool_name,
                        "success": False,
                        "error": str(e),
                    })
                    all_success = False
                    break
            
            return json.dumps({
                "success": all_success,
                "result": {
                    "workflow": name,
                    "total_steps": len(steps),
                    "completed_steps": len(results),
                    "results": results,
                },
                "error": None if all_success else "Workflow failed at step " + str(len(results)),
                "metadata": {"workflow": name, "steps_completed": len(results), "steps_total": len(steps)}
            })
        
        elif action == "delete":
            if not name:
                return json.dumps({"success": False, "result": None, "error": "Workflow name required"})
            
            workflow_path = WORKFLOWS_DIR / f"{name}.nexflow.json"
            if not workflow_path.exists():
                return json.dumps({"success": False, "result": None, "error": f"Workflow '{name}' not found"})
            
            workflow_path.unlink()
            return json.dumps({"success": True, "result": f"Deleted workflow: {name}", "error": None})
        
        elif action == "info":
            if not name:
                return json.dumps({"success": False, "result": None, "error": "Workflow name required"})
            
            workflow_path = WORKFLOWS_DIR / f"{name}.nexflow.json"
            if not workflow_path.exists():
                return json.dumps({"success": False, "result": None, "error": f"Workflow '{name}' not found"})
            
            workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
            return json.dumps({
                "success": True,
                "result": workflow,
                "error": None
            })
        
        else:
            return json.dumps({
                "success": False, "result": None,
                "error": f"Unknown action: '{action}'. Valid: run, save, list, delete, info"
            })
    
    except Exception as e:
        logger.error(f"workflow_macro error: {e}", exc_info=True)
        return json.dumps({
            "success": False, "result": None,
            "error": f"{type(e).__name__}: {e}"
        })
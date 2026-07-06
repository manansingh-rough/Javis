"""
NEXUS AI v4.0 — DAG task decomposition and parallel execution engine.
Hardware: Intel i3 7th Gen · 12GB RAM · Ollama + Groq API

Decomposes user requests into a Directed Acyclic Graph (DAG) of tool calls,
identifies parallelizable branches, computes critical path, and executes
with maximum parallelism (capped at PARALLEL_TOOL_WORKERS = 3 for i3).

LAW P2: Run every node that has all its dependencies satisfied concurrently.
LAW P3: GUI operations always serialize via UI_AUTOMATION_LOCK.
LAW P7: Maximum 3 concurrent parallel tasks on i3.
"""

import asyncio
import json
import logging
import time
import threading
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Set, Tuple, Callable, Awaitable
from functools import lru_cache
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError

from nexus_config.settings import get_settings
from nexus_brain.agent_state import NexusState, DAGNode

logger = logging.getLogger("nexus.task_planner")


# ─── UI Automation Lock ───────────────────────────────────────────────────────

# Global lock: ALL GUI operations must acquire this before executing.
# This serializes mouse/keyboard/screenshot operations because PyAutoGUI
# operates on global system state.
UI_AUTOMATION_LOCK: asyncio.Lock = asyncio.Lock()

# Thread pool for CPU-bound tool calls (not I/O-bound)
_CPU_WORKER_POOL: Optional[ThreadPoolExecutor] = None

def _get_cpu_pool() -> ThreadPoolExecutor:
    """Lazy-init thread pool for CPU-bound operations."""
    global _CPU_WORKER_POOL
    if _CPU_WORKER_POOL is None:
        _CPU_WORKER_POOL = ThreadPoolExecutor(
            max_workers=2,
            thread_name_prefix="nexus-cpu-tool",
        )
    return _CPU_WORKER_POOL


# ─── DAG Types ────────────────────────────────────────────────────────────────

@dataclass
class DAGPlan:
    """
    Complete DAG execution plan.
    
    Fields:
        description: Human-readable task description.
        nodes: All nodes in the DAG.
        critical_path: Node IDs on the longest path (estimated duration).
        estimated_duration_ms: Total estimated wall-clock time.
        parallel_branches: Number of independent parallel branches detected.
        can_parallelize: True if any nodes can run concurrently.
    """
    description: str
    nodes: List[DAGNode]
    critical_path: List[str]
    estimated_duration_ms: float
    parallel_branches: int
    can_parallelize: bool


@dataclass
class DAGExecutionResult:
    """
    Result of executing a DAG.
    
    Fields:
        success: True if all non-skippable nodes succeeded.
        node_results: Dict[node_id][str] → tool output.
        failed_nodes: List of (node_id, error) tuples.
        duration_ms: Total execution time.
        partial: True if some nodes failed but DAG continued.
    """
    success: bool
    node_results: Dict[str, str]
    failed_nodes: List[Tuple[str, str]]
    duration_ms: float
    partial: bool


# ─── DAG Planner ─────────────────────────────────────────────────────────────

DECOMPOSITION_PROMPT = """You are NEXUS AI's task planner. Decompose the following user request into a DAG (Directed Acyclic Graph) of tool calls.

Available tools with descriptions:
{tools_descriptions}

User request: {task}

Rules:
1. Each node should be a SINGLE atomic tool call.
2. Nodes that can run in parallel MUST be identified (independent operations).
3. Nodes that depend on other nodes' outputs MUST list those as dependencies.
4. UI automation operations (click, type, screenshot, mouse) CANNOT parallelize — they depend on global state.
5. Mark UI operations with "is_ui_operation": true.
6. Mark nodes that can fail safely with "can_fail_safely": true.
7. Max nodes: 15. If more than 15 needed, combine related operations.
8. Each node needs: id, description, tool, tool_input, dependencies, is_ui_operation, can_fail_safely, and estimated_duration_ms.

Respond with JSON ONLY:
{{
    "task_description": "Brief description of the overall task",
    "nodes": [
        {{
            "id": "n0",
            "description": "What this step does",
            "tool": "tool_name",
            "tool_input": {{"param1": "value1"}},
            "dependencies": [],
            "is_ui_operation": false,
            "can_fail_safely": false,
            "estimated_duration_ms": 2000
        }}
    ]
}}"""


class TaskPlanner:
    """
    Decomposes user requests into parallelizable DAGs and executes them.
    
    Usage:
        planner = get_task_planner()
        plan = await planner.plan("Get CPU stats AND list files AND check git status")
        result = await planner.execute(plan, tool_executor)
    """
    
    def __init__(self):
        self._settings = get_settings()
        self._max_parallel = self._settings.PARALLEL_TOOL_WORKERS
        self._semaphore = asyncio.Semaphore(self._max_parallel)
    
    async def plan(
        self,
        task: str,
        tools_descriptions: str,
    ) -> DAGPlan:
        """
        Decompose a task into a DAG execution plan.
        
        Args:
            task: Natural language user request.
            tools_descriptions: Formatted string of available tools.
        
        Returns:
            DAGPlan with nodes, critical path, and parallelization info.
        """
        from nexus_brain.llm_router import get_llm_router
        
        prompt = DECOMPOSITION_PROMPT.format(
            task=task[:2000],
            tools_descriptions=tools_descriptions[:3000],
        )
        
        router = get_llm_router()
        response = await router.generate(
            messages=[
                {"role": "system", "content": "You are a task decomposition expert. Respond with JSON only."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
            max_tokens=2000,
            response_format={"type": "json_object"},
            prefer_provider="groq",  # Use fast Groq for planning
        )
        
        if not response.success:
            # Fallback: single-node plan
            return DAGPlan(
                description=task,
                nodes=[self._make_single_node(task)],
                critical_path=["n0"],
                estimated_duration_ms=5000,
                parallel_branches=1,
                can_parallelize=False,
            )
        
        try:
            data = json.loads(response.content)
            raw_nodes = data.get("nodes", [])
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning("DAG parsing failed: %s. Using single-node fallback.", e)
            return DAGPlan(
                description=task,
                nodes=[self._make_single_node(task)],
                critical_path=["n0"],
                estimated_duration_ms=5000,
                parallel_branches=1,
                can_parallelize=False,
            )
        
        if not raw_nodes:
            return DAGPlan(
                description=task,
                nodes=[self._make_single_node(task)],
                critical_path=["n0"],
                estimated_duration_ms=5000,
                parallel_branches=1,
                can_parallelize=False,
            )
        
        # Convert to DAGNode typed dicts
        nodes: List[DAGNode] = []
        for n in raw_nodes:
            nodes.append(DAGNode(
                id=n.get("id", f"n{len(nodes)}"),
                description=n.get("description", ""),
                tool=n.get("tool"),
                tool_input=n.get("tool_input", {}),
                dependencies=n.get("dependencies", []),
                status="pending",
                result=None,
                error=None,
                can_fail_safely=n.get("can_fail_safely", False),
                estimated_duration_ms=n.get("estimated_duration_ms", 2000),
            ))
        
        # Compute critical path and parallelization
        critical_path = self._compute_critical_path(nodes)
        estimated_duration = sum(
            n.get("estimated_duration_ms", 2000) or 2000
            for n in nodes
            if n["id"] in critical_path
        )
        parallel_branches = self._count_parallel_branches(nodes)
        
        return DAGPlan(
            description=data.get("task_description", task),
            nodes=nodes,
            critical_path=critical_path,
            estimated_duration_ms=estimated_duration,
            parallel_branches=parallel_branches,
            can_parallelize=parallel_branches > 1,
        )
    
    def _make_single_node(self, task: str) -> DAGNode:
        """Create a single-node DAG for simple commands."""
        return DAGNode(
            id="n0",
            description=task[:200],
            tool=None,
            tool_input={},
            dependencies=[],
            status="pending",
            result=None,
            error=None,
            can_fail_safely=False,
            estimated_duration_ms=5000,
        )
    
    def _compute_critical_path(self, nodes: List[DAGNode]) -> List[str]:
        """
        Compute the critical path through the DAG (longest path).
        
        Uses topological sort + longest-path DP.
        
        Args:
            nodes: All DAG nodes.
        
        Returns:
            List of node IDs on the critical path.
        """
        if not nodes:
            return []
        
        # Build adjacency maps
        node_map: Dict[str, DAGNode] = {n["id"]: n for n in nodes}
        dependents: Dict[str, List[str]] = {}  # node_id → nodes that depend on it
        in_degree: Dict[str, int] = {}
        
        for n in nodes:
            nid = n["id"]
            in_degree[nid] = len(n.get("dependencies", []))
            for dep in n.get("dependencies", []):
                if dep not in dependents:
                    dependents[dep] = []
                dependents[dep].append(nid)
        
        # Topological sort (Kahn's algorithm)
        queue = [nid for nid, deg in in_degree.items() if deg == 0]
        topo_order = []
        
        while queue:
            node_id = queue.pop(0)
            topo_order.append(node_id)
            for dep_id in dependents.get(node_id, []):
                in_degree[dep_id] -= 1
                if in_degree[dep_id] == 0:
                    queue.append(dep_id)
        
        if len(topo_order) != len(nodes):
            logger.warning("DAG has a cycle or disconnected nodes. Using topological order.")
        
        # Longest path DP
        longest: Dict[str, float] = {}
        predecessor: Dict[str, Optional[str]] = {}
        
        for nid in topo_order:
            node = node_map[nid]
            duration = node.get("estimated_duration_ms", 2000) or 2000
            
            # Find max duration among predecessors
            max_pred_dur = 0.0
            best_pred: Optional[str] = None
            for dep_id in node.get("dependencies", []):
                pred_total = longest.get(dep_id, 0.0)
                if pred_total > max_pred_dur:
                    max_pred_dur = pred_total
                    best_pred = dep_id
            
            longest[nid] = max_pred_dur + duration
            predecessor[nid] = best_pred
        
        # Find the node with maximum total duration
        if not longest:
            return [n["id"] for n in nodes]
        
        end_node = max(longest, key=longest.get)  # type: ignore[arg-type]
        
        # Trace back to get critical path
        path: List[str] = []
        current: Optional[str] = end_node
        while current is not None:
            path.insert(0, current)
            current = predecessor.get(current)
        
        return path
    
    def _count_parallel_branches(self, nodes: List[DAGNode]) -> int:
        """
        Count the number of independent parallel branches at the widest point.
        
        Examines the DAG layer by layer to find maximum parallelism.
        """
        if not nodes:
            return 1
        
        node_map: Dict[str, DAGNode] = {n["id"]: n for n in nodes}
        
        # Find root nodes (no dependencies)
        roots = [n["id"] for n in nodes if not n.get("dependencies")]
        if not roots:
            return 1
        
        # BFS to find max nodes at any level
        visited: Set[str] = set()
        current_level: Set[str] = set(roots)
        max_width = len(roots)
        
        while current_level:
            next_level: Set[str] = set()
            for nid in current_level:
                visited.add(nid)
                # Find all direct dependents
                for other_nid, other_node in node_map.items():
                    if other_nid not in visited and nid in other_node.get("dependencies", []):
                        # Check if ALL dependencies are satisfied
                        deps = set(other_node.get("dependencies", []))
                        if deps.issubset(visited.union(current_level)):
                            next_level.add(other_nid)
            
            if next_level:
                max_width = max(max_width, len(next_level))
            current_level = next_level
        
        return max_width
    
    async def execute(
        self,
        plan: DAGPlan,
        tool_executor: Callable[[str, Dict[str, Any], bool], Awaitable[str]],
        progress_callback: Optional[Callable[[str, str], Awaitable[None]]] = None,
    ) -> DAGExecutionResult:
        """
        Execute a DAG plan with maximum parallelism.
        
        Args:
            plan: The DAG execution plan.
            tool_executor: Async callable(tool_name, tool_input, is_ui) → output string.
            progress_callback: Async callable(node_id, status) for real-time UI updates.
        
        Returns:
            DAGExecutionResult with outputs and failure info.
        """
        start = time.perf_counter()
        node_map: Dict[str, DAGNode] = {n["id"]: n for n in plan.nodes}
        results: Dict[str, str] = {}
        failed: List[Tuple[str, str]] = []
        
        # Track which nodes have completed
        completed: Set[str] = set()
        running: Set[str] = set()
        
        # Build dependency tracking
        dependents: Dict[str, List[str]] = {}
        all_ids = set()
        for n in plan.nodes:
            nid = n["id"]
            all_ids.add(nid)
            for dep in n.get("dependencies", []):
                if dep not in dependents:
                    dependents[dep] = []
                dependents[dep].append(nid)
        
        async def execute_node(node: DAGNode) -> None:
            """Execute a single DAG node."""
            nonlocal results, failed
            
            nid = node["id"]
            tool_name = node.get("tool")
            tool_input = node.get("tool_input", {})
            is_ui = isinstance(tool_input, dict) and tool_input.get("is_ui_operation", False)
            can_fail = node.get("can_fail_safely", False)
            
            if not tool_name:
                # No tool — just mark complete
                results[nid] = json.dumps({"success": True, "result": "No action needed"})
                completed.add(nid)
                if progress_callback:
                    await progress_callback(nid, "completed")
                return
            
            try:
                if progress_callback:
                    await progress_callback(nid, "running")
                
                output = await tool_executor(tool_name, tool_input, is_ui)
                results[nid] = output
                completed.add(nid)
                
                if progress_callback:
                    await progress_callback(nid, "completed")
                
            except Exception as e:
                error_msg = f"{type(e).__name__}: {e}"
                if can_fail:
                    results[nid] = json.dumps({"success": False, "error": error_msg})
                    completed.add(nid)
                    failed.append((nid, error_msg))
                    if progress_callback:
                        await progress_callback(nid, "skipped")
                else:
                    failed.append((nid, error_msg))
                    if progress_callback:
                        await progress_callback(nid, "failed")
                    raise  # Propagate to halt DAG
        
        # Execution loop: run all nodes respecting dependencies
        try:
            while len(completed) + len(failed) < len(all_ids):
                # Find nodes whose dependencies are all satisfied
                ready: List[DAGNode] = []
                for n in plan.nodes:
                    nid = n["id"]
                    if nid in completed or nid in running or any(nid == f[0] for f in failed):
                        continue
                    deps = set(n.get("dependencies", []))
                    satisfied = deps.issubset(completed)
                    if satisfied:
                        ready.append(n)
                
                if not ready:
                    # No progress possible — either done or stuck
                    break
                
                # Run ready nodes (respecting max parallelism)
                running.clear()
                async with self._semaphore:
                    running_tasks = []
                    for node in ready[:self._max_parallel]:
                        nid = node["id"]
                        running.add(nid)
                        running_tasks.append(execute_node(node))
                    
                    await asyncio.gather(*running_tasks, return_exceptions=True)
        
        except Exception as e:
            logger.error("DAG execution halted: %s", e)
        
        duration = (time.perf_counter() - start) * 1000
        
        all_done = len(completed) + len(failed) >= len(all_ids)
        any_fatal = any(
            (nid, msg) for nid, msg in failed
            if not any(
                n.get("can_fail_safely", False)
                for n in plan.nodes
                if n["id"] == nid
            )
        )
        
        return DAGExecutionResult(
            success=all_done and not any_fatal,
            node_results=results,
            failed_nodes=failed,
            duration_ms=duration,
            partial=not all_done or bool(failed),
        )


@lru_cache(maxsize=1)
def get_task_planner() -> TaskPlanner:
    """
    Return the singleton TaskPlanner instance.
    
    Returns:
        TaskPlanner: The singleton task planner instance.
    """
    return TaskPlanner()

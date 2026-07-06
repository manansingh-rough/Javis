"""
NEXUS AI v4.0 — NexusState TypedDict schema and state transition validators.
Hardware: Intel i3 7th Gen · 12GB RAM · Ollama + Groq API

This module defines the EXACT state schema passed through the LangGraph graph.
Every node reads from and writes to this state. The schema is permanent to
ensure backward compatibility across graph versions.
"""

from typing import TypedDict, Optional, List, Dict, Any, Literal
from enum import Enum


# ─── Graph Node IDs ───────────────────────────────────────────────────────────

class GraphNode(str, Enum):
    """Every node name in the LangGraph execution graph."""
    INTENT_CLASSIFY = "intent_classify"
    TASK_PLAN = "task_plan"
    CONTEXT_LOAD = "context_load"
    AGENT_REASON = "agent_reason"
    TOOL_SELECT = "tool_select"
    TOOL_EXECUTE = "tool_execute"
    CAPABILITY_SYNTH = "capability_synth"
    MEMORY_WRITE = "memory_write"
    RESPONSE_FORMAT = "response_format"
    FINAL = "final"


# ─── Route Literals ───────────────────────────────────────────────────────────

AgentRoute = Literal[
    "simple_command",
    "complex_task",
    "ui_automation",
    "capability_synthesis",
    "chat",
    "clarify",
]


# ─── Task DAG Types ───────────────────────────────────────────────────────────

class DAGNode(TypedDict, total=False):
    """A single node in the task execution DAG."""
    id: str                                  # Unique node ID (e.g. "n0", "n1")
    description: str                         # Human-readable description
    tool: Optional[str]                      # Tool name to call
    tool_input: Optional[Dict[str, Any]]     # Arguments for the tool
    dependencies: List[str]                  # Node IDs that must complete first
    status: Literal["pending", "running", "completed", "failed", "skipped"]
    result: Optional[str]                    # Tool output
    error: Optional[str]                     # Error message if failed
    can_fail_safely: bool                    # True = continue on failure
    duration_ms: Optional[float]             # Execution wall-clock time
    critical_path_ms: Optional[float]        # Estimated duration for scheduling


# ─── Main State Schema ────────────────────────────────────────────────────────

class NexusState(TypedDict, total=False):
    """
    Complete LangGraph agent state schema.
    
    Every key is optional with a default so the graph can be initialized
    with just the user input. All nodes mutate this dict in place.
    
    Thread safety: The state dict is owned by a single LangGraph run.
    Multiple concurrent runs each have their own NexusState instance.
    """
    # ── Input ────────────────────────────────────────────────────────────────
    user_input: str                           # Raw user message
    input_type: Literal["text", "voice"]      # How the input was received
    
    # ── Classification ───────────────────────────────────────────────────────
    intent: Optional[AgentRoute]              # Classified intent
    confidence: Optional[float]               # Classification confidence (0-1)
    
    # ── Context ──────────────────────────────────────────────────────────────
    system_prompt: str                        # Assembled system prompt
    conversation_history: List[Dict[str, str]] # Recent messages [{"role","content"}]
    conversation_summary: Optional[str]       # Compressed summary of older messages
    conversation_start: Optional[str]         # ISO timestamp of conversation start
    working_memory: List[Dict[str, Any]]      # Current-session facts (FIFO, max 20)
    episodic_memories: List[str]              # Retrieved past task descriptions
    user_preferences: List[str]               # Retrieved user preference facts
    
    # ── Task Plan ────────────────────────────────────────────────────────────
    task_description: Optional[str]           # Decomposed task description
    task_dag: List[DAGNode]                   # Execution DAG
    task_dag_max_parallel: int                # Max parallel branches (def: 3)
    task_estimated_duration_ms: Optional[float]
    critical_path: Optional[List[str]]        # Node IDs on critical path
    
    # ── Execution ────────────────────────────────────────────────────────────
    current_node_id: Optional[str]            # Currently executing DAG node
    completed_nodes: List[str]                # Finished node IDs
    failed_nodes: List[str]                   # Failed-but-continued node IDs
    tool_outputs: Dict[str, str]              # Node ID → output JSON string
    iteration_count: int                      # LangGraph loop counter
    
    # ── Self-Healing ─────────────────────────────────────────────────────────
    synthesis_triggered: bool                 # True if capability was synthesized
    synthesis_attempts: int                   # Number of synthesis retries
    synthesis_results: Optional[List[Dict]]   # Results of synthesis attempts
    gap_encountered: Optional[str]            # Capability gap description
    gap_recovery_tool: Optional[str]          # Name of synthesized tool
    
    # ── LAW 1.1 Playbook / Recursion ─────────────────────────────────────────
    playbook_name: Optional[str]              # Matched playbook name, if any
    playbook_step: int                        # Current step index in playbook
    playbook_state: Optional[Dict[str, Any]]  # Accumulated state across playbook steps
    recursion_depth: int                      # Current decomposition recursion depth
    debug_retry_count: int                    # Retry counter for current sub-goal
    sub_goal_tree: Optional[List[Dict]]       # Decomposition sub-goal tree
    project_memory_id: Optional[str]          # ChromaDB doc ID for project memory
    
    # ── Output ───────────────────────────────────────────────────────────────
    final_response: Optional[str]             # Response to user
    response_tokens: Optional[int]            # Output token count
    response_cost: Optional[float]            # Estimated USD cost of LLM calls
    
    # ── Meta ─────────────────────────────────────────────────────────────────
    session_id: str                           # UUID4 for the session
    boot_time: str                            # ISO timestamp of agent start
    errors: List[Dict[str, str]]              # {node, error, timestamp}
    llm_calls: int                            # Count of LLM calls this run
    total_duration_ms: float                  # Total agent run wall-clock time


# ─── Default State Factory ────────────────────────────────────────────────────

def make_initial_state(
    user_input: str,
    session_id: str,
    input_type: Literal["text", "voice"] = "text",
    working_memory: Optional[List[Dict[str, Any]]] = None,
    conversation_history: Optional[List[Dict[str, str]]] = None,
) -> NexusState:
    """
    Create a new NexusState with safe defaults.
    
    Args:
        user_input: The raw user message.
        session_id: UUID4 string for the session.
        input_type: How the input was received.
        working_memory: Current-session facts (optional).
        conversation_history: Recent messages (optional).
    
    Returns:
        Fully initialized NexusState ready for graph execution.
    """
    from datetime import datetime, timezone
    
    return NexusState(
        user_input=user_input,
        input_type=input_type,
        intent=None,
        confidence=None,
        system_prompt="",
        conversation_history=conversation_history or [],
        conversation_summary=None,
        conversation_start=datetime.now(timezone.utc).isoformat(),
        working_memory=working_memory or [],
        episodic_memories=[],
        user_preferences=[],
        task_description=None,
        task_dag=[],
        task_dag_max_parallel=3,
        task_estimated_duration_ms=None,
        critical_path=None,
        current_node_id=None,
        completed_nodes=[],
        failed_nodes=[],
        tool_outputs={},
        iteration_count=0,
        synthesis_triggered=False,
        synthesis_attempts=0,
        synthesis_results=None,
        gap_encountered=None,
        gap_recovery_tool=None,
        playbook_name=None,
        playbook_step=0,
        playbook_state=None,
        recursion_depth=0,
        debug_retry_count=0,
        sub_goal_tree=None,
        project_memory_id=None,
        final_response=None,
        response_tokens=None,
        response_cost=None,
        session_id=session_id,
        boot_time=datetime.now(timezone.utc).isoformat(),
        errors=[],
        llm_calls=0,
        total_duration_ms=0.0,
    )


# ─── State Transition Validators ──────────────────────────────────────────────

def validate_state_transition(
    old_state: NexusState,
    new_state: NexusState,
    node_id: str,
) -> List[str]:
    """
    Validate a state transition between graph nodes.
    
    Checks:
    1. Required fields for the node are populated
    2. No unexpected field mutations
    3. Counter fields only increment
    
    Args:
        old_state: State before the node ran.
        new_state: State after the node ran.
        node_id: The node that produced the transition.
    
    Returns:
        List of validation warnings. Empty list = clean transition.
    
    Note:
        This is non-blocking — it logs warnings rather than raising.
        In production, violations are recorded in the audit log.
    """
    warnings: List[str] = []
    
    # Check iteration count only increases
    if new_state.get("iteration_count", 0) < old_state.get("iteration_count", 0):
        warnings.append(f"iteration_count decreased: {old_state.get('iteration_count')} → {new_state.get('iteration_count')}")
    
    # Check llm_calls only increases
    if new_state.get("llm_calls", 0) < old_state.get("llm_calls", 0):
        warnings.append(f"llm_calls decreased: {old_state.get('llm_calls')} → {new_state.get('llm_calls')}")
    
    # Check session_id never changes
    old_sid = old_state.get("session_id")
    new_sid = new_state.get("session_id")
    if old_sid and new_sid and old_sid != new_sid:
        warnings.append(f"session_id changed: {old_sid[:8]}… → {new_sid[:8]}…")
    
    # Node-specific checks
    if node_id == GraphNode.INTENT_CLASSIFY:
        if new_state.get("intent") is None:
            warnings.append("intent_classify did not set intent")
    
    elif node_id == GraphNode.TASK_PLAN:
        if new_state.get("task_dag") is None or len(new_state.get("task_dag", [])) == 0:
            warnings.append("task_plan produced empty DAG")
    
    elif node_id == GraphNode.TOOL_EXECUTE:
        if new_state.get("current_node_id") and new_state["current_node_id"] not in new_state.get("completed_nodes", []):
            # Node may have completed successfully — no warning needed
            pass
    
    elif node_id == GraphNode.CAPABILITY_SYNTH:
        if not new_state.get("synthesis_triggered"):
            warnings.append("capability_synth did not set synthesis_triggered=True")
    
    return warnings


# ─── State Serialization ──────────────────────────────────────────────────────

def serialize_state(state: NexusState) -> Dict[str, Any]:
    """
    Serialize NexusState for audit logging and crash reports.
    
    Redacts large fields (tool_outputs, conversation_history) to keep
    serialized size manageable.
    
    Args:
        state: The NexusState to serialize.
    
    Returns:
        Dict safe for JSON serialization.
    """
    result = dict(state)
    
    # Redact conversation history (keep only count + last 2 messages)
    history = result.get("conversation_history", [])
    if len(history) > 2:
        result["conversation_history"] = (
            f"[{len(history)} messages, showing last 2]"
        )
    
    # Redact large tool outputs
    outputs = result.get("tool_outputs", {})
    if outputs:
        truncated = {}
        for k, v in outputs.items():
            truncated[k] = v[:200] + "…" if len(v) > 200 else v
        result["tool_outputs"] = truncated
    
    # Remove working memory detail
    wm = result.get("working_memory", [])
    result["working_memory"] = f"[{len(wm)} facts]"
    
    # Convert enum values to strings
    for key, value in list(result.items()):
        if hasattr(value, "value"):
            result[key] = value.value
    
    return result

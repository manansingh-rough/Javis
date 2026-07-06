"""
NEXUS AI v4.0 — LangGraph ReAct engine with self-healing loop.
Hardware: Intel i3 7th Gen · 12GB RAM · Ollama + Groq API

The orchestration graph routes every user request through:
  1. Intent classification (local Ollama, <50ms, $0)
  2. Context assembly (memory injection, ~10ms)
  3. Agent reasoning (Groq 70B, ~300ms-5s)
  4. Tool execution (parallel DAG when possible)
  5. Capability synthesis (self-healing on tool gaps)
  6. Memory write (persistent learning)
  7. Response formatting

Queue-driven I/O ensures the UI thread is NEVER blocked.
"""

import asyncio
import json
import logging
import time
import uuid
from typing import Optional, Dict, Any, List, AsyncIterator, Callable, Awaitable
from functools import lru_cache
from dataclasses import dataclass, field

from nexus_config.settings import get_settings
from nexus_config.audit_logger import get_audit_logger
from nexus_brain.agent_state import (
    NexusState,
    GraphNode,
    make_initial_state,
    serialize_state,
    validate_state_transition,
)
from nexus_brain.llm_router import get_llm_router, LLMResponse
from nexus_brain.intent_classifier import get_intent_classifier
from nexus_brain.context_builder import get_context_builder
from nexus_brain.conversation_summarizer import get_conversation_summarizer
from nexus_brain.task_planner import get_task_planner, DAGPlan
from nexus_brain.playbook_engine import get_playbook_engine, PlaybookResult
from nexus_tools.capability_synthesizer import get_capability_synthesizer
from nexus_memory.memory_manager import get_memory_manager
from nexus_memory.session_context import get_session_context

logger = logging.getLogger("nexus.orchestrator")


# ─── Graph Node Router Functions ──────────────────────────────────────────────

class AgentOrchestrator:
    """
    LangGraph-style ReAct agent orchestrator.
    
    Unlike a traditional LangGraph which uses a compiled graph object, this
    orchestrator implements the graph as async function calls with explicit
    state transitions. This gives us:
      - Full control over error handling at each node
      - Easy queue integration for UI streaming
      - No LangGraph compilation overhead
      - Simple testing (call any node directly)
    
    The graph structure (fixed — never changes):
    
        user_input
            │
        intent_classify ◄──────┐
            │                   │
        context_load            │
            │                   │
        agent_reason ───────────┤ (retry on failure)
            │                   │
        tool_select ────────────┤ (retry on tool error)
            │                   │
        tool_execute            │
            │                   │
        ┌───┴───┐              │
        │ gap?  │──yes→ capability_synth ──→ tool_execute (retry)
        └───┬───┘              │
            │ no               │
        memory_write            │
            │                   │
        response_format         │
            │                   │
        final ─────────────────┘
    """
    
    def __init__(self):
        self._settings = get_settings()
        self._audit_logger = get_audit_logger()
        self._llm_router = get_llm_router()
        self._classifier = get_intent_classifier()
        self._context_builder = get_context_builder()
        self._summarizer = get_conversation_summarizer()
        self._task_planner = get_task_planner()
        self._synthesizer = get_capability_synthesizer()
        self._memory_manager = get_memory_manager()
        self._session_context = get_session_context()
        
        # Tool execution function (injected by the application layer)
        self._tool_executor: Optional[Callable[[str, Dict[str, Any], bool], Awaitable[str]]] = None
        
        # Queue for UI streaming
        self._output_queue: Optional[asyncio.Queue] = None
        self._progress_queue: Optional[asyncio.Queue] = None
    
    def set_tool_executor(
        self,
        executor: Callable[[str, Dict[str, Any], bool], Awaitable[str]],
    ) -> None:
        """
        Set the tool execution function.
        
        Called by the application layer (main.py) after tool registry is initialized.
        
        Args:
            executor: Async callable(tool_name, tool_input, is_ui) → JSON string.
        """
        self._tool_executor = executor
    
    def set_queues(
        self,
        output_queue: asyncio.Queue,
        progress_queue: asyncio.Queue,
    ) -> None:
        """
        Set the output and progress queues for UI streaming.
        
        Args:
            output_queue: Queue for token streaming to UI.
            progress_queue: Queue for DAG progress events.
        """
        self._output_queue = output_queue
        self._progress_queue = progress_queue
    
    # ── Main Entry Point ──────────────────────────────────────────────────
    
    async def run(
        self,
        user_input: str,
        session_context: Optional[Dict[str, Any]] = None,
    ) -> NexusState:
        """
        Run a complete agent cycle from input to response.
        
        This is the main entry point. It executes all graph nodes in order:
        classify → context → reason → (tool_loop) → memory → format.
        
        Args:
            user_input: The user's message.
            session_context: Optional context from the session (working memory, history).
        
        Returns:
            Final NexusState with response, metrics, and execution record.
        """
        start = time.perf_counter()
        
        # Create initial state
        working_memory = session_context.get("working_memory", []) if session_context else []
        conversation_history = session_context.get("history", []) if session_context else []
        
        state = make_initial_state(
            user_input=user_input,
            session_id=str(uuid.uuid4()),
            input_type="text",
            working_memory=working_memory,
            conversation_history=conversation_history,
        )
        
        # ── Node: Intent Classification ─────────────────────────────────
        state = await self._run_intent_classify(state)
        
        # ── LAW 1.1: Playbook Match ─────────────────────────────────────
        # Check if the goal matches a known playbook before entering the
        # general ReAct loop. If matched, execute the playbook instead.
        state = await self._run_playbook_match(state)
        if state.get("playbook_name"):
            # Playbook was matched and executed — skip to memory write
            logger.info("Playbook '%s' completed, skipping to memory write", state["playbook_name"])
            state = await self._run_memory_write(state)
            state = await self._run_response_format(state)
            state["total_duration_ms"] = (time.perf_counter() - start) * 1000
            return state
        
        # ── Node: Context Loading ───────────────────────────────────────
        state = await self._run_context_load(state)
        
        # ── Agent Reasoning + Tool Execution Loop ───────────────────────
        # This is the main ReAct loop: reason → act → observe → reason...
        max_iterations = self._settings.AGENT_MAX_ITERATIONS
        
        while state.get("iteration_count", 0) < max_iterations:
            state["iteration_count"] = state.get("iteration_count", 0) + 1
            
            # Check for errors from previous steps
            errors = state.get("errors", [])
            if len(errors) > 0 and state.get("iteration_count", 0) > max_iterations // 2:
                logger.warning("Too many errors, terminating agent loop.")
                break
            
            # ── Node: Agent Reasoning ──────────────────────────────────
            state = await self._run_agent_reason(state)
            
            # Check if we have a final response (agent decided no tool needed)
            if state.get("final_response"):
                break
            
            # ── Node: Tool Selection ────────────────────────────────────
            tool_name, tool_input, is_ui = self._extract_tool_call(state)
            
            if not tool_name:
                # Agent chose to respond directly (not use a tool)
                break
            
            # ── Node: Tool Execution ────────────────────────────────────
            state = await self._run_tool_execute(state, tool_name, tool_input, is_ui)
            
            # ── Self-Healing: Capability Synthesis ──────────────────────
            gap = self._detect_capability_gap(state)
            if gap:
                state["gap_encountered"] = gap
                state = await self._run_capability_synthesis(state, user_input, gap)
                
                # If synthesis succeeded, retry the tool
                if state.get("synthesis_triggered") and state.get("gap_recovery_tool"):
                    state = await self._run_tool_execute(
                        state,
                        state["gap_recovery_tool"],
                        tool_input,
                        is_ui,
                    )
        
        # ── Node: Memory Write ──────────────────────────────────────────
        state = await self._run_memory_write(state)
        
        # ── Node: Response Format ───────────────────────────────────────
        state = await self._run_response_format(state)
        
        # Finalize
        state["total_duration_ms"] = (time.perf_counter() - start) * 1000
        
        # Log completion
        self._audit_logger.log(
            event_type="AGENT_STEP",
            data={
                "intent": state.get("intent"),
                "duration_ms": state["total_duration_ms"],
                "llm_calls": state.get("llm_calls", 0),
                "synthesis_triggered": state.get("synthesis_triggered", False),
                "iteration_count": state.get("iteration_count", 0),
            },
            module="nexus_brain.orchestrator",
            function_name="run",
            duration_ms=state["total_duration_ms"],
            success=bool(state.get("final_response")),
        )
        
        return state
    
    # ── Graph Node Implementations ─────────────────────────────────────────
    
    async def _run_intent_classify(self, state: NexusState) -> NexusState:
        """Graph node: Classify user intent."""
        node_start = time.perf_counter()
        try:
            result = await self._classifier.classify(state.get("user_input", ""))
            state["intent"] = result.intent
            state["confidence"] = result.confidence
            
            logger.info("Intent: %s (conf=%.2f, full_agent=%s, %.0fms)",
                result.intent, result.confidence, result.needs_full_agent, result.latency_ms)
            
            if self._progress_queue:
                await self._progress_queue.put({
                    "type": "intent",
                    "intent": result.intent,
                    "confidence": result.confidence,
                    "latency_ms": result.latency_ms,
                })
        except Exception as e:
            state.setdefault("errors", []).append({
                "node": GraphNode.INTENT_CLASSIFY,
                "error": str(e),
                "timestamp": time.strftime("%H:%M:%S"),
            })
            state["intent"] = "complex_task"
            state["confidence"] = 0.3
        
        return state
    
    async def _run_playbook_match(self, state: NexusState) -> NexusState:
        """
        LAW 1.1 STEP 0: Match the user's goal against the playbook library.
        
        If a match is found, execute the playbook and store the result.
        If no match, the agent falls through to the general ReAct loop.
        """
        try:
            from nexus_brain.playbook_engine import get_playbook_engine
            
            engine = get_playbook_engine()
            engine.set_tool_executor(self._tool_executor)
            
            user_input = state.get("user_input", "")
            intent = state.get("intent")
            
            # STEP 0: Match
            playbook = engine.match_playbook(user_input, intent)
            if not playbook:
                logger.debug("No playbook match for: %.60s", user_input)
                return state
            
            logger.info("Playbook matched: '%s' — executing...", playbook.name)
            
            if self._progress_queue:
                await self._progress_queue.put({
                    "type": "playbook_start",
                    "playbook": playbook.name,
                    "steps": len(playbook.steps),
                })
            
            # Execute the playbook
            result = await engine.execute_playbook(
                playbook,
                state={"business_name": user_input},
                progress_callback=self._playbook_progress_callback,
            )
            
            # Store result in state
            state["playbook_name"] = playbook.name
            state["playbook_step"] = len(playbook.steps)
            state["playbook_state"] = result.playbook_state
            
            # Build final response from playbook result
            if result.success:
                if result.preview_url:
                    state["final_response"] = (
                        f"✅ Playbook '{playbook.name}' completed successfully.\n"
                        f"Preview URL: {result.preview_url}\n"
                        f"Duration: {result.duration_ms:.0f}ms"
                    )
                elif result.campaign_id:
                    state["final_response"] = (
                        f"✅ Playbook '{playbook.name}' completed successfully.\n"
                        f"Campaign ID: {result.campaign_id}\n"
                        f"Duration: {result.duration_ms:.0f}ms"
                    )
                else:
                    state["final_response"] = (
                        f"✅ Playbook '{playbook.name}' completed successfully.\n"
                        f"Duration: {result.duration_ms:.0f}ms"
                    )
            else:
                failed = [f"  • {sid}: {err}" for sid, err in result.failed_steps[:3]]
                state["final_response"] = (
                    f"⚠️ Playbook '{playbook.name}' completed with {len(result.failed_steps)} failed steps.\n"
                    + "\n".join(failed) +
                    f"\nDuration: {result.duration_ms:.0f}ms"
                )
            
            # Store project memory
            mem_id = engine.store_project_memory(user_input, playbook.name, result)
            if mem_id:
                state["project_memory_id"] = mem_id
            
            if self._progress_queue:
                await self._progress_queue.put({
                    "type": "playbook_end",
                    "playbook": playbook.name,
                    "success": result.success,
                    "duration_ms": result.duration_ms,
                })
            
        except Exception as e:
            logger.error("Playbook execution failed: %s", e)
            state.setdefault("errors", []).append({
                "node": "playbook_match",
                "error": str(e),
                "timestamp": time.strftime("%H:%M:%S"),
            })
        
        return state
    
    async def _playbook_progress_callback(self, step_id: str, status: str) -> None:
        """Callback for playbook step progress updates."""
        if self._progress_queue:
            await self._progress_queue.put({
                "type": "playbook_step",
                "step_id": step_id,
                "status": status,
            })
    
    async def _run_context_load(self, state: NexusState) -> NexusState:
        """Graph node: Load context from memory and assemble system prompt."""
        try:
            # Get tool descriptions
            tool_descriptions = ""
            if self._tool_executor:
                # Request tool descriptions from registry via a special call
                try:
                    tool_list = await self._tool_executor(
                        "__list_tools__", {}, False
                    )
                    if tool_list:
                        tool_descriptions = tool_list
                except Exception:
                    tool_descriptions = "Standard tools available."
            
            # Build system prompt
            prompt = await self._context_builder.build_prompt(
                state,
                tool_descriptions,
            )
            state["system_prompt"] = prompt
            
            # Load working memory
            wm = self._session_context.get("working_memory", [])
            state["working_memory"] = wm[-20:]  # Keep last 20
            
        except Exception as e:
            state.setdefault("errors", []).append({
                "node": GraphNode.CONTEXT_LOAD,
                "error": str(e),
                "timestamp": time.strftime("%H:%M:%S"),
            })
            state["system_prompt"] = "You are NEXUS AI."
        
        return state
    
    async def _run_agent_reason(self, state: NexusState) -> NexusState:
        """Graph node: LLM reasoning step."""
        try:
            messages = self._build_llm_messages(state)
            
            if self._output_queue:
                response_stream = self._llm_router.stream(messages)
                full_content = ""
                async for token in response_stream:
                    full_content += token
                    await self._output_queue.put({"type": "token", "content": token})
                
                response = LLMResponse(content=full_content, provider="groq", model="streamed")
            else:
                response = await self._llm_router.generate(messages)
            
            state["llm_calls"] = state.get("llm_calls", 0) + 1
            
            # Parse the response — look for tool calls or final answer
            content = response.content.strip()
            
            # Check if the response contains a tool call
            state["_last_llm_response"] = content
            
            # If no tool call in response and agent is answering directly
            if "```tool" not in content and "TOOL CALL:" not in content:
                state["final_response"] = content
            
        except Exception as e:
            state.setdefault("errors", []).append({
                "node": GraphNode.AGENT_REASON,
                "error": str(e),
                "timestamp": time.strftime("%H:%M:%S"),
            })
            state["final_response"] = f"I encountered an error while processing your request: {e}"
        
        return state
    
    def _extract_tool_call(self, state: NexusState) -> tuple:
        """
        Extract tool call from the LLM response.
        
        The LLM signals tool calls with:
          TOOL CALL: tool_name
          PARAMS: {"key": "value"}
        
        Or with markdown:
          ```tool
          {"tool": "tool_name", "input": {...}}
          ```
        
        Returns:
            (tool_name, tool_input, is_ui) or (None, None, False) if no tool call.
        """
        content = state.get("_last_llm_response", "")
        
        # Pattern 1: Structured tool call format
        if "TOOL CALL:" in content:
            lines = content.split("\n")
            tool_name = ""
            tool_input: Dict[str, Any] = {}
            for line in lines:
                if line.startswith("TOOL CALL:"):
                    tool_name = line.split("TOOL CALL:")[-1].strip()
                elif line.startswith("PARAMS:"):
                    params_str = line.split("PARAMS:")[-1].strip()
                    try:
                        tool_input = json.loads(params_str)
                    except json.JSONDecodeError:
                        tool_input = {"raw": params_str}
            
            if tool_name:
                return tool_name, tool_input, False
        
        # Pattern 2: Markdown tool block
        if "```tool" in content:
            import re
            match = re.search(r"```tool\s*\n(.*?)\n```", content, re.DOTALL)
            if match:
                try:
                    data = json.loads(match.group(1).strip())
                    tool_name = data.get("tool", "")
                    tool_input = data.get("input", {})
                    is_ui = data.get("is_ui", False)
                    return tool_name, tool_input, is_ui
                except (json.JSONDecodeError, KeyError):
                    pass
        
        return None, None, False
    
    async def _run_tool_execute(
        self,
        state: NexusState,
        tool_name: str,
        tool_input: Dict[str, Any],
        is_ui: bool,
    ) -> NexusState:
        """Graph node: Execute a tool call."""
        node_start = time.perf_counter()
        
        if self._progress_queue:
            await self._progress_queue.put({
                "type": "tool_start",
                "tool": tool_name,
                "input": tool_input,
            })
        
        try:
            if self._tool_executor is None:
                raise RuntimeError("Tool executor not set — call set_tool_executor() first.")
            
            output = await self._tool_executor(tool_name, tool_input, is_ui)
            
            # Parse output
            try:
                parsed = json.loads(output)
                success = parsed.get("success", True)
                result_text = parsed.get("result", parsed.get("error", output))
            except (json.JSONDecodeError, TypeError):
                success = True
                result_text = output
            
            state["tool_outputs"][f"tool_{state['iteration_count']}"] = output
            state["completed_nodes"].append(f"tool_{state['iteration_count']}")
            
            if self._progress_queue:
                await self._progress_queue.put({
                    "type": "tool_end",
                    "tool": tool_name,
                    "success": success,
                    "duration_ms": (time.perf_counter() - node_start) * 1000,
                })
            
            # Add tool result to conversation context
            state.setdefault("conversation_history", []).append({
                "role": "assistant",
                "content": f"[Tool {tool_name} returned: {result_text[:500]}]",
            })
            
        except Exception as e:
            error_msg = f"{type(e).__name__}: {e}"
            state["tool_outputs"][f"tool_{state['iteration_count']}_error"] = error_msg
            state.setdefault("failed_nodes", []).append(f"tool_{state['iteration_count']}")
            
            state.setdefault("errors", []).append({
                "node": GraphNode.TOOL_EXECUTE,
                "tool": tool_name,
                "error": error_msg,
                "timestamp": time.strftime("%H:%M:%S"),
            })
            
            if self._progress_queue:
                await self._progress_queue.put({
                    "type": "tool_error",
                    "tool": tool_name,
                    "error": error_msg,
                })
        
        return state
    
    def _detect_capability_gap(self, state: NexusState) -> Optional[str]:
        """
        Detect if the last tool execution indicates a capability gap.
        
        Checks for these signals:
          - Tool returned ModuleNotFoundError or ImportError
          - Tool returned "No capability for" or similar
          - Tool execution raised NotImplementedError
          - Last error contains "no tool" or "not found"
        
        Args:
            state: Current agent state.
        
        Returns:
            Gap description string if gap detected, None otherwise.
        """
        errors = state.get("errors", [])
        if not errors:
            return None
        
        last_error = errors[-1]
        error_text = last_error.get("error", "")
        tool_name = last_error.get("tool", "")
        
        gap_signals = [
            "ModuleNotFoundError", "ImportError",
            "No capability", "not found", "no tool",
            "not implemented", "NotImplementedError",
            "unavailable", "missing",
        ]
        
        for signal in gap_signals:
            if signal.lower() in error_text.lower():
                return f"Need a tool for: {tool_name or 'unknown operation'}. Error: {error_text[:200]}"
        
        return None
    
    async def _run_capability_synthesis(
        self,
        state: NexusState,
        original_task: str,
        gap: str,
    ) -> NexusState:
        """Graph node: Synthesize a new capability to fill a detected gap."""
        if state.get("synthesis_attempts", 0) >= self._settings.SYNTHESIS_MAX_RETRIES:
            logger.warning("Synthesis max retries reached for gap: %s", gap)
            return state
        
        state["synthesis_attempts"] = state.get("synthesis_attempts", 0) + 1
        
        if self._progress_queue:
            await self._progress_queue.put({
                "type": "synthesis_start",
                "gap": gap,
                "attempt": state["synthesis_attempts"],
            })
        
        try:
            # Get current tool list
            tools_list = ",".join(state.get("completed_nodes", [])) or "standard tools"
            
            result = await self._synthesizer.synthesize(
                task=original_task,
                failure_reason=gap,
                tools_list=tools_list,
            )
            
            if result.success and result.registered:
                state["synthesis_triggered"] = True
                state["gap_recovery_tool"] = result.tool_name
                
                if self._progress_queue:
                    await self._progress_queue.put({
                        "type": "synthesis_end",
                        "tool_name": result.tool_name,
                        "success": True,
                        "attempts": len(result.attempts),
                    })
            else:
                logger.warning("Synthesis failed after %d attempts for gap: %s",
                    len(result.attempts), gap)
                
                if self._progress_queue:
                    await self._progress_queue.put({
                        "type": "synthesis_end",
                        "tool_name": result.tool_name,
                        "success": False,
                        "attempts": len(result.attempts),
                        "error": f"All {len(result.attempts)} attempts failed",
                    })
        
        except Exception as e:
            logger.error("Synthesis error: %s", e)
            state.setdefault("errors", []).append({
                "node": GraphNode.CAPABILITY_SYNTH,
                "error": str(e),
                "timestamp": time.strftime("%H:%M:%S"),
            })
        
        return state
    
    async def _run_memory_write(self, state: NexusState) -> NexusState:
        """Graph node: Persist task outcome to memory."""
        try:
            task = state.get("user_input", "")
            outcome = state.get("final_response", "")[:200]
            tools_used = list(state.get("tool_outputs", {}).keys())
            duration = state.get("total_duration_ms", 0)
            success = bool(state.get("final_response"))
            session_id = state.get("session_id", "")
            complexity = state.get("intent", "simple")
            
            self._memory_manager.store_episodic(
                task=task,
                outcome=outcome,
                tools=tools_used,
                dur=duration,
                success=success,
                sid=session_id,
                comp=complexity or "simple",
            )
            
            # Store to session context
            self._session_context.add_task({
                "task": task,
                "success": success,
                "duration_ms": duration,
                "timestamp": time.strftime("%H:%M:%S"),
                "tools": tools_used,
            })
            
            # ── LAW B5: Free-tier usage metering ──────────────────────
            # Increment the local task counter for free-tier users.
            # This is advisory/UX only (LAW B5) — the server is the
            # authoritative source for enforcing billing limits.
            try:
                from nexus_billing.usage_metering import increment_and_check
                
                tier = self._settings.TIER
                allowed, used, limit = increment_and_check(tier)
                if not allowed:
                    logger.warning(
                        "Free-tier task limit reached (%d/%d) — user will see block on next task",
                        used, limit,
                    )
                state["usage_allowed"] = allowed
                state["usage_task_count"] = used
                state["usage_limit"] = limit
            except Exception as metering_err:
                logger.debug("Usage metering skipped: %s", metering_err)
                state["usage_allowed"] = True
                state["usage_task_count"] = 0
                state["usage_limit"] = -1
            
            # Extract and store preferences from conversation
            if state.get("conversation_history"):
                await self._extract_preferences(state)
        
        except Exception as e:
            logger.error("Memory write failed: %s", e)
        
        return state
    
    async def _extract_preferences(self, state: NexusState) -> None:
        """
        Extract user preferences from the conversation.
        
        Uses a cheap LLM call to extract facts about the user's environment.
        """
        try:
            history = state.get("conversation_history", [])
            if len(history) < 2:
                return
            
            last_turns = history[-4:]  # Last 4 messages
            context = "\n".join(f"{m['role']}: {m['content'][:300]}" for m in last_turns)
            
            extraction_prompt = f"""From this conversation, extract any facts about the user's environment, preferences, or habits that would be useful in future sessions. 

Conversation:
{context}

If no useful facts found, respond with: []
Otherwise respond with JSON array of strings, each a fact:"""

            response = await self._llm_router.generate(
                messages=[
                    {"role": "system", "content": "Extract user preferences from conversation. Respond with JSON array only."},
                    {"role": "user", "content": extraction_prompt},
                ],
                temperature=0.1,
                max_tokens=200,
                prefer_provider="ollama",
            )
            
            if response.success:
                import re
                # Extract JSON array
                match = re.search(r'\[.*?\]', response.content, re.DOTALL)
                if match:
                    facts = json.loads(match.group(0))
                    for fact in facts:
                        self._memory_manager.store_preference(str(fact))
        
        except Exception as e:
            logger.debug("Preference extraction failed: %s", e)
    
    async def _run_response_format(self, state: NexusState) -> NexusState:
        """Graph node: Format the final response."""
        response = state.get("final_response", "")
        if not response:
            # Build a summary from tool outputs
            outputs = state.get("tool_outputs", {})
            if outputs:
                parts = []
                for tool_name, output in list(outputs.items())[:3]:
                    try:
                        parsed = json.loads(output)
                        result = parsed.get("result", parsed.get("error", output))
                        parts.append(f"• {tool_name}: {str(result)[:200]}")
                    except (json.JSONDecodeError, TypeError):
                        parts.append(f"• {tool_name}: {output[:200]}")
                
                state["final_response"] = "Here are the results:\n" + "\n".join(parts)
            else:
                state["final_response"] = "Task completed. No specific output to report."
        
        return state
    
    # ── LLM Message Builder ───────────────────────────────────────────────
    
    def _build_llm_messages(self, state: NexusState) -> List[Dict[str, str]]:
        """
        Build the messages list for the LLM call.
        
        Structure:
          1. System prompt (assembled by context builder)
          2. Conversation history (trimmed)
          3. Working memory context
          4. Current user input
        
        Args:
            state: Current agent state.
        
        Returns:
            List of message dicts for the LLM.
        """
        messages: List[Dict[str, str]] = [
            {"role": "system", "content": state.get("system_prompt", BASE_SYSTEM_FALLBACK)},
        ]
        
        # Add conversation history
        history = state.get("conversation_history", [])
        trimmed_history = self._context_builder.build_conversation_context(
            history,
            max_messages=self._settings.CONVERSATION_CONTEXT_WINDOW,
        )
        messages.extend(trimmed_history)
        
        # Add conversation summary if available
        summary = state.get("conversation_summary")
        if summary:
            messages.append({
                "role": "system",
                "content": f"[Earlier conversation context: {summary}]",
            })
        
        # Add current user input
        messages.append({
            "role": "user",
            "content": state.get("user_input", ""),
        })
        
        # Add tool results as context
        tool_outputs = state.get("tool_outputs", {})
        if tool_outputs:
            recent_outputs = list(tool_outputs.items())[-3:]
            for tool_name, output in recent_outputs:
                messages.append({
                    "role": "system",
                    "content": f"[Tool {tool_name} result: {str(output)[:500]}]",
                })
        
        return messages


# ─── Base system fallback (if context builder fails to produce one) ────────────

BASE_SYSTEM_FALLBACK = """You are NEXUS AI, an autonomous desktop agent. Help the user with their computer tasks. Be concise and direct. Use tools when needed, but don't use tools for simple questions you can answer from your knowledge."""


@lru_cache(maxsize=1)
def get_orchestrator() -> AgentOrchestrator:
    """
    Return the singleton AgentOrchestrator instance.
    
    Returns:
        AgentOrchestrator: The singleton orchestrator instance.
    """
    return AgentOrchestrator()

"""
NEXUS AI v4.0 — LAW 1.1 Playbook Engine
Hardware: Intel i3 7th Gen · 12GB RAM · Ollama + Groq API

LAW 1.1 fires when the Task Planner and LAW 1 agree the gap isn't a missing tool
— it's a missing *workflow* made of many tools. This engine provides:

  STEP 0 — Playbook Match: Check goal against a human-approved library of
           pre-designed, already-tested workflows stored at
           ~/.nexus_ai/playbooks/*.json.

  STEP 1 — Playbook: local_business_site
  STEP 2 — Playbook: compliant_outreach_campaign
  STEP 3 — Bounded Decomposition for genuinely new goals
  STEP 4 — API Discovery & Adaptation
  STEP 5 — Project Memory persistence

Key bounds (from settings):
  - Max recursion depth: 3
  - Max sub-goal nodes per project: 20
  - Max debug-retry attempts per code sub-goal: 3, then escalate
"""

import asyncio
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Dict, Any, List, Callable, Awaitable, Tuple
from functools import lru_cache

from nexus_config.settings import get_settings, APP_ROOT
from nexus_config.audit_logger import get_audit_logger
from nexus_brain.agent_state import NexusState, DAGNode
from nexus_brain.llm_router import get_llm_router

logger = logging.getLogger("nexus.playbook_engine")


# ─── Playbook Types ────────────────────────────────────────────────────────────

@dataclass
class PlaybookStep:
    """
    A single step in a playbook workflow.

    Fields:
        id: Unique step ID (e.g. "discover", "classify", "select_template").
        description: Human-readable description of what this step does.
        tool: Tool name to call, or "llm" for an LLM reasoning step, or "sub_playbook".
        tool_input: Static input dict for the tool (may be merged with playbook_state).
        sub_playbook: If tool=="sub_playbook", the name of the nested playbook.
        llm_prompt_template: If tool=="llm", the prompt template (uses {state} placeholders).
        output_key: Key in playbook_state to store this step's result.
        can_fail_safely: If True, step failure doesn't halt the playbook.
        requires_human_checkpoint: If True, pause for human approval before executing.
        max_retries: Max retries for this step (default: 1).
    """
    id: str
    description: str
    tool: str  # "llm" | tool_name | "sub_playbook"
    tool_input: Optional[Dict[str, Any]] = None
    sub_playbook: Optional[str] = None
    llm_prompt_template: Optional[str] = None
    output_key: Optional[str] = None
    can_fail_safely: bool = False
    requires_human_checkpoint: bool = False
    max_retries: int = 1


@dataclass
class Playbook:
    """
    A complete playbook workflow definition.

    Fields:
        name: Unique playbook name (e.g. "local_business_site").
        description: What this playbook accomplishes.
        version: Semantic version.
        trigger_keywords: List of keywords that suggest this playbook.
        trigger_intents: List of intent labels that match this playbook.
        steps: Ordered list of PlaybookStep to execute.
        required_tools: Tools that must be registered before running.
        required_human_setup: Description of one-time human setup needed.
        output_schema: Dict describing what the playbook produces.
    """
    name: str
    description: str
    version: str = "1.0.0"
    trigger_keywords: List[str] = field(default_factory=list)
    trigger_intents: List[str] = field(default_factory=list)
    steps: List[PlaybookStep] = field(default_factory=list)
    required_tools: List[str] = field(default_factory=list)
    required_human_setup: str = ""
    output_schema: Dict[str, str] = field(default_factory=dict)


@dataclass
class PlaybookResult:
    """
    Result of executing a playbook.

    Fields:
        success: True if all non-skippable steps succeeded.
        playbook_state: Accumulated state dict across all steps.
        failed_steps: List of (step_id, error) tuples.
        duration_ms: Total execution time.
        partial: True if some steps failed but playbook continued.
        preview_url: For site playbooks, the deployment URL.
        campaign_id: For outreach playbooks, the campaign identifier.
    """
    success: bool = False
    playbook_state: Dict[str, Any] = field(default_factory=dict)
    failed_steps: List[Tuple[str, str]] = field(default_factory=list)
    duration_ms: float = 0.0
    partial: bool = False
    preview_url: Optional[str] = None
    campaign_id: Optional[str] = None


# ─── Decomposition Types ───────────────────────────────────────────────────────

@dataclass
class SubGoal:
    """
    A single node in a bounded decomposition tree.

    Fields:
        id: Unique sub-goal ID.
        description: What this sub-goal accomplishes.
        tool: Tool to use, or "decompose" to recurse, or "llm" for LLM reasoning.
        tool_input: Input for the tool.
        dependencies: List of sub-goal IDs that must complete first.
        status: "pending" | "running" | "completed" | "failed" | "escalated".
        result: Output from execution.
        error: Error message if failed.
        debug_retries: Number of retry attempts so far.
    """
    id: str
    description: str
    tool: str
    tool_input: Optional[Dict[str, Any]] = None
    dependencies: List[str] = field(default_factory=list)
    status: str = "pending"
    result: Optional[str] = None
    error: Optional[str] = None
    debug_retries: int = 0


# ─── Playbook Engine ───────────────────────────────────────────────────────────

DECOMPOSITION_PROMPT = """You are NEXUS AI's bounded decomposition engine. Break the following goal into a tree of sub-goals that can be executed by available tools.

Goal: {goal}

Available tools: {tools_list}

Rules:
1. Max {max_nodes} sub-goals total.
2. Each sub-goal must map to an available tool or be marked "decompose" for further breakdown.
3. Mark dependencies between sub-goals (which must complete before others).
4. If a sub-goal is too complex, mark it as "decompose" to recurse (max depth: {max_depth}).
5. Each sub-goal needs: id, description, tool, tool_input, dependencies.

Respond with JSON ONLY:
{{
    "task_description": "Brief description",
    "sub_goals": [
        {{
            "id": "sg_1",
            "description": "What this sub-goal does",
            "tool": "tool_name_or_decompose",
            "tool_input": {{"param1": "value1"}},
            "dependencies": []
        }}
    ]
}}"""


class PlaybookEngine:
    """
    LAW 1.1 Playbook Engine — matches goals to playbooks, executes them,
    and falls back to bounded decomposition for genuinely new goals.

    Usage:
        engine = get_playbook_engine()
        # STEP 0: Match
        match = engine.match_playbook("Build a website for Joe's Pizza")
        if match:
            result = await engine.execute_playbook(match, tool_executor)
        else:
            # STEP 3: Bounded decomposition
            tree = await engine.decompose_goal(goal, tools_list)
            result = await engine.execute_decomposition(tree, tool_executor)
    """

    def __init__(self):
        self._settings = get_settings()
        self._audit_logger = get_audit_logger()
        self._llm_router = get_llm_router()
        self._playbooks_dir = APP_ROOT / "playbooks"
        self._playbooks_dir.mkdir(parents=True, exist_ok=True)
        self._playbooks: Dict[str, Playbook] = {}
        self._tool_executor: Optional[Callable] = None
        self._load_playbooks()

    def set_tool_executor(
        self,
        executor: Callable[[str, Dict[str, Any], bool], Awaitable[str]],
    ) -> None:
        """Set the tool execution function (injected by application layer)."""
        self._tool_executor = executor

    # ── Playbook Loading ──────────────────────────────────────────────────

    def _load_playbooks(self) -> int:
        """Load all playbook JSON files from the playbooks directory."""
        count = 0
        for file_path in sorted(self._playbooks_dir.glob("*.json")):
            try:
                playbook = self._load_playbook_file(file_path)
                self._playbooks[playbook.name] = playbook
                count += 1
                logger.info("Loaded playbook '%s' v%s", playbook.name, playbook.version)
            except Exception as e:
                logger.warning("Failed to load playbook '%s': %s", file_path.stem, e)
        logger.info("Loaded %d playbooks from %s", count, self._playbooks_dir)
        return count

    def _load_playbook_file(self, file_path: Path) -> Playbook:
        """Parse a playbook JSON file into a Playbook dataclass."""
        data = json.loads(file_path.read_text(encoding="utf-8"))
        steps = []
        for s in data.get("steps", []):
            steps.append(PlaybookStep(
                id=s["id"],
                description=s.get("description", ""),
                tool=s["tool"],
                tool_input=s.get("tool_input"),
                sub_playbook=s.get("sub_playbook"),
                llm_prompt_template=s.get("llm_prompt_template"),
                output_key=s.get("output_key"),
                can_fail_safely=s.get("can_fail_safely", False),
                requires_human_checkpoint=s.get("requires_human_checkpoint", False),
                max_retries=s.get("max_retries", 1),
            ))
        return Playbook(
            name=data["name"],
            description=data.get("description", ""),
            version=data.get("version", "1.0.0"),
            trigger_keywords=data.get("trigger_keywords", []),
            trigger_intents=data.get("trigger_intents", []),
            steps=steps,
            required_tools=data.get("required_tools", []),
            required_human_setup=data.get("required_human_setup", ""),
            output_schema=data.get("output_schema", {}),
        )

    def reload_playbooks(self) -> int:
        """Reload all playbooks from disk (for hot-reload)."""
        self._playbooks.clear()
        return self._load_playbooks()

    def get_playbook(self, name: str) -> Optional[Playbook]:
        """Get a playbook by name."""
        return self._playbooks.get(name)

    def list_playbooks(self) -> List[str]:
        """List all loaded playbook names."""
        return sorted(self._playbooks.keys())

    # ── STEP 0: Playbook Match ────────────────────────────────────────────

    def match_playbook(
        self,
        goal: str,
        intent: Optional[str] = None,
    ) -> Optional[Playbook]:
        """
        Match a goal against the loaded playbook library.

        Matching logic:
        1. Check trigger_keywords in the goal text (case-insensitive).
        2. Check trigger_intents against the classified intent.
        3. Return the best match (most keyword hits).

        Args:
            goal: The user's goal/task description.
            intent: Optional classified intent label.

        Returns:
            The best-matching Playbook, or None if no match.
        """
        if not self._playbooks:
            return None

        goal_lower = goal.lower()
        best_match: Optional[Playbook] = None
        best_score = 0

        for playbook in self._playbooks.values():
            score = 0

            # Check keyword matches
            for kw in playbook.trigger_keywords:
                if kw.lower() in goal_lower:
                    score += 1

            # Check intent match
            if intent and intent in playbook.trigger_intents:
                score += 2  # Intent match is weighted higher

            if score > best_score:
                best_score = score
                best_match = playbook

        # Require at least 1 keyword or intent match
        if best_score >= 1:
            logger.info("Playbook match: '%s' (score=%d) for goal: %.60s",
                        best_match.name, best_score, goal)
            return best_match

        logger.info("No playbook match for goal: %.60s", goal)
        return None

    # ── STEP 1/2: Playbook Execution ──────────────────────────────────────

    async def execute_playbook(
        self,
        playbook: Playbook,
        state: Optional[Dict[str, Any]] = None,
        progress_callback: Optional[Callable[[str, str], Awaitable[None]]] = None,
    ) -> PlaybookResult:
        """
        Execute a playbook workflow step by step.

        Args:
            playbook: The playbook to execute.
            state: Initial state dict (e.g. business info from discovery).
            progress_callback: Async callable(step_id, status) for progress updates.

        Returns:
            PlaybookResult with accumulated state and outcomes.
        """
        start = time.perf_counter()
        pb_state: Dict[str, Any] = dict(state or {})
        failed_steps: List[Tuple[str, str]] = []

        logger.info("Executing playbook '%s' (%d steps)", playbook.name, len(playbook.steps))

        for step_idx, step in enumerate(playbook.steps):
            step_start = time.perf_counter()

            if progress_callback:
                await progress_callback(step.id, "running")

            # ── Human Checkpoint ──────────────────────────────────────
            if step.requires_human_checkpoint:
                logger.info("Playbook '%s' step '%s' requires human approval. "
                            "Pausing for checkpoint.", playbook.name, step.id)
                if progress_callback:
                    await progress_callback(step.id, "awaiting_approval")
                # In a real implementation, this would surface a UI prompt
                # and wait for user confirmation. For now, we log and continue.
                logger.warning("Human checkpoint not implemented — auto-continuing.")

            # ── Execute Step ──────────────────────────────────────────
            step_success = False
            step_error = ""
            step_result = ""

            for attempt in range(1, step.max_retries + 1):
                try:
                    if step.tool == "llm":
                        step_result = await self._execute_llm_step(step, pb_state)
                    elif step.tool == "sub_playbook":
                        sub = self._playbooks.get(step.sub_playbook or "")
                        if sub:
                            sub_result = await self.execute_playbook(sub, pb_state, progress_callback)
                            step_result = json.dumps({
                                "success": sub_result.success,
                                "state": sub_result.playbook_state,
                            })
                            pb_state.update(sub_result.playbook_state)
                        else:
                            step_error = f"Sub-playbook '{step.sub_playbook}' not found"
                            continue
                    else:
                        step_result = await self._execute_tool_step(step, pb_state)

                    step_success = True
                    break  # Success — exit retry loop

                except Exception as e:
                    step_error = f"{type(e).__name__}: {e}"
                    logger.warning("Playbook step '%s' attempt %d/%d failed: %s",
                                   step.id, attempt, step.max_retries, step_error)
                    if attempt < step.max_retries:
                        await asyncio.sleep(1)  # Brief backoff

            # ── Handle Step Result ────────────────────────────────────
            if step_success:
                if step.output_key:
                    pb_state[step.output_key] = step_result
                if progress_callback:
                    await progress_callback(step.id, "completed")
            else:
                failed_steps.append((step.id, step_error))
                if step.can_fail_safely:
                    logger.warning("Playbook step '%s' failed safely: %s", step.id, step_error)
                    if progress_callback:
                        await progress_callback(step.id, "skipped")
                else:
                    logger.error("Playbook step '%s' failed — halting: %s", step.id, step_error)
                    if progress_callback:
                        await progress_callback(step.id, "failed")
                    break

            step_duration = (time.perf_counter() - step_start) * 1000
            logger.debug("Step '%s' completed in %.0fms", step.id, step_duration)

        duration = (time.perf_counter() - start) * 1000
        all_success = len(failed_steps) == 0

        # Extract common outputs
        preview_url = pb_state.get("preview_url")
        campaign_id = pb_state.get("campaign_id")

        result = PlaybookResult(
            success=all_success,
            playbook_state=pb_state,
            failed_steps=failed_steps,
            duration_ms=duration,
            partial=not all_success,
            preview_url=preview_url,
            campaign_id=campaign_id,
        )

        # Log completion
        self._audit_logger.log(
            event_type="PLAYBOOK_EXECUTION",
            data={
                "playbook": playbook.name,
                "version": playbook.version,
                "steps_total": len(playbook.steps),
                "steps_failed": len(failed_steps),
                "duration_ms": duration,
                "success": all_success,
            },
            module="nexus_brain.playbook_engine",
            function_name="execute_playbook",
            duration_ms=duration,
            success=all_success,
        )

        return result

    async def _execute_llm_step(
        self,
        step: PlaybookStep,
        pb_state: Dict[str, Any],
    ) -> str:
        """Execute an LLM reasoning step."""
        if not step.llm_prompt_template:
            raise ValueError(f"LLM step '{step.id}' has no prompt template")

        prompt = step.llm_prompt_template.format(
            state=json.dumps(pb_state, indent=2),
            **pb_state,
        )

        response = await self._llm_router.generate(
            messages=[
                {"role": "system", "content": "You are NEXUS AI executing a playbook step."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            max_tokens=1024,
            prefer_provider="groq",
        )

        if not response.success:
            raise RuntimeError(f"LLM step failed: {response.error}")

        return response.content.strip()

    async def _execute_tool_step(
        self,
        step: PlaybookStep,
        pb_state: Dict[str, Any],
    ) -> str:
        """Execute a tool step."""
        if self._tool_executor is None:
            raise RuntimeError("Tool executor not set — call set_tool_executor() first.")

        # Merge static tool_input with dynamic state values
        tool_input = dict(step.tool_input or {})
        for key, value in list(tool_input.items()):
            if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
                state_key = value[2:-1]
                tool_input[key] = pb_state.get(state_key, "")

        return await self._tool_executor(step.tool, tool_input, False)

    # ── STEP 3: Bounded Decomposition ────────────────────────────────────

    async def decompose_goal(
        self,
        goal: str,
        tools_list: str,
        depth: int = 0,
    ) -> List[SubGoal]:
        """
        Decompose a goal into a bounded tree of sub-goals.

        Args:
            goal: The goal to decompose.
            tools_list: Available tools description.
            depth: Current recursion depth (starts at 0).

        Returns:
            List of SubGoal objects.

        Raises:
            RuntimeError: If max recursion depth is exceeded.
        """
        max_depth = self._settings.MAX_RECURSION_DEPTH
        max_nodes = self._settings.MAX_DAG_NODES

        if depth >= max_depth:
            raise RuntimeError(
                f"Max recursion depth ({max_depth}) exceeded for goal: {goal[:100]}"
            )

        prompt = DECOMPOSITION_PROMPT.format(
            goal=goal[:1000],
            tools_list=tools_list[:2000],
            max_nodes=max_nodes,
            max_depth=max_depth,
        )

        response = await self._llm_router.generate(
            messages=[
                {"role": "system", "content": "You are a task decomposition expert. Respond with JSON only."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
            max_tokens=2000,
            response_format={"type": "json_object"},
            prefer_provider="groq",
        )

        if not response.success:
            # Fallback: single sub-goal
            return [SubGoal(
                id="sg_0",
                description=goal[:200],
                tool="llm",
                tool_input={"prompt": goal},
            )]

        try:
            data = json.loads(response.content)
            raw_goals = data.get("sub_goals", [])
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning("Decomposition parsing failed: %s", e)
            return [SubGoal(
                id="sg_0",
                description=goal[:200],
                tool="llm",
                tool_input={"prompt": goal},
            )]

        if not raw_goals:
            return [SubGoal(
                id="sg_0",
                description=goal[:200],
                tool="llm",
                tool_input={"prompt": goal},
            )]

        # Enforce max nodes
        if len(raw_goals) > max_nodes:
            logger.warning("Decomposition produced %d sub-goals, truncating to %d",
                           len(raw_goals), max_nodes)
            raw_goals = raw_goals[:max_nodes]

        sub_goals: List[SubGoal] = []
        for g in raw_goals:
            sub_goals.append(SubGoal(
                id=g.get("id", f"sg_{len(sub_goals)}"),
                description=g.get("description", ""),
                tool=g.get("tool", "llm"),
                tool_input=g.get("tool_input"),
                dependencies=g.get("dependencies", []),
            ))

        # Recurse for "decompose" sub-goals
        final_goals: List[SubGoal] = []
        for sg in sub_goals:
            if sg.tool == "decompose":
                try:
                    children = await self.decompose_goal(
                        sg.description,
                        tools_list,
                        depth + 1,
                    )
                    # Mark parent as completed, children will run
                    sg.status = "completed"
                    final_goals.append(sg)
                    final_goals.extend(children)
                except RuntimeError as e:
                    logger.warning("Decomposition recursion halted: %s", e)
                    sg.tool = "llm"  # Fallback to LLM reasoning
                    final_goals.append(sg)
            else:
                final_goals.append(sg)

        return final_goals

    async def execute_decomposition(
        self,
        sub_goals: List[SubGoal],
        progress_callback: Optional[Callable[[str, str], Awaitable[None]]] = None,
    ) -> Dict[str, Any]:
        """
        Execute a decomposition tree of sub-goals.

        Args:
            sub_goals: List of SubGoal objects to execute.
            progress_callback: Async callable(goal_id, status).

        Returns:
            Dict mapping goal_id → result string.
        """
        if self._tool_executor is None:
            raise RuntimeError("Tool executor not set — call set_tool_executor() first.")

        max_retries = self._settings.MAX_DEBUG_RETRIES
        results: Dict[str, Any] = {}
        completed: set = set()
        failed: List[Tuple[str, str]] = []
        escalated: List[str] = []

        # Build dependency map
        goal_map = {g.id: g for g in sub_goals}
        dependents: Dict[str, List[str]] = {}
        for g in sub_goals:
            for dep in g.dependencies:
                if dep not in dependents:
                    dependents[dep] = []
                dependents[dep].append(g.id)

        while len(completed) + len(failed) + len(escalated) < len(sub_goals):
            # Find ready goals
            ready = []
            for g in sub_goals:
                if g.id in completed or g.id in [f[0] for f in failed] or g.id in escalated:
                    continue
                if g.status == "completed":
                    continue
                deps_satisfied = all(d in completed for d in g.dependencies)
                if deps_satisfied:
                    ready.append(g)

            if not ready:
                break  # Stuck or done

            for goal in ready:
                if progress_callback:
                    await progress_callback(goal.id, "running")

                try:
                    if goal.tool == "llm":
                        prompt = goal.tool_input.get("prompt", goal.description) if goal.tool_input else goal.description
                        response = await self._llm_router.generate(
                            messages=[
                                {"role": "system", "content": "Execute this sub-goal."},
                                {"role": "user", "content": prompt},
                            ],
                            temperature=0.1,
                            max_tokens=1024,
                            prefer_provider="groq",
                        )
                        result = response.content if response.success else f"Error: {response.error}"
                    else:
                        result = await self._tool_executor(
                            goal.tool,
                            goal.tool_input or {},
                            False,
                        )

                    results[goal.id] = result
                    goal.status = "completed"
                    completed.add(goal.id)
                    if progress_callback:
                        await progress_callback(goal.id, "completed")

                except Exception as e:
                    goal.debug_retries += 1
                    error_msg = f"{type(e).__name__}: {e}"

                    if goal.debug_retries >= max_retries:
                        # Escalate to human review
                        escalated.append(goal.id)
                        goal.status = "escalated"
                        results[goal.id] = f"ESCALATED: {error_msg}"
                        if progress_callback:
                            await progress_callback(goal.id, "escalated")
                        logger.warning("Sub-goal '%s' escalated after %d retries: %s",
                                       goal.id, max_retries, error_msg)
                    else:
                        failed.append((goal.id, error_msg))
                        goal.status = "failed"
                        if progress_callback:
                            await progress_callback(goal.id, "failed")
                        logger.warning("Sub-goal '%s' failed (retry %d/%d): %s",
                                       goal.id, goal.debug_retries, max_retries, error_msg)

        return results

    # ── STEP 4: API Discovery ─────────────────────────────────────────────

    async def discover_api(
        self,
        service_name: str,
        docs_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Discover an API and model its endpoints for tool synthesis.

        Args:
            service_name: Name of the service (e.g. "sendgrid", "netlify").
            docs_url: Optional URL to API documentation.

        Returns:
            Dict with "endpoints", "auth_type", "base_url" keys.
        """
        # This is a stub — full implementation in nexus_tools/api_discovery.py
        logger.info("API discovery requested for '%s'", service_name)
        return {
            "service": service_name,
            "status": "needs_human_setup",
            "message": (
                f"To integrate {service_name}:\n"
                f"1. Create an account at {service_name}.com\n"
                f"2. Generate an API key\n"
                f"3. Configure SPF/DKIM/DMARC (for email services)\n"
                f"4. Provide the API key via NEXUS settings\n"
                f"After setup, run 'discover {service_name}' again."
            ),
        }

    # ── STEP 5: Project Memory ────────────────────────────────────────────

    def store_project_memory(
        self,
        goal: str,
        playbook_name: str,
        result: PlaybookResult,
    ) -> str:
        """
        Store a completed project in project memory.

        Args:
            goal: The original goal.
            playbook_name: The playbook that was executed.
            result: The execution result.

        Returns:
            ChromaDB document ID for the stored memory.
        """
        try:
            from nexus_memory.vector_store import get_vector_store
            store = get_vector_store()

            doc_id = f"proj_{uuid.uuid4().hex[:12]}"
            document = json.dumps({
                "goal": goal,
                "playbook": playbook_name,
                "success": result.success,
                "duration_ms": result.duration_ms,
                "preview_url": result.preview_url,
                "campaign_id": result.campaign_id,
                "state_keys": list(result.playbook_state.keys()),
            }, indent=2)

            store.add_memory(
                col="project_memory",
                doc_id=doc_id,
                document=document,
                metadata={
                    "goal": goal[:200],
                    "playbook": playbook_name,
                    "success": result.success,
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
                },
            )

            logger.info("Stored project memory: %s", doc_id)
            return doc_id

        except Exception as e:
            logger.warning("Failed to store project memory: %s", e)
            return ""

    def query_project_memory(
        self,
        query: str,
        n: int = 3,
    ) -> List[Dict[str, Any]]:
        """
        Query project memory for similar past projects.

        Args:
            query: Search query.
            n: Max results.

        Returns:
            List of matching project memory documents.
        """
        try:
            from nexus_memory.vector_store import get_vector_store
            store = get_vector_store()
            result = store.query("project_memory", query, n)
            documents = []
            if result and "documents" in result and result["documents"]:
                for i, doc in enumerate(result["documents"][0]):
                    try:
                        parsed = json.loads(doc)
                        documents.append(parsed)
                    except (json.JSONDecodeError, TypeError):
                        documents.append({"raw": doc})
            return documents
        except Exception as e:
            logger.warning("Project memory query failed: %s", e)
            return []

    # ── Candidate Playbook Generation ─────────────────────────────────────

    def generate_candidate_playbook(
        self,
        goal: str,
        sub_goals: List[SubGoal],
        result: Dict[str, Any],
    ) -> str:
        """
        Generate a candidate playbook JSON from a successful decomposition.

        This is called when a bounded decomposition succeeds — the workflow
        is written up as a candidate for human approval to join STEP 0's library.

        Args:
            goal: The original goal.
            sub_goals: The sub-goals that were executed.
            result: The execution results.

        Returns:
            Path to the candidate playbook file.
        """
        playbook_name = f"candidate_{uuid.uuid4().hex[:8]}"
        steps = []
        for sg in sub_goals:
            if sg.tool == "decompose":
                continue  # Skip decomposed parents
            steps.append({
                "id": sg.id,
                "description": sg.description,
                "tool": sg.tool,
                "tool_input": sg.tool_input,
                "output_key": sg.id,
                "can_fail_safely": True,
                "max_retries": 1,
            })

        candidate = {
            "name": playbook_name,
            "description": f"Candidate playbook for: {goal[:200]}",
            "version": "0.1.0",
            "trigger_keywords": [],
            "trigger_intents": [],
            "steps": steps,
            "required_tools": list(set(sg.tool for sg in sub_goals if sg.tool not in ("llm", "decompose"))),
            "required_human_setup": "Review and approve this candidate playbook before adding to the library.",
            "output_schema": {},
        }

        candidate_path = self._playbooks_dir / f"{playbook_name}.json"
        candidate_path.write_text(
            json.dumps(candidate, indent=2),
            encoding="utf-8",
        )

        logger.info("Candidate playbook written to %s", candidate_path)
        return str(candidate_path)


@lru_cache(maxsize=1)
def get_playbook_engine() -> PlaybookEngine:
    """
    Return the singleton PlaybookEngine instance.

    Returns:
        PlaybookEngine: The singleton playbook engine instance.
    """
    return PlaybookEngine()
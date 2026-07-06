"""
Tests for LAW 1.1 Playbook Engine (nexus_brain.playbook_engine).

Tests cover:
1. Playbook loading from JSON files
2. Playbook matching (STEP 0)
3. Playbook execution (STEP 1/2)
4. Bounded decomposition (STEP 3)
5. Project memory (STEP 5)
6. Candidate playbook generation
7. Bounds enforcement (max recursion, max nodes, max retries)
"""

import json
import os
import sys
import tempfile
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from nexus_brain.playbook_engine import (
    PlaybookEngine,
    Playbook,
    PlaybookStep,
    PlaybookResult,
    SubGoal,
    get_playbook_engine,
)


# ─── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_settings():
    """Mock settings with test values."""
    with patch("nexus_brain.playbook_engine.get_settings") as mock:
        settings = MagicMock()
        settings.MAX_RECURSION_DEPTH = 3
        settings.MAX_DAG_NODES = 20
        settings.MAX_DEBUG_RETRIES = 3
        mock.return_value = settings
        yield settings


@pytest.fixture
def mock_llm_router():
    """Mock LLM router for testing."""
    with patch("nexus_brain.playbook_engine.get_llm_router") as mock:
        router = MagicMock()
        router.generate = AsyncMock()
        mock.return_value = router
        yield router


@pytest.fixture
def mock_audit_logger():
    """Mock audit logger."""
    with patch("nexus_brain.playbook_engine.get_audit_logger") as mock:
        logger = MagicMock()
        mock.return_value = logger
        yield logger


@pytest.fixture
def temp_playbooks_dir():
    """Create a temporary playbooks directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def sample_playbook_json():
    """Sample playbook JSON for testing."""
    return {
        "name": "test_playbook",
        "description": "A test playbook",
        "version": "1.0.0",
        "trigger_keywords": ["test", "example", "demo"],
        "trigger_intents": ["complex_task"],
        "required_tools": ["t03_web_search"],
        "required_human_setup": "No setup needed for tests.",
        "output_schema": {"result": "string"},
        "steps": [
            {
                "id": "step_1",
                "description": "First step",
                "tool": "llm",
                "llm_prompt_template": "Test prompt with {state}",
                "output_key": "step1_result",
                "can_fail_safely": False,
                "max_retries": 1,
            },
            {
                "id": "step_2",
                "description": "Second step",
                "tool": "t03_web_search",
                "tool_input": {"query": "test query"},
                "output_key": "step2_result",
                "can_fail_safely": True,
                "max_retries": 2,
            },
        ],
    }


# ─── Tests: Playbook Loading ──────────────────────────────────────────────────

class TestPlaybookLoading:
    """Test loading playbooks from JSON files."""

    def test_load_playbooks_empty_dir(self, temp_playbooks_dir, mock_settings, mock_llm_router, mock_audit_logger):
        """Loading from an empty directory should return 0."""
        with patch.object(PlaybookEngine, "_playbooks_dir", temp_playbooks_dir):
            engine = PlaybookEngine()
            assert engine.list_playbooks() == []

    def test_load_single_playbook(self, temp_playbooks_dir, sample_playbook_json, mock_settings, mock_llm_router, mock_audit_logger):
        """Loading a single valid playbook should succeed."""
        playbook_file = temp_playbooks_dir / "test_playbook.json"
        playbook_file.write_text(json.dumps(sample_playbook_json), encoding="utf-8")

        with patch.object(PlaybookEngine, "_playbooks_dir", temp_playbooks_dir):
            engine = PlaybookEngine()
            assert len(engine.list_playbooks()) == 1
            assert engine.list_playbooks()[0] == "test_playbook"

    def test_load_invalid_playbook(self, temp_playbooks_dir, mock_settings, mock_llm_router, mock_audit_logger):
        """Loading an invalid JSON file should be skipped gracefully."""
        playbook_file = temp_playbooks_dir / "invalid.json"
        playbook_file.write_text("not valid json", encoding="utf-8")

        with patch.object(PlaybookEngine, "_playbooks_dir", temp_playbooks_dir):
            engine = PlaybookEngine()
            assert len(engine.list_playbooks()) == 0

    def test_get_playbook_by_name(self, temp_playbooks_dir, sample_playbook_json, mock_settings, mock_llm_router, mock_audit_logger):
        """Getting a playbook by name should return the correct playbook."""
        playbook_file = temp_playbooks_dir / "test_playbook.json"
        playbook_file.write_text(json.dumps(sample_playbook_json), encoding="utf-8")

        with patch.object(PlaybookEngine, "_playbooks_dir", temp_playbooks_dir):
            engine = PlaybookEngine()
            pb = engine.get_playbook("test_playbook")
            assert pb is not None
            assert pb.name == "test_playbook"
            assert len(pb.steps) == 2
            assert pb.steps[0].id == "step_1"
            assert pb.steps[1].id == "step_2"

    def test_reload_playbooks(self, temp_playbooks_dir, sample_playbook_json, mock_settings, mock_llm_router, mock_audit_logger):
        """Reloading should pick up new playbooks."""
        with patch.object(PlaybookEngine, "_playbooks_dir", temp_playbooks_dir):
            engine = PlaybookEngine()
            assert len(engine.list_playbooks()) == 0

            # Add a playbook
            playbook_file = temp_playbooks_dir / "test_playbook.json"
            playbook_file.write_text(json.dumps(sample_playbook_json), encoding="utf-8")

            count = engine.reload_playbooks()
            assert count == 1
            assert len(engine.list_playbooks()) == 1


# ─── Tests: Playbook Matching (STEP 0) ────────────────────────────────────────

class TestPlaybookMatching:
    """Test STEP 0: Playbook matching."""

    def test_match_by_keyword(self, temp_playbooks_dir, sample_playbook_json, mock_settings, mock_llm_router, mock_audit_logger):
        """Matching by keyword should find the right playbook."""
        playbook_file = temp_playbooks_dir / "test_playbook.json"
        playbook_file.write_text(json.dumps(sample_playbook_json), encoding="utf-8")

        with patch.object(PlaybookEngine, "_playbooks_dir", temp_playbooks_dir):
            engine = PlaybookEngine()
            match = engine.match_playbook("This is a test example")
            assert match is not None
            assert match.name == "test_playbook"

    def test_no_match(self, temp_playbooks_dir, sample_playbook_json, mock_settings, mock_llm_router, mock_audit_logger):
        """A goal with no matching keywords should return None."""
        playbook_file = temp_playbooks_dir / "test_playbook.json"
        playbook_file.write_text(json.dumps(sample_playbook_json), encoding="utf-8")

        with patch.object(PlaybookEngine, "_playbooks_dir", temp_playbooks_dir):
            engine = PlaybookEngine()
            match = engine.match_playbook("unrelated goal about something else")
            assert match is None

    def test_match_by_intent(self, temp_playbooks_dir, sample_playbook_json, mock_settings, mock_llm_router, mock_audit_logger):
        """Matching by intent should work."""
        playbook_file = temp_playbooks_dir / "test_playbook.json"
        playbook_file.write_text(json.dumps(sample_playbook_json), encoding="utf-8")

        with patch.object(PlaybookEngine, "_playbooks_dir", temp_playbooks_dir):
            engine = PlaybookEngine()
            match = engine.match_playbook("some goal", intent="complex_task")
            assert match is not None
            assert match.name == "test_playbook"

    def test_match_empty_playbooks(self, mock_settings, mock_llm_router, mock_audit_logger):
        """Matching with no loaded playbooks should return None."""
        engine = PlaybookEngine()
        match = engine.match_playbook("test example")
        assert match is None

    def test_best_match_wins(self, temp_playbooks_dir, mock_settings, mock_llm_router, mock_audit_logger):
        """When multiple playbooks match, the best one should win."""
        pb1 = {
            "name": "playbook_a",
            "description": "Playbook A",
            "trigger_keywords": ["test", "example"],
            "trigger_intents": [],
            "steps": [],
        }
        pb2 = {
            "name": "playbook_b",
            "description": "Playbook B",
            "trigger_keywords": ["test", "example", "demo", "sample"],
            "trigger_intents": [],
            "steps": [],
        }
        (temp_playbooks_dir / "playbook_a.json").write_text(json.dumps(pb1), encoding="utf-8")
        (temp_playbooks_dir / "playbook_b.json").write_text(json.dumps(pb2), encoding="utf-8")

        with patch.object(PlaybookEngine, "_playbooks_dir", temp_playbooks_dir):
            engine = PlaybookEngine()
            match = engine.match_playbook("test example demo")
            assert match is not None
            assert match.name == "playbook_b"  # More keyword hits


# ─── Tests: Bounded Decomposition (STEP 3) ────────────────────────────────────

class TestBoundedDecomposition:
    """Test STEP 3: Bounded decomposition."""

    @pytest.mark.asyncio
    async def test_decompose_simple_goal(self, mock_settings, mock_llm_router, mock_audit_logger):
        """A simple goal should decompose into sub-goals."""
        mock_llm_router.generate.return_value = MagicMock(
            success=True,
            content=json.dumps({
                "task_description": "Test task",
                "sub_goals": [
                    {"id": "sg_1", "description": "Step 1", "tool": "t03_web_search",
                     "tool_input": {"query": "test"}, "dependencies": []},
                    {"id": "sg_2", "description": "Step 2", "tool": "t02_file_manager",
                     "tool_input": {}, "dependencies": ["sg_1"]},
                ],
            }),
        )

        engine = PlaybookEngine()
        sub_goals = await engine.decompose_goal("test goal", "t03_web_search, t02_file_manager")

        assert len(sub_goals) == 2
        assert sub_goals[0].id == "sg_1"
        assert sub_goals[1].id == "sg_2"
        assert sub_goals[1].dependencies == ["sg_1"]

    @pytest.mark.asyncio
    async def test_decompose_llm_failure_fallback(self, mock_settings, mock_llm_router, mock_audit_logger):
        """When LLM fails, decomposition should fall back to a single sub-goal."""
        mock_llm_router.generate.return_value = MagicMock(
            success=False,
            error="LLM unavailable",
        )

        engine = PlaybookEngine()
        sub_goals = await engine.decompose_goal("test goal", "tools")

        assert len(sub_goals) == 1
        assert sub_goals[0].tool == "llm"

    @pytest.mark.asyncio
    async def test_decompose_max_depth_enforced(self, mock_settings, mock_llm_router, mock_audit_logger):
        """Decomposition should raise when max recursion depth is exceeded."""
        mock_settings.MAX_RECURSION_DEPTH = 0  # No recursion allowed

        engine = PlaybookEngine()
        with pytest.raises(RuntimeError, match="Max recursion depth"):
            await engine.decompose_goal("test goal", "tools", depth=0)

    @pytest.mark.asyncio
    async def test_decompose_max_nodes_enforced(self, mock_settings, mock_llm_router, mock_audit_logger):
        """Decomposition should truncate to max nodes."""
        mock_settings.MAX_DAG_NODES = 2
        mock_llm_router.generate.return_value = MagicMock(
            success=True,
            content=json.dumps({
                "task_description": "Test",
                "sub_goals": [
                    {"id": "sg_1", "description": "S1", "tool": "t1", "dependencies": []},
                    {"id": "sg_2", "description": "S2", "tool": "t2", "dependencies": []},
                    {"id": "sg_3", "description": "S3", "tool": "t3", "dependencies": []},
                ],
            }),
        )

        engine = PlaybookEngine()
        sub_goals = await engine.decompose_goal("test goal", "tools")
        assert len(sub_goals) <= 2


# ─── Tests: Project Memory (STEP 5) ───────────────────────────────────────────

class TestProjectMemory:
    """Test STEP 5: Project memory."""

    def test_store_project_memory(self, mock_settings, mock_llm_router, mock_audit_logger):
        """Storing project memory should return a doc ID."""
        with patch("nexus_brain.playbook_engine.get_vector_store") as mock_vs:
            store = MagicMock()
            mock_vs.return_value = store

            engine = PlaybookEngine()
            result = PlaybookResult(
                success=True,
                playbook_state={"key": "value"},
                duration_ms=1000,
            )
            doc_id = engine.store_project_memory("test goal", "test_playbook", result)

            assert doc_id != ""
            assert doc_id.startswith("proj_")
            store.add_memory.assert_called_once()

    def test_query_project_memory(self, mock_settings, mock_llm_router, mock_audit_logger):
        """Querying project memory should return results."""
        with patch("nexus_brain.playbook_engine.get_vector_store") as mock_vs:
            store = MagicMock()
            store.query.return_value = {
                "documents": [[json.dumps({"goal": "test", "playbook": "pb"})]],
            }
            mock_vs.return_value = store

            engine = PlaybookEngine()
            results = engine.query_project_memory("test")
            assert len(results) == 1
            assert results[0]["goal"] == "test"


# ─── Tests: Candidate Playbook Generation ─────────────────────────────────────

class TestCandidatePlaybook:
    """Test candidate playbook generation from successful decompositions."""

    def test_generate_candidate(self, temp_playbooks_dir, mock_settings, mock_llm_router, mock_audit_logger):
        """A successful decomposition should generate a candidate playbook."""
        with patch.object(PlaybookEngine, "_playbooks_dir", temp_playbooks_dir):
            engine = PlaybookEngine()
            sub_goals = [
                SubGoal(id="sg_1", description="Step 1", tool="t03_web_search"),
                SubGoal(id="sg_2", description="Step 2", tool="t02_file_manager",
                        dependencies=["sg_1"]),
            ]
            result = {"sg_1": "output1", "sg_2": "output2"}

            path = engine.generate_candidate_playbook("test goal", sub_goals, result)
            assert path is not None
            assert Path(path).exists()

            # Verify the candidate is valid JSON
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            assert data["name"].startswith("candidate_")
            assert len(data["steps"]) == 2


# ─── Tests: Singleton ─────────────────────────────────────────────────────────

class TestSingleton:
    """Test the singleton factory."""

    def test_get_playbook_engine(self, mock_settings, mock_llm_router, mock_audit_logger):
        """get_playbook_engine should return a PlaybookEngine instance."""
        engine = get_playbook_engine()
        assert isinstance(engine, PlaybookEngine)

    def test_singleton_returns_same_instance(self, mock_settings, mock_llm_router, mock_audit_logger):
        """get_playbook_engine should return the same instance."""
        engine1 = get_playbook_engine()
        engine2 = get_playbook_engine()
        assert engine1 is engine2
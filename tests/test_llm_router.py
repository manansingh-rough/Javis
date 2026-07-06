"""
NEXUS AI v4.0 — Fallback + circuit breaker tests for LLMRouter.
Hardware: Intel i3 7th Gen · 12GB RAM · Ollama + Groq API

Covers:
1. Router singleton and initialization
2. Provider order based on API keys
3. Circuit breaker — closed state
4. Circuit breaker — tripping on failures
5. Circuit breaker — half-open recovery
6. Rate limiting — token bucket
7. Token bucket refill behavior
8. Token bucket timeout
9. LLMResponse dataclass creation
10. CircuitBreaker dataclass creation
"""

import pytest
import asyncio
import time
from unittest.mock import MagicMock, AsyncMock, patch


class TestRouterInit:
    """Tests for LLMRouter initialization."""

    def test_get_llm_router_singleton(self):
        """Test that get_llm_router returns a singleton."""
        from nexus_brain.llm_router import get_llm_router
        r1 = get_llm_router()
        r2 = get_llm_router()
        assert r1 is r2

    def test_router_initializes_with_defaults(self, mock_settings):
        """Test that router initializes with default components."""
        from nexus_brain.llm_router import get_llm_router
        router = get_llm_router()
        assert router._settings is not None
        assert router._audit_logger is not None
        assert len(router._circuit_breakers) == 3
        assert "groq" in router._circuit_breakers
        assert "openai" in router._circuit_breakers
        assert "ollama" in router._circuit_breakers

    def test_router_rate_limiters_initialized(self, mock_settings):
        """Test that rate limiters are initialized."""
        from nexus_brain.llm_router import get_llm_router
        router = get_llm_router()
        assert "groq" in router._rate_limiters
        assert "openai" in router._rate_limiters
        assert "ollama" in router._rate_limiters

    def test_router_cost_tracking(self, mock_settings):
        """Test that cost tracking values are set."""
        from nexus_brain.llm_router import get_llm_router
        router = get_llm_router()
        assert router._cost_per_1k_input["ollama"] == 0.0
        assert router._cost_per_1k_input["groq"] > 0.0


class TestProviderOrder:
    """Tests for provider selection order."""

    def test_provider_order_full(self, mock_settings):
        """Test groq → openai → ollama when both keys present."""
        from nexus_brain.llm_router import get_llm_router
        router = get_llm_router()
        order = router._get_provider_order()
        assert "groq" in order
        assert "openai" in order
        assert "ollama" in order
        assert order.index("groq") < order.index("openai") < order.index("ollama")

    def test_provider_order_openai_only(self, monkeypatch):
        """Test openai → ollama when only openai key present."""
        from nexus_brain.llm_router import get_llm_router
        get_llm_router.cache_clear()
        monkeypatch.setattr("nexus_brain.llm_router.get_settings", lambda: MagicMock(
            GROQ_API_KEY=None,
            OPENAI_API_KEY="sk-test",
        ))
        router = get_llm_router()
        order = router._get_provider_order()
        assert "groq" not in order
        assert "openai" in order
        assert "ollama" in order
        get_llm_router.cache_clear()


class TestCircuitBreaker:
    """Tests for circuit breaker functionality."""

    @pytest.mark.asyncio
    async def test_circuit_breaker_closed(self, mock_settings):
        """Test that closed circuit allows requests."""
        from nexus_brain.llm_router import get_llm_router
        router = get_llm_router()
        is_open = await router._is_circuit_open("groq")
        assert is_open is False

    @pytest.mark.asyncio
    async def test_circuit_breaker_trips_after_failures(self, mock_settings):
        """Test that circuit breaker trips after CIRCUIT_BREAKER_FAILURES."""
        from nexus_brain.llm_router import get_llm_router
        router = get_llm_router()

        # Simulate failures
        for _ in range(mock_settings.CIRCUIT_BREAKER_FAILURES):
            await router._record_failure("groq")

        is_open = await router._is_circuit_open("groq")
        assert is_open is True

    @pytest.mark.asyncio
    async def test_circuit_breaker_half_open(self, mock_settings):
        """Test that circuit enters half-open after reset time."""
        from nexus_brain.llm_router import get_llm_router
        router = get_llm_router()

        # Trip the breaker
        for _ in range(mock_settings.CIRCUIT_BREAKER_FAILURES):
            await router._record_failure("test_provider")

        # Manually set a past open_time to simulate timeout
        cb = router._circuit_breakers["test_provider"] = router._circuit_breakers.get(
            "test_provider",
            type(router._circuit_breakers["groq"])(provider="test_provider"),
        )
        cb.state = type(cb.state)("open")
        cb.open_time = time.monotonic() - mock_settings.CIRCUIT_BREAKER_RESET_SECONDS - 1

        is_open = await router._is_circuit_open("test_provider")
        assert is_open is False  # Should transition to half-open

    @pytest.mark.asyncio
    async def test_circuit_breaker_records_success(self, mock_settings):
        """Test that success resets the circuit breaker."""
        from nexus_brain.llm_router import get_llm_router
        router = get_llm_router()

        cb = router._circuit_breakers["groq"]
        cb.state = type(cb.state)("half_open")
        cb.failure_count = 3

        await router._record_success("groq")
        assert cb.state.value == "closed"
        assert cb.failure_count == 0

    @pytest.mark.asyncio
    async def test_circuit_breaker_unknown_provider(self, mock_settings):
        """Test that unknown providers are treated as open."""
        from nexus_brain.llm_router import get_llm_router
        router = get_llm_router()

        is_open = await router._is_circuit_open("nonexistent")
        assert is_open is True


class TestTokenBucket:
    """Tests for TokenBucket rate limiter."""

    @pytest.mark.asyncio
    async def test_token_bucket_acquire(self):
        """Test basic token acquisition."""
        from nexus_brain.llm_router import TokenBucket
        bucket = TokenBucket(rate=100, capacity=10)
        result = await bucket.acquire(tokens=1, timeout=1)
        assert result is True

    @pytest.mark.asyncio
    async def test_token_bucket_exhaust(self):
        """Test that exhausted bucket returns False."""
        from nexus_brain.llm_router import TokenBucket
        bucket = TokenBucket(rate=0.01, capacity=3)  # Very slow refill
        for _ in range(3):
            await bucket.acquire(tokens=1, timeout=0.1)
        
        result = await bucket.acquire(tokens=1, timeout=0.1)
        assert result is False

    @pytest.mark.asyncio
    async def test_token_bucket_refill(self):
        """Test that tokens refill over time."""
        from nexus_brain.llm_router import TokenBucket
        bucket = TokenBucket(rate=100, capacity=10)
        
        # Consume all tokens
        for _ in range(10):
            await bucket.acquire(tokens=1, timeout=1)
        
        # Wait for refill
        await asyncio.sleep(0.05)
        
        # Should have some tokens now
        result = await bucket.acquire(tokens=1, timeout=2)
        assert result is True

    def test_token_bucket_initial_state(self):
        """Test that bucket initializes with full capacity."""
        from nexus_brain.llm_router import TokenBucket
        bucket = TokenBucket(rate=10, capacity=5)
        assert bucket._tokens == 5.0


class TestLLMResponse:
    """Tests for LLMResponse dataclass."""

    def test_llm_response_defaults(self):
        """Test that LLMResponse has correct defaults."""
        from nexus_brain.llm_router import LLMResponse
        resp = LLMResponse(content="Hello", provider="groq", model="llama-3.3-70b")
        assert resp.content == "Hello"
        assert resp.provider == "groq"
        assert resp.success is True
        assert resp.error is None
        assert resp.duration_ms == 0.0
        assert resp.cost_usd == 0.0

    def test_llm_response_error(self):
        """Test LLMResponse with error."""
        from nexus_brain.llm_router import LLMResponse
        resp = LLMResponse(
            content="",
            provider="groq",
            model="none",
            success=False,
            error="Rate limited",
        )
        assert resp.success is False
        assert resp.error == "Rate limited"


class TestCircuitBreakerDataclass:
    """Tests for CircuitBreaker dataclass."""

    def test_circuit_breaker_defaults(self):
        """Test that CircuitBreaker has correct defaults."""
        from nexus_brain.llm_router import CircuitBreaker, CircuitState
        cb = CircuitBreaker(provider="groq")
        assert cb.provider == "groq"
        assert cb.failure_count == 0
        assert cb.state == CircuitState.CLOSED
        assert cb.last_failure_time == 0.0
"""
NEXUS AI v4.0 — Token bucket rate limiter for LLM and tool calls.
Hardware: Intel i3 7th Gen · 12GB RAM · Ollama + Groq API

Provides thread-safe rate limiting using the token bucket algorithm.
Supports per-provider rate limits and adaptive throttling.
"""

import time
import threading
from typing import Dict, Optional, Callable, Any


class RateLimiter:
    """
    Token bucket rate limiter with burst support.
    
    Thread-safe. Multiple threads can call acquire() concurrently.
    
    The bucket starts full (initial_tokens = rate) and refills at
    rate/per tokens per second. acquire(1) consumes one token.
    
    Args:
        rate: Maximum number of operations allowed in the time window.
        per: Time window in seconds.
        burst: Maximum burst size (default: same as rate).
    
    Example:
        limiter = RateLimiter(rate=30, per=60)  # 30 requests per minute
        if limiter.acquire():
            make_api_call()
        else:
            wait_and_retry()
    """
    
    def __init__(
        self,
        rate: float = 30,
        per: float = 60,
        burst: Optional[float] = None,
    ):
        self.rate = rate
        self.per = per
        self.burst = burst if burst is not None else rate
        self._tokens = float(rate)
        self._last_refill = time.monotonic()
        self._lock = threading.Lock()
        self._total_acquired = 0
        self._total_rejected = 0
    
    def acquire(self, tokens: float = 1.0) -> bool:
        """
        Try to acquire tokens from the bucket.
        
        Args:
            tokens: Number of tokens to consume (default: 1).
        
        Returns:
            True if tokens were acquired, False if bucket is empty.
        """
        with self._lock:
            self._refill()
            if self._tokens >= tokens:
                self._tokens -= tokens
                self._total_acquired += 1
                return True
            self._total_rejected += 1
            return False
    
    def wait(self, tokens: float = 1.0, timeout: Optional[float] = None) -> bool:
        """
        Block until tokens are available or timeout expires.
        
        Args:
            tokens: Number of tokens to acquire.
            timeout: Maximum time to wait in seconds (None = wait forever).
        
        Returns:
            True if tokens were acquired, False on timeout.
        """
        start = time.monotonic()
        while not self.acquire(tokens):
            if timeout is not None and (time.monotonic() - start) >= timeout:
                return False
            time.sleep(max(0.01, self.per / self.rate / 4))
        return True
    
    def _refill(self) -> None:
        """Refill tokens based on elapsed time."""
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._last_refill = now
        refill = elapsed * (self.rate / self.per)
        self._tokens = min(self.burst, self._tokens + refill)
    
    @property
    def available_tokens(self) -> float:
        """Get current number of available tokens."""
        with self._lock:
            self._refill()
            return self._tokens
    
    @property
    def stats(self) -> Dict[str, Any]:
        """Get rate limiter statistics."""
        with self._lock:
            return {
                "rate": self.rate,
                "per": self.per,
                "burst": self.burst,
                "available_tokens": self._tokens,
                "total_acquired": self._total_acquired,
                "total_rejected": self._total_rejected,
            }
    
    def reset(self) -> None:
        """Reset the bucket to full and clear statistics."""
        with self._lock:
            self._tokens = float(self.burst)
            self._last_refill = time.monotonic()
            self._total_acquired = 0
            self._total_rejected = 0


# ─── Global rate limiters ───────────────────────────────────────────────────

_llm_rate_limiter: Optional[RateLimiter] = None
_llm_rate_limiter_lock = threading.Lock()


def get_llm_rate_limiter() -> RateLimiter:
    """
    Get or create the global LLM rate limiter.
    
    Rate limits are loaded from settings (GROQ_REQUESTS_PER_MINUTE).
    Default: 30 requests per minute (Groq free tier).
    """
    global _llm_rate_limiter
    if _llm_rate_limiter is None:
        with _llm_rate_limiter_lock:
            if _llm_rate_limiter is None:
                from nexus_config.settings import get_settings
                settings = get_settings()
                _llm_rate_limiter = RateLimiter(
                    rate=settings.GROQ_REQUESTS_PER_MINUTE,
                    per=60,
                )
    return _llm_rate_limiter


# ─── Retry decorator ───────────────────────────────────────────────────────

def with_rate_limit(
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
) -> Callable[..., Any]:
    """
    Decorator that applies rate limiting and retry logic to a function.
    
    Args:
        max_retries: Maximum number of retry attempts.
        base_delay: Initial delay between retries (exponential backoff).
        max_delay: Maximum delay between retries.
    
    Returns:
        Decorated function with rate limiting and retry.
    
    Example:
        @with_rate_limit(max_retries=3)
        def call_api():
            ...
    """
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        import functools
        
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            limiter = get_llm_rate_limiter()
            last_error = None
            
            for attempt in range(max_retries):
                if limiter.wait(tokens=1, timeout=10):
                    try:
                        return func(*args, **kwargs)
                    except Exception as e:
                        last_error = e
                        delay = min(base_delay * (2 ** attempt), max_delay)
                        time.sleep(delay)
                else:
                    delay = min(base_delay * (2 ** attempt), max_delay)
                    time.sleep(delay)
            
            raise last_error or RuntimeError("Rate limit retry exhausted")
        
        return wrapper
    return decorator
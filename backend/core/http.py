"""
GeoAtlas — Resilient Network Infrastructure
============================================
Global HTTP client, adaptive rate limiters, windowed circuit breakers,
EMA-based provider health scoring, and per-provider concurrency caps.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from collections import deque, OrderedDict
from enum import Enum
from typing import Any, Callable, Dict, Optional

import httpx

logger = logging.getLogger(__name__)

# ─── GLOBAL HTTP CLIENT ──────────────────────────────────────────────────────

GLOBAL_TIMEOUT = httpx.Timeout(
    connect=2.0,
    read=5.0,
    write=5.0,
    pool=2.0,
)

# Gracefully degrade to HTTP/1.1 if h2 is not installed
try:
    global_http_client: httpx.AsyncClient = httpx.AsyncClient(
        http2=True,
        timeout=GLOBAL_TIMEOUT,
        limits=httpx.Limits(
            max_connections=100,
            max_keepalive_connections=20,
        ),
    )
except ImportError:
    logger.warning("h2 not installed — falling back to HTTP/1.1. Run: pip install httpx[http2]")
    global_http_client = httpx.AsyncClient(
        timeout=GLOBAL_TIMEOUT,
        limits=httpx.Limits(
            max_connections=100,
            max_keepalive_connections=20,
        ),
    )


async def close_global_client() -> None:
    """Flush and close the global client (call during app shutdown)."""
    await global_http_client.aclose()


# ─── LRU CACHE ───────────────────────────────────────────────────────────────

class LRUCache:
    """Simple size + TTL bounded LRU cache for in-memory data."""

    def __init__(self, max_size: int = 1000, ttl_seconds: float = 300.0):
        self._max_size = max_size
        self._ttl = ttl_seconds
        self._store: OrderedDict[str, tuple[float, Any]] = OrderedDict()

    def get(self, key: str) -> Optional[Any]:
        if key not in self._store:
            return None
        ts, value = self._store[key]
        if time.time() - ts > self._ttl:
            del self._store[key]
            return None
        self._store.move_to_end(key)
        return value

    def set(self, key: str, value: Any) -> None:
        self._store[key] = (time.time(), value)
        self._store.move_to_end(key)
        while len(self._store) > self._max_size:
            self._store.popitem(last=False)   # evict oldest

    def __len__(self) -> int:
        return len(self._store)

    def clear(self) -> None:
        self._store.clear()


# ─── ADAPTIVE RATE LIMITER ───────────────────────────────────────────────────

class AdaptiveLimiter:
    """
    Smoothed rate limiter with jitter.
    • Requires *3 consecutive* successes before it speeds up.
    • Backs off immediately with jitter on a 429.
    """

    def __init__(self, initial_delay: float = 0.05):
        self.delay: float = initial_delay
        self.success_streak: int = 0

    async def wait(self) -> None:
        if self.delay > 0:
            await asyncio.sleep(self.delay)

    def success(self) -> None:
        self.success_streak += 1
        if self.success_streak >= 3:
            self.delay = max(0.01, self.delay * 0.9)
            self.success_streak = 0

    def rate_limited(self) -> None:
        self.success_streak = 0
        self.delay = min(2.0, self.delay * 1.5 + random.uniform(0, 0.2))


# ─── CIRCUIT BREAKER ─────────────────────────────────────────────────────────

class CircuitState(Enum):
    CLOSED = 0
    OPEN = 1
    HALF_OPEN = 2


class CircuitBreaker:
    """
    Time-windowed circuit breaker with:
    • Rolling failure window (deque).
    • Minimum OPEN duration to prevent flapping.
    • Jittered HALF_OPEN probe delay.
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        window_seconds: float = 10.0,
        min_open_seconds: float = 30.0,
    ):
        self.failure_threshold = failure_threshold
        self.window_seconds = window_seconds
        self.min_open_seconds = min_open_seconds

        self.state: CircuitState = CircuitState.CLOSED
        self._failures: deque[float] = deque()
        self._opened_at: float = 0.0
        self._half_open_jitter: float = 0.0

    # ── public API ──

    def allow_request(self) -> bool:
        """Returns True if a request is allowed right now."""
        if self.state == CircuitState.CLOSED:
            return True

        if self.state == CircuitState.OPEN:
            elapsed = time.time() - self._opened_at
            if elapsed >= self.min_open_seconds + self._half_open_jitter:
                self.state = CircuitState.HALF_OPEN
                logger.info("Circuit breaker → HALF_OPEN")
                return True
            return False

        # HALF_OPEN — allow exactly one probe
        return True

    def record_success(self) -> None:
        if self.state == CircuitState.HALF_OPEN:
            self.state = CircuitState.CLOSED
            self._failures.clear()
            logger.info("Circuit breaker → CLOSED (recovered)")

    def record_failure(self) -> None:
        now = time.time()
        self._failures.append(now)
        self._prune()

        if self.state == CircuitState.HALF_OPEN:
            self._open(now)
        elif self.state == CircuitState.CLOSED and len(self._failures) >= self.failure_threshold:
            self._open(now)

    # ── internals ──

    def _prune(self) -> None:
        cutoff = time.time() - self.window_seconds
        while self._failures and self._failures[0] < cutoff:
            self._failures.popleft()

    def _open(self, now: float) -> None:
        self.state = CircuitState.OPEN
        self._opened_at = now
        self._half_open_jitter = random.uniform(0, 5)
        logger.warning(
            "Circuit breaker → OPEN for %.1fs (+%.2fs jitter)",
            self.min_open_seconds,
            self._half_open_jitter,
        )


# ─── PROVIDER HEALTH (EMA) ──────────────────────────────────────────────────

class ProviderHealth:
    """
    Exponential Moving Average based health scoring.
    • Composite = 50 % success-EMA + 30 % latency + 20 % raw success rate.
    • Clamped to [0.05, 1.0] so no provider is permanently starved.
    """

    def __init__(self, decay: float = 0.8):
        self.decay = decay
        self.score: float = 1.0
        self.latency_ema: float = 200.0   # ms
        self.success_count: int = 0
        self.total_count: int = 0

    def update(self, success: bool, latency_ms: float) -> None:
        new = 1.0 if success else 0.0
        self.score = (self.score * self.decay) + (new * (1 - self.decay))
        self.latency_ema = (self.latency_ema * self.decay) + (latency_ms * (1 - self.decay))
        self.score = max(0.05, min(1.0, self.score))
        self.total_count += 1
        if success:
            self.success_count += 1

    def get_composite_score(self) -> float:
        raw_rate = self.success_count / max(self.total_count, 1)
        # 1.0 at ≤ 200 ms → 0.0 at ≥ 2000 ms
        lat = max(0.0, min(1.0, (2000 - self.latency_ema) / 1800))
        composite = 0.5 * self.score + 0.3 * lat + 0.2 * raw_rate
        return max(0.05, min(1.0, composite))


# ─── PROVIDER CONTEXT ────────────────────────────────────────────────────────

class ProviderContext:
    """
    Wraps all resilience primitives for a single upstream provider:
    Semaphore → AdaptiveLimiter → CircuitBreaker → Health tracking.
    """

    def __init__(self, name: str, concurrency: int = 8):
        self.name = name
        self.limiter = AdaptiveLimiter()
        self.breaker = CircuitBreaker()
        self.health = ProviderHealth()
        self.semaphore = asyncio.Semaphore(concurrency)

    async def execute(self, func: Callable, *args: Any, **kwargs: Any) -> Any:
        """
        Run *func* with full resilience wrapping.
        Returns None if the circuit is open.
        """
        if not self.breaker.allow_request():
            return None

        async with self.semaphore:
            await self.limiter.wait()
            t0 = time.perf_counter()
            try:
                result = await func(*args, **kwargs)
                latency = (time.perf_counter() - t0) * 1000

                if hasattr(result, "status_code"):
                    if result.status_code == 429:
                        self.limiter.rate_limited()
                        self.breaker.record_failure()
                        self.health.update(False, latency)
                        return result
                    if result.status_code >= 400:
                        self.breaker.record_failure()
                        self.health.update(False, latency)
                    else:
                        self.limiter.success()
                        self.breaker.record_success()
                        self.health.update(True, latency)
                else:
                    self.limiter.success()
                    self.breaker.record_success()
                    self.health.update(True, latency)

                return result
            except Exception as exc:
                latency = (time.perf_counter() - t0) * 1000
                self.breaker.record_failure()
                self.health.update(False, latency)
                logger.debug("Provider %s error: %s", self.name, exc)
                raise


# ─── PROVIDER REGISTRY ───────────────────────────────────────────────────────

PROVIDERS: Dict[str, ProviderContext] = {
    "polygon":      ProviderContext("polygon",      concurrency=10),
    "finnhub":      ProviderContext("finnhub",      concurrency=10),
    "twelvedata":   ProviderContext("twelvedata",   concurrency=5),
    "binance":      ProviderContext("binance",      concurrency=15),
    "fcs":          ProviderContext("fcs",          concurrency=5),
    "eodhd":        ProviderContext("eodhd",        concurrency=10),
    "alphavantage": ProviderContext("alphavantage", concurrency=2),
}


# ─── REQUEST COALESCER ───────────────────────────────────────────────────────

class RequestCoalescer:
    """
    De-duplicates concurrent identical requests.
    • Per-key timeout prevents indefinite waits.
    • `finally` cleanup prevents stuck keys.
    • Exception isolation: failure in the source task returns fallback, not crash.
    """

    def __init__(self, timeout: float = 5.0):
        self._in_flight: dict[str, asyncio.Task] = {}
        self._timeout = timeout

    async def get_or_fetch(
        self,
        key: str,
        fetch_coro,
        fallback: Any = None,
    ) -> Any:
        if key in self._in_flight:
            try:
                return await asyncio.wait_for(
                    asyncio.shield(self._in_flight[key]),
                    timeout=self._timeout,
                )
            except Exception:
                return fallback

        task = asyncio.create_task(fetch_coro)
        self._in_flight[key] = task
        try:
            return await asyncio.wait_for(task, timeout=self._timeout)
        except Exception:
            return fallback
        finally:
            self._in_flight.pop(key, None)


# ─── DB WRITE BUFFER ─────────────────────────────────────────────────────────

class DBBuffer:
    """
    Batch-insert buffer with hybrid flushing:
    • Time-based  — flush every `interval` seconds.
    • Size-based  — flush when `batch_size` records are queued.
    • Backpressure — drop oldest if queue exceeds `max_queue`.
    • Shutdown-safe — explicit `drain()` flushes remaining records.
    """

    def __init__(
        self,
        flush_fn: Callable,
        interval: float = 1.0,
        batch_size: int = 50,
        max_queue: int = 5000,
    ):
        self._flush_fn = flush_fn
        self._interval = interval
        self._batch_size = batch_size
        self._max_queue = max_queue
        self._queue: list[dict] = []
        self._lock = asyncio.Lock()
        self._running = False
        self._task: Optional[asyncio.Task] = None

    async def add(self, record: dict) -> None:
        batch = None
        async with self._lock:
            self._queue.append(record)
            if len(self._queue) > self._max_queue:
                dropped = len(self._queue) - self._max_queue
                self._queue = self._queue[dropped:]
                logger.warning("DBBuffer: dropped %d oldest records (backpressure)", dropped)
            if len(self._queue) >= self._batch_size:
                batch = list(self._queue)
                self._queue.clear()
        # Flush outside the lock if threshold was hit
        if batch:
            await self._do_flush(batch)

    def start(self) -> None:
        if not self._running:
            self._running = True
            self._task = asyncio.create_task(self._flush_loop(), name="db-buffer-flush")

    async def drain(self) -> None:
        """Flush any remaining records and stop the background loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        async with self._lock:
            if self._queue:
                batch = list(self._queue)
                self._queue.clear()
                await self._do_flush(batch)

    async def _flush_loop(self) -> None:
        while self._running:
            await asyncio.sleep(self._interval)
            async with self._lock:
                if not self._queue:
                    continue
                batch = list(self._queue)
                self._queue.clear()
            await self._do_flush(batch)

    async def _do_flush(self, batch: list[dict]) -> None:
        try:
            await self._flush_fn(batch)
        except Exception as exc:
            logger.error("DBBuffer flush error (%d records): %s", len(batch), exc)

    @property
    def size(self) -> int:
        return len(self._queue)

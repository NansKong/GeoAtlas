import asyncio
import time
import random

class AsyncTokenBucket:
    """
    Asynchronous implementation of the Token Bucket algorithm for controlling concurrent network calls.
    Ensures safe parallel execution across exact rate limits with AIMD (Smart Concurrency).
    """
    def __init__(self, capacity: int, refill_rate: float, max_refill_rate: float = None):
        """
        :param capacity: The max burst size of tokens
        :param refill_rate: Initial tokens per second
        :param max_refill_rate: Maximum ceiling for dynamic tuning
        """
        self.capacity = float(capacity)
        self.tokens = float(capacity)
        self.base_refill_rate = float(refill_rate)
        self.refill_rate = float(refill_rate)
        # Cap max throughput at 10x base or the provided value
        self.max_refill_rate = float(max_refill_rate) if max_refill_rate else self.base_refill_rate * 10.0
        self.last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    def penalize_rate(self):
        """Multiplicative Decrease on 429"""
        self.refill_rate = max(self.base_refill_rate * 0.1, self.refill_rate * 0.5)

    def reward_rate(self):
        """Additive Increase on Success"""
        # Increase refill rate by +1 token/sec, capped at maximum
        self.refill_rate = min(self.max_refill_rate, self.refill_rate + 1.0)

    async def consume(self, tokens: int = 1):
        """
        Wait until `tokens` are available in the bucket, then consume them to execute a network request.
        """
        while True:
            async with self._lock:
                now = time.monotonic()
                time_passed = now - self.last_refill
                
                # Refill dynamically
                added = time_passed * self.refill_rate
                if added > 0:
                    self.tokens = min(self.capacity, self.tokens + added)
                    self.last_refill = now
                
                if self.tokens >= tokens:
                    self.tokens -= tokens
                    return # Acquired lock permission directly
                else:
                    # Not enough tokens. Calculate minimum wait time
                    wait_time = (tokens - self.tokens) / self.refill_rate
            
            # Unlock and sleep outside the lock so other tasks can attempt
            # await asyncio.sleep(max(wait_time, 0.1))

            await asyncio.sleep(max(wait_time, 0.1) + random.uniform(0.05, 0.3))

# Initialize specific limiters for our pipelines
# Polygon: 5 requests per 60 seconds -> 5 max burst, 5/60 tokens per second
# polygon_limiter = AsyncTokenBucket(capacity=5, refill_rate=(5.0 / 60.0))
polygon_limiter = AsyncTokenBucket(
    capacity=1,          # ❗ NO BURST
    refill_rate=5.0 / 60.0
)   

# TwelveData: 8 credits per 60 seconds -> 8 max burst, 8/60 tokens per second
twelvedata_limiter = AsyncTokenBucket(capacity=8, refill_rate=(8.0 / 60.0))

# Binance: 1200 request weight per minute. We limit to ~5 per second reliably for historical data
binance_limiter = AsyncTokenBucket(capacity=10, refill_rate=5.0)

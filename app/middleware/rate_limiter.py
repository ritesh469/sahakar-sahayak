import threading
import time
from collections import defaultdict, deque

from upstash_redis import Redis

from app.config import settings

_redis_client: Redis | None = None

# In-memory fallback (single process) used when Upstash is not configured
_memory_windows: dict[str, deque[float]] = defaultdict(deque)
_memory_lock = threading.Lock()


def get_redis_client() -> Redis | None:
    global _redis_client
    if not settings.upstash_redis_url or not settings.upstash_redis_token:
        return None
    if _redis_client is None:
        _redis_client = Redis(
            url=settings.upstash_redis_url,
            token=settings.upstash_redis_token,
        )
    return _redis_client



class RateLimiter:
    def __init__(self, max_requests: int, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds

    def is_allowed(self, key: str) -> tuple[bool, int, int]:
        client = get_redis_client()
        now = time.time()
        window_start = now - self.window_seconds

        if client is None:
            request_count = self._count_in_memory(key, now, window_start)
        else:
            pipe = client.pipeline()
            pipe.zremrangebyscore(key, 0, window_start)
            pipe.zadd(key, {str(now): now})
            pipe.zcard(key)
            pipe.expire(key, self.window_seconds)
            results = pipe.exec()
            request_count: int = results[2]  # type: ignore[assignment,no-redef]

        remaining = max(0, self.max_requests - request_count)
        allowed = request_count <= self.max_requests

        return allowed, remaining, request_count

    @staticmethod
    def _count_in_memory(key: str, now: float, window_start: float) -> int:
        """Same sliding-window semantics as the Redis sorted-set version."""
        with _memory_lock:
            window = _memory_windows[key]
            while window and window[0] <= window_start:
                window.popleft()
            window.append(now)
            return len(window)


def is_allowed_ip(ip: str, route: str, limit: int, window_seconds: int) -> tuple[bool, int, int]:
    limiter = RateLimiter(max_requests=limit, window_seconds=window_seconds)
    key = f"rate_limit:ip:{ip}:{route}"
    return limiter.is_allowed(key)


def is_allowed_user(
    user_id: str, limit: int = 20, window_seconds: int = 60
) -> tuple[bool, int, int]:
    limiter = RateLimiter(max_requests=limit, window_seconds=window_seconds)
    key = f"rate_limit:user:{user_id}"
    return limiter.is_allowed(key)

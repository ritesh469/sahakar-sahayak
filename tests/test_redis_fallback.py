"""Rate limiter + token budget must work without Upstash (in-memory fallback)."""

import pytest

from app.config import settings
from app.middleware import rate_limiter
from app.security import token_budget


@pytest.fixture(autouse=True)
def no_upstash(monkeypatch):
    monkeypatch.setattr(settings, "upstash_redis_url", "")
    monkeypatch.setattr(settings, "upstash_redis_token", "")
    rate_limiter._memory_windows.clear()
    token_budget._memory_used.clear()


def test_rate_limiter_blocks_after_limit():
    results = [rate_limiter.is_allowed_ip("1.2.3.4", "/auth/login", limit=3, window_seconds=60)
               for _ in range(4)]
    assert [allowed for allowed, _, _ in results] == [True, True, True, False]
    assert results[-1][2] == 4  # request_count


def test_rate_limiter_keys_are_independent():
    for _ in range(3):
        rate_limiter.is_allowed_user("alice", limit=3, window_seconds=60)
    allowed, _, _ = rate_limiter.is_allowed_user("bob", limit=3, window_seconds=60)
    assert allowed


def test_rate_limiter_window_expires(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(rate_limiter.time, "time", lambda: clock[0])
    for _ in range(2):
        rate_limiter.is_allowed_user("carol", limit=2, window_seconds=60)
    assert not rate_limiter.is_allowed_user("carol", limit=2, window_seconds=60)[0]
    clock[0] += 61
    assert rate_limiter.is_allowed_user("carol", limit=2, window_seconds=60)[0]


def test_token_budget_check_and_consume():
    budget = token_budget.TokenBudget(max_tokens=100)
    assert budget.check_budget("dave", 60) == (True, 100)
    out = budget.consume("dave", 60)
    assert out["used"] == 60 and out["remaining"] == 40
    assert budget.check_budget("dave", 60) == (False, 40)

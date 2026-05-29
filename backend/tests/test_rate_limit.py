import pytest

pytest.importorskip("starlette")

from services.rate_limit import InMemoryRateLimiter, LimitRule, parse_csv_paths


def test_limiter_blocks_after_limit():
    limiter = InMemoryRateLimiter()
    rule = LimitRule(requests=2, window_seconds=60)

    allowed, remaining, _ = limiter.check("127.0.0.1:/auth/login", rule)
    assert allowed is True
    assert remaining == 1

    allowed, remaining, _ = limiter.check("127.0.0.1:/auth/login", rule)
    assert allowed is True
    assert remaining == 0

    allowed, remaining, reset = limiter.check("127.0.0.1:/auth/login", rule)
    assert allowed is False
    assert remaining == 0
    assert reset >= 1


def test_parse_csv_paths_normalizes_entries():
    paths = parse_csv_paths("/auth/login, docs ,openapi.json")
    assert paths == ["/auth/login", "/docs", "/openapi.json"]

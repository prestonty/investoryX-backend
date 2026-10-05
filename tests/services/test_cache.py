from __future__ import annotations

import pytest

import src.services.cache as cache


class _FakeRedis:
    """Just enough of redis-py for the cache: values plus the TTL each was set with."""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.ttls: dict[str, int] = {}

    def get(self, key):
        return self.values.get(key)

    def mget(self, keys):
        return [self.values.get(k) for k in keys]

    def setex(self, key, ttl, value):
        self.values[key], self.ttls[key] = value, ttl

    def incr(self, key):
        self.values[key] = str(int(self.values.get(key, 0)) + 1)

    def pipeline(self):
        redis = self

        class _Pipe:
            def __init__(self):
                self.ops = []

            def setex(self, *args):
                self.ops.append(args)

            def execute(self):
                for args in self.ops:
                    redis.setex(*args)

        return _Pipe()


@pytest.fixture
def redis(monkeypatch) -> _FakeRedis:
    fake = _FakeRedis()
    monkeypatch.setattr(cache, "get_redis", lambda: fake)
    monkeypatch.setattr(cache, "market_is_open", lambda: True)
    return fake


def test_hit_skips_upstream(redis) -> None:
    calls: list = []

    @cache.cached("t", 30, 1800, key=lambda x: str(x))
    def fn(x):
        calls.append(x)
        return {"value": x}

    assert fn(1) == {"value": 1}
    assert fn(1) == {"value": 1}
    assert calls == [1]

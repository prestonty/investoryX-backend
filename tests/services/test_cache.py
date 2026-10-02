from __future__ import annotations

from datetime import datetime

import pytest

import src.services.cache as cache
import src.services.stock_data as stock_data
from src.trading_engine.services.pricing import MARKET_TZ


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


def _counter():
    calls: list = []

    @cache.cached("t", 30, 1800, key=lambda x: str(x))
    def fn(x):
        calls.append(x)
        return {"value": x}

    return fn, calls


def test_hit_skips_upstream(redis) -> None:
    fn, calls = _counter()
    assert fn(1) == {"value": 1}
    assert fn(1) == {"value": 1}
    assert calls == [1]
    assert redis.values["stats:cache:hit:t"] == "1"


def test_ttl_depends_on_market_hours(redis, monkeypatch) -> None:
    fn, _ = _counter()
    fn(1)
    monkeypatch.setattr(cache, "market_is_open", lambda: False)
    fn(2)
    assert redis.ttls["cache:t:1"] == 30
    assert redis.ttls["cache:t:2"] == 1800
    assert redis.ttls["stale:t:1"] == cache.STALE_TTL_SECONDS


def test_upstream_failure_serves_stale_copy(redis) -> None:
    fn, _ = _counter()
    fn(1)
    del redis.values["cache:t:1"]  # fresh copy expired

    @cache.cached("t", 30, 1800, key=lambda x: str(x))
    def failing(x):
        raise RuntimeError("429 Too Many Requests")

    assert failing(1) == {"value": 1}


def test_upstream_failure_without_stale_copy_raises(redis) -> None:
    @cache.cached("t", 30, 1800, key=lambda x: str(x))
    def failing(x):
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        failing(1)


@pytest.mark.parametrize("value", [None, [], {}, {"PE Ratio": "N/A", "Beta": "N/A"}])
def test_empty_or_failed_results_are_not_cached(redis, value) -> None:
    @cache.cached("t", 30, 1800, key=lambda: "k")
    def fn():
        return value

    fn()
    assert "cache:t:k" not in redis.values


def test_works_without_redis(monkeypatch) -> None:
    monkeypatch.setattr(cache, "get_redis", lambda: None)
    fn, calls = _counter()
    assert fn(1) == fn(1) == {"value": 1}
    assert calls == [1, 1]


@pytest.mark.parametrize(
    ("when", "is_open"),
    [
        (datetime(2025, 11, 26, 9, 29), False),
        (datetime(2025, 11, 26, 9, 30), True),
        (datetime(2025, 11, 26, 15, 59), True),
        (datetime(2025, 11, 26, 16, 0), False),
        (datetime(2025, 11, 27, 12, 0), False),  # Thanksgiving
        (datetime(2025, 11, 29, 12, 0), False),  # Saturday
    ],
)
def test_market_is_open(when: datetime, is_open: bool) -> None:
    assert cache.market_is_open(when.replace(tzinfo=MARKET_TZ)) is is_open


# --- stock_data integration --------------------------------------------------

def test_quotes_only_fetch_tickers_not_in_cache(redis, monkeypatch) -> None:
    fetched: list[list[str]] = []

    def _fake_fetch(tickers):
        fetched.append(list(tickers))
        return {t: {"stockPrice": 100.0, "priceChange": 1.0, "priceChangePercent": 1.0} for t in tickers}

    monkeypatch.setattr(stock_data, "_fetchQuotes", _fake_fetch)

    stock_data.getQuotes(["SPY", "QQQ"])         # homepage
    result = stock_data.getQuotes(["SPY", "AAPL"])  # a watchlist sharing SPY

    assert fetched == [["SPY", "QQQ"], ["AAPL"]]
    assert set(result) == {"SPY", "AAPL"}


def test_quote_error_falls_back_to_stale_quote(redis, monkeypatch) -> None:
    good = {"stockPrice": 100.0, "priceChange": 1.0, "priceChangePercent": 1.0}
    monkeypatch.setattr(stock_data, "_fetchQuotes", lambda tickers: {t: good for t in tickers})
    stock_data.getQuotes(["SPY"])
    del redis.values["cache:quote:SPY"]
    monkeypatch.setattr(stock_data, "_fetchQuotes", lambda tickers: {t: {"error": "rate limited"} for t in tickers})

    assert stock_data.getQuotes(["SPY"]) == {"SPY": good}


def test_news_page_sizes_share_one_upstream_fetch(redis, monkeypatch) -> None:
    calls: list[int] = []
    articles = [{"headline": f"h{i}"} for i in range(50)]

    @cache.cached("news", 600, 600, key=lambda: "all-stocks")
    def _fake_fetch():
        calls.append(1)
        return articles

    monkeypatch.setattr(stock_data, "_fetchStockNews", _fake_fetch)

    assert len(stock_data.getStockNews(5)) == 5
    assert len(stock_data.getStockNews(20)) == 20
    assert calls == [1]

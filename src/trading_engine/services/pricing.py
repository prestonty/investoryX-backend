from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from functools import lru_cache
from typing import Protocol
from zoneinfo import ZoneInfo
import logging

import pandas as pd
import yfinance as yf
from pandas.tseries.holiday import (
    AbstractHolidayCalendar,
    GoodFriday,
    Holiday,
    USLaborDay,
    USMartinLutherKingJr,
    USMemorialDay,
    USPresidentsDay,
    USThanksgivingDay,
    nearest_workday,
    sunday_to_monday,
)
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from src.core.database import SessionLocal
from src.models.price_bar import PriceBar as PriceBarModel
from src.models.simulator_tracked_stock import SimulatorTrackedStock

logger = logging.getLogger("investoryx.trading_engine.pricing")


@dataclass(frozen=True)
class PriceBar:
    """Daily OHLCV price record for a single symbol."""
    symbol: str
    day: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    source: str


class PriceProvider(Protocol):
    """Source of price data (API, CSV, etc.)."""

    def fetch_daily_bars(
        self,
        symbols: list[str],
        day: date,
    ) -> list[PriceBar]:
        raise NotImplementedError


class PriceBarRepository(Protocol):
    """Persistence layer for price bars (DB)."""

    def upsert_bars(self, bars: list[PriceBar]) -> int:
        raise NotImplementedError

    def get_latest_bars(self, symbols: list[str], day: date) -> list[PriceBar]:
        raise NotImplementedError


class PricingService:
    """Orchestrates fetching and storing price bars."""

    def __init__(self, provider: PriceProvider, repo: PriceBarRepository) -> None:
        self._provider = provider
        self._repo = repo

    def fetch_and_store_daily_bars(self, symbols: list[str], day: date) -> int:
        bars = self._provider.fetch_daily_bars(symbols, day)
        return self._repo.upsert_bars(bars)

    def get_latest_bars(self, symbols: list[str], day: date) -> list[PriceBar]:
        return self._repo.get_latest_bars(symbols, day)


def get_all_enabled_simulator_tickers(simulator_id: int | None = None) -> list[str]:
    session = SessionLocal()
    try:
        stmt = select(SimulatorTrackedStock.ticker).where(
            SimulatorTrackedStock.enabled.is_(True)
        )
        if simulator_id is not None:
            stmt = stmt.where(SimulatorTrackedStock.simulator_id == simulator_id)
        rows = session.execute(stmt).scalars().all()
        tickers = {
            ticker.strip().upper()
            for ticker in rows
            if ticker and ticker.strip()
        }
        return sorted(tickers)
    finally:
        session.close()


class YahooPriceProvider(PriceProvider):
    """Yahoo Finance-backed daily bar provider (yfinance)."""

    def fetch_daily_bars(self, symbols: list[str], day: date) -> list[PriceBar]:
        if not symbols:
            return []

        symbols = _normalize_symbols(symbols)
        if not _is_trading_day(day):
            logger.info("Skipping non-trading day: %s", day.isoformat())
            return []

        start = day
        end = day + timedelta(days=1)
        try:
            data = yf.download(
                tickers=" ".join(symbols),
                start=start.isoformat(),
                end=end.isoformat(),
                interval="1d",
                group_by="ticker",
                auto_adjust=False,
                threads=True,
                progress=False,
            )
        except Exception as exc:
            logger.exception("yfinance download failed for %s: %s", symbols, exc)
            return []

        bars: list[PriceBar] = []

        if len(symbols) == 1:
            symbol = symbols[0]
            if data.empty:
                return []
            frame = data[symbol] if isinstance(data.columns, pd.MultiIndex) else data
            row = frame.iloc[0]
            bars.append(
                PriceBar(
                    symbol=symbol,
                    day=day,
                    open=Decimal(str(row["Open"])),
                    high=Decimal(str(row["High"])),
                    low=Decimal(str(row["Low"])),
                    close=Decimal(str(row["Close"])),
                    volume=int(row.get("Volume", 0)),
                    source="yfinance",
                )
            )
            return bars

        for symbol in symbols:
            frame = self._extract_symbol_frame(data, symbol)
            if frame.empty:
                continue
            row = frame.iloc[0]
            bar = self._build_bar(symbol=symbol, row_day=day, row=row)
            if bar is not None:
                bars.append(bar)

        return bars

    def fetch_daily_bars_range(
        self,
        symbols: list[str],
        start_day: date,
        end_day: date,
    ) -> list[PriceBar]:
        if not symbols:
            return []

        symbols = _normalize_symbols(symbols)
        if start_day > end_day:
            start_day, end_day = end_day, start_day

        try:
            data = yf.download(
                tickers=" ".join(symbols),
                start=start_day.isoformat(),
                end=(end_day + timedelta(days=1)).isoformat(),
                interval="1d",
                group_by="ticker",
                auto_adjust=False,
                threads=True,
                progress=False,
            )
        except Exception as exc:
            logger.exception(
                "yfinance range download failed for %s: %s", symbols, exc
            )
            return []

        bars: list[PriceBar] = []

        if len(symbols) == 1:
            symbol = symbols[0]
            if data.empty:
                return []
            frame = data[symbol] if isinstance(data.columns, pd.MultiIndex) else data
            for row_day, row in frame.iterrows():
                if not _is_trading_day(row_day.date()):
                    continue
                bars.append(
                    PriceBar(
                        symbol=symbol,
                        day=row_day.date(),
                        open=Decimal(str(row["Open"])),
                        high=Decimal(str(row["High"])),
                        low=Decimal(str(row["Low"])),
                        close=Decimal(str(row["Close"])),
                        volume=int(row.get("Volume", 0)),
                        source="yfinance",
                    )
                )
            return bars

        for symbol in symbols:
            frame = self._extract_symbol_frame(data, symbol)
            if frame.empty:
                continue
            for row_day, row in frame.iterrows():
                day_value = row_day.date()
                if not _is_trading_day(day_value):
                    continue
                bar = self._build_bar(symbol=symbol, row_day=day_value, row=row)
                if bar is not None:
                    bars.append(bar)

        return bars

    def _extract_symbol_frame(self, data, symbol: str):
        if data.empty:
            return data

        columns = data.columns
        if getattr(columns, "nlevels", 1) == 1:
            # Single ticker often returns flat columns: Open/High/Low/Close/Volume.
            return data

        level0 = {str(value) for value in columns.get_level_values(0)}
        level1 = {str(value) for value in columns.get_level_values(1)}

        if symbol in level0:
            frame = data[symbol]
        elif symbol in level1:
            frame = data.xs(symbol, axis=1, level=1)
        else:
            return data.iloc[0:0]

        return self._normalize_frame_columns(frame)

    def _normalize_frame_columns(self, frame):
        columns = frame.columns
        if getattr(columns, "nlevels", 1) == 1:
            return frame

        normalized = frame.copy()
        level0 = {str(value) for value in columns.get_level_values(0)}
        level1 = {str(value) for value in columns.get_level_values(1)}

        if "Open" in level0 and "Close" in level0:
            normalized.columns = columns.get_level_values(0)
            return normalized

        if "Open" in level1 and "Close" in level1:
            normalized.columns = columns.get_level_values(1)
            return normalized

        return normalized

    def _build_bar(self, symbol: str, row_day: date, row) -> PriceBar | None:
        required_columns = ("Open", "High", "Low", "Close")
        if any(column not in row.index for column in required_columns):
            logger.warning(
                "Skipping bar for %s on %s due to missing OHLC columns: %s",
                symbol,
                row_day,
                list(row.index),
            )
            return None

        open_value = row["Open"]
        high_value = row["High"]
        low_value = row["Low"]
        close_value = row["Close"]
        volume_value = row.get("Volume", 0)

        if any(str(value).lower() == "nan" for value in (open_value, high_value, low_value, close_value)):
            return None

        if str(volume_value).lower() == "nan":
            volume_value = 0

        return PriceBar(
            symbol=symbol,
            day=row_day,
            open=Decimal(str(open_value)),
            high=Decimal(str(high_value)),
            low=Decimal(str(low_value)),
            close=Decimal(str(close_value)),
            volume=int(volume_value),
            source="yfinance",
        )


class SqlPriceBarRepository(PriceBarRepository):
    """Postgres-backed repository for daily price bars."""

    def upsert_bars(self, bars: list[PriceBar]) -> int:
        if not bars:
            return 0

        payload = [
            {
                "symbol": bar.symbol.upper(),
                "day": bar.day,
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
                "volume": bar.volume,
                "source": bar.source,
            }
            for bar in bars
        ]

        stmt = insert(PriceBarModel).values(payload)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_price_bar_symbol_day_source",
            set_={
                "open": stmt.excluded.open,
                "high": stmt.excluded.high,
                "low": stmt.excluded.low,
                "close": stmt.excluded.close,
                "volume": stmt.excluded.volume,
            },
        )

        session = SessionLocal()
        try:
            result = session.execute(stmt)
            session.commit()
            return result.rowcount or 0
        finally:
            session.close()

    def get_latest_bars(self, symbols: list[str], day: date) -> list[PriceBar]:
        if not symbols:
            return []

        session = SessionLocal()
        try:
            stmt = (
                select(PriceBarModel)
                .where(PriceBarModel.symbol.in_(symbols))
                .where(PriceBarModel.day == day)
            )
            rows = session.execute(stmt).scalars().all()
            return [
                PriceBar(
                    symbol=row.symbol,
                    day=row.day,
                    open=Decimal(str(row.open)),
                    high=Decimal(str(row.high)),
                    low=Decimal(str(row.low)),
                    close=Decimal(str(row.close)),
                    volume=int(row.volume),
                    source=row.source,
                )
                for row in rows
            ]
        finally:
            session.close()


def _normalize_symbols(symbols: list[str]) -> list[str]:
    return [symbol.strip().upper() for symbol in symbols if symbol and symbol.strip()]


MARKET_TZ = ZoneInfo("America/New_York")
MARKET_CLOSE = time(16, 0)


class _NyseHolidayCalendar(AbstractHolidayCalendar):
    """Regular NYSE full-day closures (ad-hoc closures are not modelled)."""

    rules = [
        # A Saturday New Year's Day is not observed on the preceding Friday.
        Holiday("New Year's Day", month=1, day=1, observance=sunday_to_monday),
        USMartinLutherKingJr,
        USPresidentsDay,
        GoodFriday,
        USMemorialDay,
        Holiday("Juneteenth", month=6, day=19, start_date="2022-01-01", observance=nearest_workday),
        Holiday("Independence Day", month=7, day=4, observance=nearest_workday),
        USLaborDay,
        USThanksgivingDay,
        Holiday("Christmas Day", month=12, day=25, observance=nearest_workday),
    ]


@lru_cache(maxsize=32)
def _nyse_holidays(year: int) -> frozenset[date]:
    days = _NyseHolidayCalendar().holidays(start=f"{year}-01-01", end=f"{year}-12-31")
    return frozenset(day.date() for day in days)


def _is_trading_day(day: date) -> bool:
    return day.weekday() < 5 and day not in _nyse_holidays(day.year)


def last_completed_trading_day(now: datetime | None = None) -> date:
    """Most recent trading day whose regular session has closed, in US/Eastern time."""
    now_et = (now or datetime.now(MARKET_TZ)).astimezone(MARKET_TZ)
    day = now_et.date()
    if now_et.time() < MARKET_CLOSE:
        day -= timedelta(days=1)
    while not _is_trading_day(day):
        day -= timedelta(days=1)
    return day


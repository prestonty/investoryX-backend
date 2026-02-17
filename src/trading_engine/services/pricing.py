from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Protocol
import logging

import yfinance as yf
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from src.api.database.database import SessionLocal
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


def get_all_enabled_simulator_tickers() -> list[str]:
    session = SessionLocal()
    try:
        stmt = select(SimulatorTrackedStock.ticker).where(
            SimulatorTrackedStock.enabled.is_(True)
        )
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
            row = data.iloc[0]
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
            if symbol not in data.columns.get_level_values(0):
                continue
            frame = data[symbol]
            if frame.empty:
                continue
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
            for row_day, row in data.iterrows():
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
            if symbol not in data.columns.get_level_values(0):
                continue
            frame = data[symbol]
            if frame.empty:
                continue
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


def _is_trading_day(day: date) -> bool:
    return day.weekday() < 5


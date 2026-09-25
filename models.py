"""Shared domain types for fansboda-finance."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal


def week_start_of(day: date) -> date:
    """Return the Monday of the calendar week containing ``day``."""
    return day - timedelta(days=day.weekday())


@dataclass(frozen=True)
class TickerEntry:
    symbol: str
    company: str | None
    sector: str | None = None
    industry: str | None = None
    market: str | None = None
    exchange_name: str | None = None


@dataclass(frozen=True)
class MetricRow:
    ticker: str
    company: str | None
    trading_date: date
    sma_50: Decimal | None
    sma_200: Decimal | None
    current_price: Decimal | None
    currency: str | None = None
    momentum: Decimal | None = None
    z_score: Decimal | None = None

    @property
    def week_start(self) -> date:
        return week_start_of(self.trading_date)


@dataclass(frozen=True)
class MarketRow:
    market: str
    week_start: date
    momentum_mean: Decimal | None
    momentum_std: Decimal | None

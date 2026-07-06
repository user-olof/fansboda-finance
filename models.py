"""Shared domain types for fansboda-finance."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True)
class TickerEntry:
    symbol: str
    company: str | None
    sector: str | None = None
    industry: str | None = None


@dataclass(frozen=True)
class MetricRow:
    ticker: str
    company: str | None
    trading_date: date
    sma_50: Decimal | None
    sma_200: Decimal | None
    current_price: Decimal | None
    currency: str | None = None

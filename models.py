"""Shared domain types for fansboda-finance."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True)
class TickerEntry:
    symbol: str
    name: str | None


@dataclass(frozen=True)
class MetricRow:
    ticker: str
    name: str | None
    trading_date: date
    sma_50: Decimal | None
    sma_200: Decimal | None
    current_price: Decimal | None

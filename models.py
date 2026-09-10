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


@dataclass(frozen=True)
class MarketRow:
    market: str
    trading_date: date
    momentum_mean: Decimal | None
    momentum_std: Decimal | None


@dataclass(frozen=True)
class SmaSnapshot:
    """Minimal SMA history point for golden-cross detection (RFC-013)."""

    trading_date: date
    sma_50: Decimal | None
    sma_200: Decimal | None

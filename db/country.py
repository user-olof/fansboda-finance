"""Country-partitioned table routing (RFC-001 / PRD §6)."""

from __future__ import annotations

from enum import Enum


class CountrySet(str, Enum):
    US = "us"
    SWE = "swe"


def country_set_for(*, market: str | None = None, symbol: str = "") -> CountrySet:
    """Return US or SWE set from listing market and/or symbol suffix."""
    market_key = (market or "").strip().lower()
    symbol_key = symbol.strip().upper()
    if market_key == "se_market" or symbol_key.endswith(".ST"):
        return CountrySet.SWE
    return CountrySet.US


def infer_listing_market(*, market: str | None = None, symbol: str = "") -> str:
    """Return yfinance listing market, falling back from symbol when missing."""
    market_key = (market or "").strip()
    if market_key:
        return market_key
    if country_set_for(symbol=symbol) is CountrySet.SWE:
        return "se_market"
    return "us_market"


TICKERS_TABLE = {
    CountrySet.US: "us_tickers",
    CountrySet.SWE: "swe_tickers",
}
METRICS_TABLE = {
    CountrySet.US: "us_metrics",
    CountrySet.SWE: "swe_metrics",
}
MARKET_METRICS_TABLE = {
    CountrySet.US: "us_market_metrics",
    CountrySet.SWE: "swe_market_metrics",
}

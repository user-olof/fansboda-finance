"""Country-partitioned table routing (RFC-001 / PRD §6)."""

from __future__ import annotations

from enum import Enum


class CountrySet(str, Enum):
    US = "us"
    SWE = "swe"
    UK = "uk"


def country_set_for(*, market: str | None = None, symbol: str = "") -> CountrySet:
    """Return US, SWE, or UK set from listing market and/or symbol suffix."""
    market_key = (market or "").strip().lower()
    symbol_key = symbol.strip().upper()
    if market_key == "se_market" or symbol_key.endswith(".ST"):
        return CountrySet.SWE
    if market_key == "uk_market" or symbol_key.endswith(".L"):
        return CountrySet.UK
    return CountrySet.US


def infer_listing_market(*, market: str | None = None, symbol: str = "") -> str:
    """Return yfinance listing market, falling back from symbol when missing."""
    market_key = (market or "").strip()
    if market_key:
        return market_key
    country = country_set_for(symbol=symbol)
    if country is CountrySet.SWE:
        return "se_market"
    if country is CountrySet.UK:
        return "uk_market"
    return "us_market"


TICKERS_TABLE = {
    CountrySet.US: "us_tickers",
    CountrySet.SWE: "swe_tickers",
    CountrySet.UK: "uk_tickers",
}
METRICS_TABLE = {
    CountrySet.US: "us_metrics",
    CountrySet.SWE: "swe_metrics",
    CountrySet.UK: "uk_metrics",
}
MARKET_METRICS_TABLE = {
    CountrySet.US: "us_market_metrics",
    CountrySet.SWE: "swe_market_metrics",
    CountrySet.UK: "uk_market_metrics",
}
BY_SECTOR_TABLE = {
    CountrySet.US: "us_by_sector",
    CountrySet.SWE: "swe_by_sector",
    CountrySet.UK: "uk_by_sector",
}


def _table_placeholders(country: CountrySet) -> dict[str, str]:
    """Allowlisted table names for SQL templates (never user input)."""
    return {
        "tickers": TICKERS_TABLE[country],
        "metrics": METRICS_TABLE[country],
        "market_metrics": MARKET_METRICS_TABLE[country],
        "by_sector": BY_SECTOR_TABLE[country],
    }


def sql_for_countries(template: str) -> dict[CountrySet, str]:
    """Format ``template`` once per country set.

    Placeholders: ``{tickers}``, ``{metrics}``, ``{market_metrics}``,
    ``{by_sector}``.
    """
    return {
        country: template.format(**_table_placeholders(country))
        for country in CountrySet
    }


def union_all_sql(fragment: str) -> str:
    """Join a per-country SQL fragment with ``UNION ALL``."""
    return "\nUNION ALL\n".join(
        fragment.format(**_table_placeholders(country)) for country in CountrySet
    )

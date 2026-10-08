"""Database access for the shared ``indices`` table (PRD §5.8 / RFC-015 / RFC-018)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

import psycopg2

from db.country import CountrySet, sql_for_countries
from db.metrics import retention_cutoff
from equity_index import (
    INDEX_DEFINITIONS,
    IndexDefinition,
    IndexRow,
    WeekLevels,
    build_index_row,
    sector_index_definition,
    with_sector_z_scores,
)

# Sector labels are normalized to the yfinance ``sectorKey`` form so a display
# name fallback ("Consumer Cyclical") and a key ("consumer-cyclical") merge;
# a blank sector becomes NULL (market index only, FR-34a).
SECTOR_KEY_SQL = "NULLIF(lower(replace(btrim(t.sector), ' ', '-')), '')"

# Latest stored row per index ticker of one country before the week: the pin
# of the weekly run's daily series (specs/002-index-true-sma).
LOAD_PREVIOUS_INDICES_SQL = """
SELECT DISTINCT ON (ticker) ticker, trading_date, current_price
FROM indices
WHERE country = %s AND trading_date < %s
ORDER BY ticker, trading_date DESC
"""

# Per-week stats are grouped with GROUPING SETS ((), (sector)): the grand
# total (GROUPING = 1) is the market index, each sector group a sector index.
# Supplies count and pct_uptrend; the levels come from the index's daily series
# (specs/002-index-true-sma).
BASE_WEEK_STATS_SQL = sql_for_countries(
    f"""
WITH s AS (
    SELECT m.trading_date, m.sma_50, m.sma_200,
           {SECTOR_KEY_SQL} AS sector
    FROM {{metrics}} m
    JOIN {{tickers}} t ON t.symbol = m.ticker
    WHERE m.week_start = %s
      AND m.current_price > 0 AND m.sma_50 > 0 AND m.sma_200 > 0
)
SELECT
    GROUPING(sector),
    sector,
    COUNT(*),
    MAX(trading_date),
    100.0 * AVG(CASE WHEN sma_50 > sma_200 THEN 1 ELSE 0 END)
FROM s
GROUP BY GROUPING SETS ((), (sector))
"""
)

INSERT_INDEX_SQL = """
INSERT INTO indices (
    ticker, sector, country, currency, trading_date, updated_at,
    ticker_count, current_price, sma_50, sma_200, pct_uptrend, momentum, z_score
)
VALUES (%s, %s, %s, %s, %s, NOW(), %s, %s, %s, %s, %s, %s, %s)
"""

DELETE_COUNTRY_WEEK_SQL = """
DELETE FROM indices
WHERE country = %s AND trading_date >= %s AND trading_date < %s
"""

DELETE_COUNTRY_INDICES_SQL = "DELETE FROM indices WHERE country = %s"

LOAD_COUNTRY_INDEX_TICKERS_SQL = "SELECT DISTINCT ticker FROM indices WHERE country = %s"

LOAD_COUNTRY_WEEK_INDICES_SQL = """
SELECT ticker, sector, currency, trading_date, ticker_count,
       current_price, sma_50, sma_200, pct_uptrend, momentum
FROM indices
WHERE country = %s AND trading_date >= %s AND trading_date < %s
"""

DELETE_STALE_INDICES_SQL = "DELETE FROM indices WHERE trading_date < %s"

def _group_stats(rows: list[tuple]) -> dict[str | None, tuple]:
    """Map grouped stats rows to ``{None: market, sector: sector stats}``."""
    stats: dict[str | None, tuple] = {}
    for is_market, sector, *values in rows:
        if is_market:
            stats[None] = tuple(values)
        elif sector is not None:
            stats[sector] = tuple(values)
    return stats


def _definition(country: CountrySet, sector: str | None) -> IndexDefinition:
    if sector is None:
        return INDEX_DEFINITIONS[country]
    return sector_index_definition(country, sector)


def _insert_values(row: IndexRow) -> tuple:
    return (
        row.ticker,
        row.sector,
        row.country.value,
        row.currency,
        row.trading_date,
        row.ticker_count,
        row.current_price,
        row.sma_50,
        row.sma_200,
        row.pct_uptrend,
        row.momentum,
        row.z_score,
    )


@dataclass(frozen=True)
class IndexWriteResult:
    rows: list[IndexRow]


def _sector_of(country: CountrySet, ticker: str) -> str | None:
    """Sector key of an index ticker (``US-IDX-FINANCIAL-SERVICES`` →
    ``financial-services``); None for the market index."""
    market = INDEX_DEFINITIONS[country].ticker
    key = ticker[len(market) + 1 :].lower() if ticker.startswith(f"{market}-") else None
    return key or None


def _stored_row(country: CountrySet, values: tuple) -> IndexRow:
    """An ``indices`` row read back, with ``sector_key`` derived from the ticker."""
    (
        ticker,
        sector,
        currency,
        trading_date,
        ticker_count,
        current_price,
        sma_50,
        sma_200,
        pct_uptrend,
        momentum,
    ) = values
    return IndexRow(
        ticker=ticker,
        sector=sector,
        country=country,
        trading_date=trading_date,
        ticker_count=ticker_count,
        current_price=current_price,
        sma_50=sma_50,
        sma_200=sma_200,
        momentum=momentum,
        sector_key=_sector_of(country, ticker),
        currency=currency,
        pct_uptrend=pct_uptrend,
    )


def write_index_weeks(
    database_url: str,
    week_levels: dict[date, dict[str, WeekLevels]],
    *,
    country: CountrySet,
    rebuild: bool = False,
    only_tickers: set[str] | None = None,
) -> IndexWriteResult:
    """Store the country's index rows per week from their daily-series levels.

    Stock count and pct_uptrend come from the week's stored metrics; an index
    whose group has no stock with a positive price and SMAs gets no row
    (FR-41). ``rebuild=True`` first deletes every row for the country. All of
    the country's rows in a week are replaced (sector z-scores need the whole
    week); with ``only_tickers`` only those indices are written, the other
    stored rows of the week are kept and their z-scores recomputed. One
    transaction.
    """
    written: list[IndexRow] = []
    with psycopg2.connect(database_url) as conn:
        with conn.cursor() as cur:
            if rebuild:
                cur.execute(DELETE_COUNTRY_INDICES_SQL, (country.value,))
            for week_start in sorted(week_levels):
                cur.execute(BASE_WEEK_STATS_SQL[country], (week_start,))
                stats = _group_stats(cur.fetchall())

                week_rows: list[IndexRow] = []
                for ticker, levels in sorted(week_levels[week_start].items()):
                    if only_tickers is not None and ticker not in only_tickers:
                        continue
                    sector = _sector_of(country, ticker)
                    if sector not in stats:
                        continue
                    ticker_count, _, pct = stats[sector]
                    row = build_index_row(
                        _definition(country, sector),
                        trading_date=levels.trading_date,
                        ticker_count=ticker_count,
                        levels=levels.levels,
                        pct_uptrend=pct,
                    )
                    if row is not None:
                        week_rows.append(row)

                week_end = week_start + timedelta(days=7)
                if only_tickers is None:
                    week_rows = with_sector_z_scores(week_rows)
                    stored_rows = week_rows
                else:
                    if not week_rows:
                        continue
                    cur.execute(
                        LOAD_COUNTRY_WEEK_INDICES_SQL,
                        (country.value, week_start, week_end),
                    )
                    kept = [
                        _stored_row(country, values)
                        for values in cur.fetchall()
                        if values[0] not in only_tickers
                    ]
                    stored_rows = with_sector_z_scores(kept + week_rows)
                    week_rows = [r for r in stored_rows if r.ticker in only_tickers]
                cur.execute(DELETE_COUNTRY_WEEK_SQL, (country.value, week_start, week_end))
                for row in stored_rows:
                    cur.execute(INSERT_INDEX_SQL, _insert_values(row))
                written.extend(week_rows)
        conn.commit()

    return IndexWriteResult(rows=written)


def load_previous_indices(
    database_url: str, country: CountrySet, before: date
) -> dict[str, tuple[date, Decimal]]:
    """Latest stored ``(trading_date, current_price)`` per index before ``before``."""
    with psycopg2.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(LOAD_PREVIOUS_INDICES_SQL, (country.value, before))
            return {ticker: (day, price) for ticker, day, price in cur.fetchall()}


def load_index_tickers(database_url: str, country: CountrySet) -> set[str]:
    """Index tickers the country has stored rows for (R11 / R12)."""
    with psycopg2.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(LOAD_COUNTRY_INDEX_TICKERS_SQL, (country.value,))
            return {row[0] for row in cur.fetchall()}


def purge_stale_indices(database_url: str, retention_days: int) -> int:
    """Delete ``indices`` rows with ``trading_date`` before the retention cutoff."""
    cutoff = retention_cutoff(retention_days)
    with psycopg2.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(DELETE_STALE_INDICES_SQL, (cutoff,))
            deleted = cur.rowcount
        conn.commit()

    return deleted

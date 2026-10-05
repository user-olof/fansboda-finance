"""Database access for the shared ``indices`` table (PRD §5.8 / RFC-015 / RFC-018)."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import psycopg2

from config import DEFAULT_OUTLIER_MAX_GROWTH, DEFAULT_OUTLIER_MIN_GROWTH
from db.country import CountrySet, sql_for_countries
from db.metrics import retention_cutoff
from equity_index import (
    INDEX_DEFINITIONS,
    IndexDefinition,
    IndexLevels,
    IndexRow,
    build_base_row,
    build_chained_row,
    sector_index_definition,
    with_sector_z_scores,
)
from models import week_start_of

# Sector labels are normalized to the yfinance ``sectorKey`` form so a display
# name fallback ("Consumer Cyclical") and a key ("consumer-cyclical") merge;
# a blank sector becomes NULL (market index only, FR-34a).
SECTOR_KEY_SQL = "NULLIF(lower(replace(btrim(t.sector), ' ', '-')), '')"

# Latest stored row per index ticker of one country before the week.
LOAD_PREVIOUS_INDICES_SQL = """
SELECT DISTINCT ON (ticker) ticker, trading_date, current_price, sma_50, sma_200
FROM indices
WHERE country = %s AND trading_date < %s
ORDER BY ticker, trading_date DESC
"""

# Per-week stats are grouped with GROUPING SETS ((), (sector)): the grand
# total (GROUPING = 1) is the market index, each sector group a sector index.
BASE_WEEK_STATS_SQL = sql_for_countries(
    f"""
WITH s AS (
    SELECT m.trading_date, m.current_price, m.sma_50, m.sma_200,
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
    AVG(sma_50 / current_price),
    AVG(sma_200 / current_price),
    100.0 * AVG(CASE WHEN sma_50 > sma_200 THEN 1 ELSE 0 END)
FROM s
GROUP BY GROUPING SETS ((), (sector))
"""
)

# Equal-weighted mean of the stocks' stored weekly growth (FR-37), over stocks
# with positive price / SMAs and all three growth values inside the outlier
# bounds (FR-36 / FR-37b); one set drives all three levels and pct_uptrend.
CHAINED_WEEK_STATS_SQL = sql_for_countries(
    f"""
WITH s AS (
    SELECT m.trading_date, m.sma_50, m.sma_200,
           m.price_growth, m.sma_50_growth, m.sma_200_growth,
           {SECTOR_KEY_SQL} AS sector
    FROM {{metrics}} m
    JOIN {{tickers}} t ON t.symbol = m.ticker
    WHERE m.week_start = %s
      AND m.current_price > 0 AND m.sma_50 > 0 AND m.sma_200 > 0
      AND m.price_growth BETWEEN %s AND %s
      AND m.sma_50_growth BETWEEN %s AND %s
      AND m.sma_200_growth BETWEEN %s AND %s
)
SELECT
    GROUPING(sector),
    sector,
    COUNT(*),
    MAX(trading_date),
    AVG(price_growth),
    AVG(sma_50_growth),
    AVG(sma_200_growth),
    100.0 * AVG(CASE WHEN sma_50 > sma_200 THEN 1 ELSE 0 END)
FROM s
GROUP BY GROUPING SETS ((), (sector))
"""
)

# Gap week (FR-37a) for one index: its previous stored week is not the previous
# calendar week, so growth is the ratio of stored rows between the two weeks,
# with the same outlier bounds applied to each ratio. A NULL sector parameter
# selects the whole set (market index).
GAP_WEEK_STATS_SQL = sql_for_countries(
    f"""
SELECT
    COUNT(*),
    MAX(cur.trading_date),
    AVG(cur.current_price / prev.current_price - 1),
    AVG(cur.sma_50 / prev.sma_50 - 1),
    AVG(cur.sma_200 / prev.sma_200 - 1),
    100.0 * AVG(CASE WHEN cur.sma_50 > cur.sma_200 THEN 1 ELSE 0 END)
FROM {{metrics}} cur
JOIN {{metrics}} prev
  ON prev.ticker = cur.ticker
 AND prev.week_start = %s
JOIN {{tickers}} t ON t.symbol = cur.ticker
WHERE cur.week_start = %s
  AND (%s::text IS NULL OR {SECTOR_KEY_SQL} = %s)
  AND cur.current_price > 0 AND cur.sma_50 > 0 AND cur.sma_200 > 0
  AND prev.current_price > 0 AND prev.sma_50 > 0 AND prev.sma_200 > 0
  AND cur.current_price / prev.current_price - 1 BETWEEN %s AND %s
  AND cur.sma_50 / prev.sma_50 - 1 BETWEEN %s AND %s
  AND cur.sma_200 / prev.sma_200 - 1 BETWEEN %s AND %s
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

DELETE_STALE_INDICES_SQL = "DELETE FROM indices WHERE trading_date < %s"

_NO_STATS = (0, None, None, None, None, None)


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


def write_index_weeks(
    database_url: str,
    week_starts: list[date],
    *,
    country: CountrySet,
    rebuild: bool = False,
    max_growth: float = DEFAULT_OUTLIER_MAX_GROWTH,
    min_growth: float = DEFAULT_OUTLIER_MIN_GROWTH,
) -> list[IndexRow]:
    """Compute and store the country's market and sector indices per week.

    Weeks run in ascending order and each index chains from its own latest
    stored row before the week, so later weeks see rows written earlier in the
    same call. All of the country's rows in the week are replaced (sector
    z-scores need the whole week). ``rebuild=True`` first deletes every row
    for the country, making each index's earliest week its base week. An index
    with no contributing stocks gets no row that week (FR-41). Stock-weeks with
    growth outside ``[min_growth, max_growth]`` are excluded (FR-37b). One
    transaction.
    """
    bounds = (Decimal(str(min_growth)), Decimal(str(max_growth))) * 3
    written: list[IndexRow] = []
    with psycopg2.connect(database_url) as conn:
        with conn.cursor() as cur:
            if rebuild:
                cur.execute(DELETE_COUNTRY_INDICES_SQL, (country.value,))
            for week_start in sorted(set(week_starts)):
                cur.execute(LOAD_PREVIOUS_INDICES_SQL, (country.value, week_start))
                previous = {row[0]: row[1:] for row in cur.fetchall()}
                cur.execute(BASE_WEEK_STATS_SQL[country], (week_start,))
                base = _group_stats(cur.fetchall())
                cur.execute(CHAINED_WEEK_STATS_SQL[country], (week_start, *bounds))
                chained = _group_stats(cur.fetchall())

                week_rows: list[IndexRow] = []
                for sector in sorted(base, key=lambda key: (key is not None, key or "")):
                    definition = _definition(country, sector)
                    prev = previous.get(definition.ticker)
                    if prev is None:
                        ticker_count, trading_date, sma_50_ratio, sma_200_ratio, pct = (
                            base[sector]
                        )
                        row = build_base_row(
                            definition,
                            trading_date=trading_date,
                            ticker_count=ticker_count,
                            avg_sma_50_ratio=sma_50_ratio,
                            avg_sma_200_ratio=sma_200_ratio,
                            pct_uptrend=pct,
                        )
                    else:
                        prev_date, prev_price, prev_sma_50, prev_sma_200 = prev
                        prev_week = week_start_of(prev_date)
                        if prev_week == week_start - timedelta(days=7):
                            stats = chained.get(sector, _NO_STATS)
                        else:
                            cur.execute(
                                GAP_WEEK_STATS_SQL[country],
                                (prev_week, week_start, sector, sector, *bounds),
                            )
                            stats = cur.fetchone()
                        ticker_count, trading_date, g_price, g_sma_50, g_sma_200, pct = (
                            stats
                        )
                        row = build_chained_row(
                            definition,
                            IndexLevels(prev_price, prev_sma_50, prev_sma_200),
                            trading_date=trading_date,
                            ticker_count=ticker_count,
                            growth_price=g_price,
                            growth_sma_50=g_sma_50,
                            growth_sma_200=g_sma_200,
                            pct_uptrend=pct,
                        )
                    if row is not None:
                        week_rows.append(row)

                week_rows = with_sector_z_scores(week_rows)
                cur.execute(
                    DELETE_COUNTRY_WEEK_SQL,
                    (country.value, week_start, week_start + timedelta(days=7)),
                )
                for row in week_rows:
                    cur.execute(INSERT_INDEX_SQL, _insert_values(row))
                written.extend(week_rows)
        conn.commit()

    return written


def purge_stale_indices(database_url: str, retention_days: int) -> int:
    """Delete ``indices`` rows with ``trading_date`` before the retention cutoff."""
    cutoff = retention_cutoff(retention_days)
    with psycopg2.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(DELETE_STALE_INDICES_SQL, (cutoff,))
            deleted = cur.rowcount
        conn.commit()

    return deleted
